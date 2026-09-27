# SPDX-License-Identifier: GPL-3.0-or-later
"""캐릭터 시트 — 말투·호칭·관계를 번역기에 **필요한 만큼만** 넘깁니다.

AI 번역기(Claude·GPT·Gemini)에 매번 캐릭터 설정을 통째로 보내면 돈이
샙니다. 20줄 묶음에 엄마와 주인공만 나온다면 그 둘의 설정과 **서로에게
쓰는 말투**만 있으면 됩니다. 용어집도 그 묶음 원문에 나오는 말만 보냅니다.

구조 (작업 폴더의 ``characters.json``)::

    {
      "style": "전체 번역 지침. 매 요청에 들어갑니다 — 짧게.",
      "characters": {
        "mom": {
          "names": ["母", "母親", "お母さん"],   ← 원문에 나오는 모든 호칭
          "ko_name": "엄마",
          "gender": "여성", "age": "40대",
          "profile": "잔소리가 많지만 다정함",
          "speech": "~하렴, ~니? 같은 엄마 말투",
          "first_person": "엄마",
          "quirks": "한숨을 자주 쉼", "avoid": "욕설",
          "examples": [{"ja": "…", "ko": "…"}],
          "to": {
            "player": {"register": "반말", "calls_them": "너",
                       "speech": "…", "examples": [{"ja": "…", "ko": "…"}]},
            "*": {"register": "존댓말"}          ← 그 밖의 상대
          }
        }
      },
      "glossary": {"精力": "정력", "度胸": {"ko": "배짱", "note": "스탯 이름"}}
    }

화자(Location.speaker)는 게임 원문의 이름 그대로 들어옵니다. ``names`` 에
그 이름을 적어 두면 연결됩니다. RPG Maker 는 얼굴 그림만 알 때
``얼굴:Actor1`` 로 들어오니 그것도 ``names`` 에 적을 수 있습니다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

FILENAME = "characters.json"
ANY = "*"

# 인물 한 명의 필드 중 번역기에 보낼 것 (순서 = 보내는 순서).
_PROFILE_KEYS = ("ko_name", "gender", "age", "profile", "speech",
                 "first_person", "quirks", "avoid", "examples")
# 대사 속에 **이름만** 나오는 인물(말하지도 듣지도 않음)에게는 호칭 번역에
# 필요한 것만 보냅니다. 말투·예문까지 보내면 돈만 듭니다.
_MENTION_KEYS = ("ko_name", "gender")
# 대사 속 이름으로 인물을 찾을 때, 너무 짧은 이름은 오탐이 많습니다.
_MIN_MENTION = 2


def _norm(name: str) -> str:
    return re.sub(r"[\s　・『』「」【】()（）]", "", str(name or "")).casefold()


@dataclass
class Sheet:
    style: str = ""
    characters: dict[str, dict] = field(default_factory=dict)
    glossary: dict[str, Any] = field(default_factory=dict)
    _alias: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for key, ch in self.characters.items():
            for name in [key, ch.get("ko_name", ""), *(ch.get("names") or [])]:
                n = _norm(name)
                if n:
                    self._alias.setdefault(n, key)

    # ---------------------------------------------------------- 찾기
    def who(self, name: str) -> str:
        """게임 속 이름(화자) → 시트의 인물 키. 모르면 빈칸."""
        n = _norm(name)
        if not n:
            return ""
        if n in self._alias:
            return self._alias[n]
        # RPG Maker 얼굴 그림: '얼굴:Actor1#3' 도 '얼굴:Actor1' 로 찾습니다.
        base = n.split("#", 1)[0]
        return self._alias.get(base, "")

    def mentioned(self, texts: Iterable[str]) -> list[str]:
        """대사 속에 이름이 나오는 인물."""
        blob = _norm("".join(texts))
        out = []
        for alias, key in self._alias.items():
            if len(alias) >= _MIN_MENTION and alias in blob and key not in out:
                out.append(key)
        return out

    # ---------------------------------------------------------- 고르기
    def pick(self, lines: list[dict], texts: Iterable[str] = ()) -> dict:
        """이번 묶음에 필요한 인물 설정만.

        ``lines`` 는 ``{"speaker", "listener"}`` 를 가진 줄들입니다. 말하는
        사람·듣는 사람은 설정과 **그 상대에게 쓰는 말투**까지, 대사 속에
        이름만 나오는 사람은 기본 설정(호칭·성별 등)만 보냅니다.
        """
        pairs: set[tuple[str, str]] = set()
        speaking: list[str] = []
        for line in lines:
            a = self.who(line.get("speaker", ""))
            b = self.who(line.get("listener", ""))
            for k in (a, b):
                if k and k not in speaking:
                    speaking.append(k)
            if a:
                pairs.add((a, b or ANY))
        mention = [k for k in self.mentioned(texts) if k not in speaking]

        out: dict[str, dict] = {}
        for key in speaking + mention:
            ch = self.characters.get(key) or {}
            keys = _PROFILE_KEYS if key in speaking else _MENTION_KEYS
            item = {k: ch[k] for k in keys if ch.get(k)}
            if key in speaking:
                to = ch.get("to") or {}
                chosen = {}
                for a, b in sorted(pairs):
                    if a != key:
                        continue
                    rule = to.get(b) if b != ANY else None
                    if rule is None:
                        rule = to.get(ANY)
                        b = ANY
                    if rule:
                        chosen[b] = rule
                if chosen:
                    item["to"] = chosen
            out[key] = item
        return out

    def pick_glossary(self, texts: Iterable[str],
                      extra: dict[str, str] | None = None) -> dict[str, Any]:
        """이번 묶음 원문에 **나오는** 용어만. 긴 용어 먼저 봅니다."""
        blob = "".join(texts)
        merged: dict[str, Any] = dict(self.glossary)
        merged.update(extra or {})
        return {src: merged[src]
                for src in sorted(merged, key=len, reverse=True)
                if src and src in blob}


def empty() -> Sheet:
    return Sheet()


def parse(raw: str | dict) -> Sheet:
    """JSON 문자열/사전 → Sheet. 형식이 틀리면 ``ValueError`` (이유 포함)."""
    if isinstance(raw, str):
        if not raw.strip():
            return Sheet()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"캐릭터 시트 JSON 이 깨졌습니다 "
                             f"({exc.lineno}번째 줄 {exc.colno}칸): {exc.msg}") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("캐릭터 시트 맨 바깥은 { } 여야 합니다.")
    chars = data.get("characters") or {}
    if not isinstance(chars, dict):
        raise ValueError('"characters" 는 { "키": {...} } 모양이어야 합니다.')
    for key, ch in chars.items():
        if not isinstance(ch, dict):
            raise ValueError(f'"{key}" 의 설정이 {{ }} 가 아닙니다.')
        names = ch.get("names", [])
        if not isinstance(names, list):
            raise ValueError(f'"{key}.names" 는 ["이름", ...] 목록이어야 합니다.')
        to = ch.get("to", {})
        if not isinstance(to, dict):
            raise ValueError(f'"{key}.to" 는 {{ "상대 키": {{...}} }} 모양이어야 합니다.')
        for other in to:
            if other != ANY and other not in chars:
                raise ValueError(f'"{key}.to" 의 "{other}" 는 characters 에 없는 '
                                 f'키입니다 (그 밖의 모든 상대는 "*").')
    glossary = data.get("glossary") or {}
    if not isinstance(glossary, dict):
        raise ValueError('"glossary" 는 { "원문": "번역" } 모양이어야 합니다.')
    return Sheet(style=str(data.get("style") or ""), characters=chars,
                 glossary=glossary)


def load(workdir: Path) -> Sheet:
    """작업 폴더의 ``characters.json``. 없으면 빈 시트."""
    path = Path(workdir) / FILENAME
    if not path.is_file():
        return Sheet()
    return parse(path.read_text("utf-8-sig"))

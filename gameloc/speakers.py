# SPDX-License-Identifier: GPL-3.0-or-later
"""유니티 데이터에서 **누가 누구에게** 하는 말인지 찾아 둡니다.

번역기에 넘겨 말투(반말·존댓말)를 고르게 하고, 캐릭터 시트에서 그 인물
몫만 골라 보내는 열쇠로 씁니다. 틀리게 붙이느니 비워 둡니다.

화자는 오브젝트 하나만 봐서는 이름까지 알 수 없는 경우가 많습니다.
채팅 한 줄에는 보낸 사람의 **Id** 만 있고, 이름(NickName)은 캐릭터 오브젝트에
따로 있습니다. 트윗 본문은 아예 번역 DB(LocalizedStringDatabase)에 있고,
작성자는 트윗 쪽에 있습니다. 그래서 파일을 읽는 동안에는 자리표시자
(``@id:…``, ``@pid:…``, ``@sid:…``)를 적어 두고, 다 읽은 뒤 :meth:`Book.resolve`
가 이름으로 바꿉니다. 못 풀면 빈칸이 됩니다.
"""

from __future__ import annotations

import re
from typing import Any

# [SerializeReference] 대화 조각 → (화자, 듣는 사람).
# ニートの俺は… 의 식사 대화: 게임 코드(TalkPresenter)에서 Listen 은
# CoMotherTalkLine(엄마 대사), Say 는 CoPlayerTalkLine(주인공 대사)로 그립니다.
# 이름은 그 게임 CharacterMaster 의 NickName 과 같게 적습니다.
_REF_SPEAKERS: dict[str, tuple[str, str]] = {
    "Apps.Talks.TalkListenEntry": ("母", "プレイヤー"),
    "Apps.Talks.TalkSayEntry": ("プレイヤー", "母"),
}
# 선택지 한 줄 안의 필드별: say 는 주인공이, response 는 엄마가.
_REF_FIELD_SPEAKERS: dict[tuple[str, str], tuple[str, str]] = {
    ("Apps.Talks.TalkChoiceEntry", "say"): ("プレイヤー", "母"),
    ("Apps.Talks.TalkChoiceEntry", "response"): ("母", "プレイヤー"),
}
_SENDER_KEYS = ("_sender", "_author", "_speaker", "sender", "author", "speaker")

_REF_PTR = re.compile(r"^references\.RefIds\[(\d+)\]\.data\.(.+)$")
_RECORD_PTR = re.compile(r"^_records\[(\d+)\]\.text$")


def _pointer(value: Any) -> str:
    """보낸 사람 칸의 값 → 자리표시자. 모르는 모양이면 빈칸."""
    if isinstance(value, dict):
        if isinstance(value.get("_value"), str) and value["_value"]:
            return f"@id:{value['_value']}"
        pid = value.get("m_PathID")
        if isinstance(pid, int) and pid:
            return f"@pid:{pid}"
    return ""


def _sender_of(data: dict) -> str:
    for key in _SENDER_KEYS:
        got = _pointer(data.get(key))
        if got:
            return got
    return ""


def _string_ids(node: Any):
    """LocalizedString(``{"_stringId": ...}``) 값을 전부."""
    if isinstance(node, dict):
        sid = node.get("_stringId")
        if isinstance(sid, str) and sid:
            yield sid
        for v in node.values():
            yield from _string_ids(v)
    elif isinstance(node, list):
        for v in node:
            yield from _string_ids(v)


class Book:
    """파일 하나를 읽는 동안 모으는 이름표."""

    def __init__(self) -> None:
        self.by_id: dict[str, str] = {}      # 오브젝트 m_Name(Id) → NickName
        self.by_pid: dict[int, str] = {}     # path_id → NickName
        self.by_sid: dict[str, str] = {}     # 번역 DB 문장 Id → 보낸 사람 자리표시자

    def learn(self, tree: dict, path_id: int) -> None:
        """이 오브젝트에서 알 수 있는 이름·연결을 적어 둡니다."""
        nick = tree.get("NickName")
        if isinstance(nick, str) and nick.strip():
            self.by_pid[path_id] = nick.strip()
            name = tree.get("m_Name")
            if isinstance(name, str) and name:
                self.by_id[name] = nick.strip()
        for ref in ((tree.get("references") or {}).get("RefIds") or []):
            data = ref.get("data") if isinstance(ref, dict) else None
            if not isinstance(data, dict):
                continue
            who = _sender_of(data)
            if not who:
                continue
            for sid in _string_ids(data):
                self.by_sid.setdefault(sid, who)

    def mark(self, tree: dict, ptr: str) -> tuple[str, str]:
        """이 자리의 (화자, 듣는 사람). 이름을 아직 모르면 자리표시자."""
        m = _REF_PTR.match(ptr)
        if m:
            refs = (tree.get("references") or {}).get("RefIds") or []
            i = int(m.group(1))
            if i < len(refs) and isinstance(refs[i], dict):
                ref = refs[i]
                typ = ref.get("type") or {}
                cls = ".".join(x for x in (typ.get("ns"), typ.get("class")) if x)
                leaf = m.group(2).rsplit(".", 1)[-1].split("[", 1)[0]
                if (cls, leaf) in _REF_FIELD_SPEAKERS:
                    return _REF_FIELD_SPEAKERS[(cls, leaf)]
                if cls in _REF_SPEAKERS:
                    return _REF_SPEAKERS[cls]
                data = ref.get("data")
                if isinstance(data, dict):
                    return _sender_of(data), ""
            return "", ""
        m = _RECORD_PTR.match(ptr)
        if m:
            records = tree.get("_records") or []
            i = int(m.group(1))
            if i < len(records) and isinstance(records[i], dict):
                sid = records[i].get("stringId")
                if isinstance(sid, str) and sid:
                    return f"@sid:{sid}", ""
        return "", ""

    def resolve(self, name: str) -> str:
        """자리표시자 → 이름. 이름이거나 못 풀면 그대로/빈칸."""
        for _ in range(3):                   # @sid → @id → 이름
            if not name.startswith("@"):
                return name
            kind, _, key = name[1:].partition(":")
            if kind == "id":
                name = self.by_id.get(key, "")
            elif kind == "pid":
                name = self.by_pid.get(int(key), "") if key.isdigit() else ""
            elif kind == "sid":
                name = self.by_sid.get(key, "")
            else:
                return ""
        return "" if name.startswith("@") else name

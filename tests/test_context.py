# SPDX-License-Identifier: GPL-3.0-or-later
"""캐릭터 시트 · 골라 보내기 · 앞 대사 · id 로 짝 맞추기."""

from __future__ import annotations

import json

import pytest

from gameloc import charsheet, translate as T
from gameloc.model import Entry, Location

SHEET = {
    "style": "구어체로.",
    "characters": {
        "mom": {"names": ["母", "お母さん"], "ko_name": "엄마", "gender": "여성",
                "speech": "엄마 말투", "examples": [{"ja": "a", "ko": "b"}],
                "to": {"player": {"register": "반말"}, "*": {"register": "존댓말"}}},
        "player": {"names": ["プレイヤー", "俺"], "ko_name": "주인공",
                   "to": {"mom": {"register": "반말", "calls_them": "엄마"}}},
        "teacher": {"names": ["先生"], "ko_name": "선생님", "gender": "남성",
                    "speech": "딱딱함"},
    },
    "glossary": {"精力": "정력", "度胸": {"ko": "배짱", "note": "스탯"}},
}


# ── 시트 읽기 · 검사 ───────────────────────────────────────────────

def test_parse_rejects_unknown_relation_target():
    bad = json.loads(json.dumps(SHEET))
    bad["characters"]["mom"]["to"]["dad"] = {"register": "반말"}
    with pytest.raises(ValueError, match="dad"):
        charsheet.parse(bad)


def test_parse_reports_broken_json_position():
    with pytest.raises(ValueError, match="줄"):
        charsheet.parse('{"characters": {')


def test_who_matches_all_names_and_rpgmaker_faces():
    sheet = charsheet.parse({"characters": {
        "yuri": {"names": ["ユリ", "얼굴:Actor1"]}}})
    assert sheet.who("ユリ") == "yuri"
    assert sheet.who("얼굴:Actor1#3") == "yuri"
    assert sheet.who("누구") == ""


# ── 고르기: 그 묶음에 필요한 것만 ─────────────────────────────────────

def test_pick_sends_only_speakers_and_their_mutual_speech():
    sheet = charsheet.parse(SHEET)
    got = sheet.pick([{"speaker": "母", "listener": "プレイヤー"},
                      {"speaker": "プレイヤー", "listener": "母"}])
    assert set(got) == {"mom", "player"}                 # 선생님은 안 감
    assert got["mom"]["to"] == {"player": {"register": "반말"}}   # '*' 는 안 감
    assert got["player"]["to"] == {"mom": {"register": "반말", "calls_them": "엄마"}}


def test_pick_unknown_listener_uses_wildcard_and_mentions_are_light():
    sheet = charsheet.parse(SHEET)
    got = sheet.pick([{"speaker": "母"}], ["先生に言われた"])
    assert got["mom"]["to"] == {"*": {"register": "존댓말"}}
    assert got["teacher"] == {"ko_name": "선생님", "gender": "남성"}


def test_pick_glossary_only_terms_in_batch():
    sheet = charsheet.parse(SHEET)
    assert sheet.pick_glossary(["精力が回復した"], {"ジム": "헬스장"}) == {"精力": "정력"}


# ── 번역: 묶음마다 무엇을 보내나 ─────────────────────────────────────

class _Fake(T._LLM):
    key_id = "fake-ctx"
    label = "fake"
    retry_delay = 0
    batch_size = 20
    workers = 1

    def __init__(self, drop_first_call: str = ""):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []
        self.drop = drop_first_call

    def _ask(self, prompt, payload):
        req = json.loads(payload)
        self.calls.append((prompt, req))
        out = {l["id"]: "번역:" + l["text"] for l in req["lines"]}
        if self.drop and len(self.calls) == 1:
            out = {k: v for k, v in out.items()
                   if not v.endswith(self.drop)}
        return json.dumps(out, ensure_ascii=False)


def _entry(i, text, speaker="", listener="", ko=""):
    loc = Location(file="scene.json", kind="loose", fmt="json", ptr=f"p{i}",
                   speaker=speaker, listener=listener)
    e = Entry(id=f"e{i}", text=text, locations=[loc])
    if ko:
        e.translations["ko"] = ko
    return e


def test_request_carries_speakers_selected_sheet_and_previous_lines():
    story = [_entry(0, "ご飯よ", "母", "プレイヤー", ko="밥 먹어"),
             _entry(1, "今行く", "プレイヤー", "母", ko="지금 가"),
             _entry(2, "精力がない", "プレイヤー", "母"),
             _entry(3, "ちゃんと食べなさい", "母", "プレイヤー")]
    todo = [e for e in story if not e.translations]
    fake = _Fake()
    rep = T.translate_entries(todo, fake, src="ja", dst="ko", lang_col="ko",
                              characters=charsheet.parse(SHEET),
                              context_lines=2, pool=story)
    assert rep.done == 2 and rep.requests == 1
    prompt, req = fake.calls[0]
    assert "구어체로." in prompt                       # style 은 지시문에
    assert "精力" not in prompt                         # 용어집은 지시문에 없음
    assert req["glossary"] == {"精力": "정력"}
    assert set(req["characters"]) == {"mom", "player"}
    assert req["previous"] == [
        {"speaker": "母", "text": "ご飯よ", "ko": "밥 먹어"},
        {"speaker": "プレイヤー", "text": "今行く", "ko": "지금 가"}]
    assert [(l["id"], l["speaker"], l["listener"]) for l in req["lines"]] == [
        ("1", "プレイヤー", "母"), ("2", "母", "プレイヤー")]


def test_system_prompt_is_identical_across_batches():
    story = [_entry(i, f"台詞{i}", "母" if i % 2 else "プレイヤー") for i in range(45)]
    fake = _Fake()
    T.translate_entries(story, fake, src="ja", dst="ko", lang_col="ko",
                        characters=charsheet.parse(SHEET))
    assert len(fake.calls) == 3
    assert len({prompt for prompt, _ in fake.calls}) == 1


def test_missing_line_is_resent_alone():
    story = [_entry(i, f"台詞{i}") for i in range(5)]
    fake = _Fake(drop_first_call="台詞3")
    rep = T.translate_entries(story, fake, src="ja", dst="ko", lang_col="ko")
    assert rep.done == 5 and rep.failed == 0
    assert [len(req["lines"]) for _, req in fake.calls] == [5, 1]
    assert story[3].translations["ko"] == "번역:台詞3"


def test_no_sheet_sends_no_empty_sections():
    story = [_entry(0, "こんにちは")]
    fake = _Fake()
    T.translate_entries(story, fake, src="ja", dst="ko", lang_col="ko")
    assert set(fake.calls[0][1]) == {"lines"}

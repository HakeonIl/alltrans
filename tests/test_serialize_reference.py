# SPDX-License-Identifier: GPL-3.0-or-later
"""[SerializeReference] 읽기 · 적용 범위 · DLL 문구 분류.

실제 게임(ニートの俺は見ていることしか出来ない, Unity 6 Mono)에서 나온 사고를
게임 파일 없이 재현합니다.
"""

from __future__ import annotations

import pytest

pytest.importorskip("UnityPy")

from UnityPy.helpers.TypeTreeNode import TypeTreeNode

from gameloc import managed, typetree
from gameloc.apply import _scope_allows
from gameloc.model import Location


def _nodes(rows):
    return [TypeTreeNode(lv, ty, name, 0, 0, m_MetaFlag=0) for lv, ty, name in rows]


def _typed(ptr: str) -> Location:
    return Location(file="resources.assets", kind="asset", fmt="typetree",
                    ptr=ptr, path_id=1, asset="x")


# ── 생성기 출력 바로잡기 ──────────────────────────────────────────────

def test_list_of_strings_becomes_vector():
    nodes = typetree._fix_vectors(_nodes([
        (0, "MotherTrackingLocationMaster", "Base"),
        (1, "string", "NickName"),
        (2, "Array", "Array"), (3, "int", "size"), (3, "char", "data"),
        (1, "string", "_doing"),                    # 실제로는 List<string>
        (2, "Array", "Array"), (3, "int", "size"),
        (3, "string", "data"),
        (4, "Array", "Array"), (5, "int", "size"), (5, "char", "data"),
    ]))
    by_name = {n.m_Name: n.m_Type for n in nodes if n.m_Level == 1}
    assert by_name == {"NickName": "string", "_doing": "vector"}


def test_ref_nodes_drop_monobehaviour_head():
    nodes = typetree._strip_head(_nodes([
        (0, "TalkListenEntry", "Base"),
        (1, "PPtr<GameObject>", "m_GameObject"),
        (2, "int", "m_FileID"), (2, "SInt64", "m_PathID"),
        (1, "UInt8", "m_Enabled"),
        (1, "PPtr<MonoScript>", "m_Script"),
        (2, "int", "m_FileID"), (2, "SInt64", "m_PathID"),
        (1, "string", "m_Name"),
        (1, "string", "_text"),
        (2, "Array", "Array"), (3, "int", "size"), (3, "char", "data"),
    ]))
    assert [n.m_Name for n in nodes if n.m_Level == 1] == ["_text"]


# ── 적용 범위: 대사는 넣고, 게임이 이름으로 찾는 값은 막는다 ─────────────

@pytest.mark.parametrize("ptr", [
    "references.RefIds[3].data._text",              # TalkMaster 대사
    "references.RefIds[0].data._message",           # TimelineMaster 채팅
    "references.RefIds[5].data._entries[1].say",    # 선택지
    "references.RefIds[5].data._entries[1].response",
    "_fastEatDiscipline.chewLines[0]",
    "_smartphoneMealDistraction.lines[0]",
    "_doing[1]",
    "definition.commands[2].disabledReason",
])
def test_display_fields_are_applied(ptr):
    assert _scope_allows("visible_text", _typed(ptr))


@pytest.mark.parametrize("ptr", [
    "NickName",                                      # 토픽 이름 → 검은 화면
    "_speakerNameAliases[0]",                        # 화자 이름 대조용
    "_entries[2]._motherMemo",                       # 개발 메모
    "NextSceneName", "_gameSceneName",               # 씬 이름
    "nodes[3].pathFromPrefabRoot",                   # PSD 레이어 경로
    "references.RefIds[0].data.poseKeyOnBegin",
    "lines[0]",                                      # 흔한 이름은 경로로만
])
def test_identifier_fields_are_protected(ptr):
    assert not _scope_allows("visible_text", _typed(ptr))


def test_raw_talk_master_is_not_trusted():
    from gameloc.apply import _VISIBLE_RAW_CLASSES
    assert not "Apps.Talks.TalkMaster  (Assembly-CSharp)".startswith(
        _VISIBLE_RAW_CLASSES)


# ── DLL 문자열 분류 ────────────────────────────────────────────────

@pytest.mark.parametrize("text,type_name,method", [
    ("新しく始める", "Apps.Utilities.TitleEntry", "SetupTitle"),
    ("度胸 Lv.{0} に上がった！", "Apps.Touch.Courage.TouchCourageLevelUI",
     "PushGainNotification"),
    ("+{0} XP（異常を指摘）", "Apps.Meals.Mother.Skin.X", "TryNotifyHit"),
])
def test_screen_literals(text, type_name, method):
    assert managed.classify(text, type_name, method) == "screen"


@pytest.mark.parametrize("text,type_name,method,want", [
    ("[\\u30A1-\\u30FAー]{2,}", "Apps.Texts.JapaneseNounExtractor", ".cctor",
     "internal"),
    ("これ", "Apps.Texts.JapaneseNounExtractor", ".cctor", "review"),
    ("ハンドルネーム", "Apps.Plays.Jerks.JerkStreamDonorNameCsvParser",
     "IsHeaderLine", "review"),
    ("再生可能な Chat Step がありません。", "Apps.Scenario.X", "TryPlay", "review"),
    ("stateId が空です。", "Apps.Meals.X", "TryValidate", "review"),
    ("' を適用できません。", "Apps.Meals.X", "TryApplyPreset", "review"),
    ("再生済み", "Apps.Dialogues.X", "get_info", "review"),
])
def test_non_screen_literals(text, type_name, method, want):
    assert managed.classify(text, type_name, method) == want


# ── 엑셀을 거치며 틀어진 줄바꿈 되돌리기 ───────────────────────────────

@pytest.mark.parametrize("source,translated,want", [
    # 윈도우에서 \r\n 이 \r\r\n 으로 저장 → 엑셀이 \n\n 으로 읽음
    ("はい\r\n経験\n毎日\r\n直接", "예\n\n경험\n매일\n\n직접",
     "예\r\n경험\n매일\r\n직접"),
    # \r 이 빠져 \n 하나로 돌아옴
    ("a\r\nb\nc", "가\n나\n다", "가\r\n나\n다"),
    # 번역가가 줄 모양을 바꿨으면 그대로
    ("a\r\nb\nc", "가 나 다", "가 나 다"),
    ("a\nb", "가\n\n나", "가\n\n나"),
])
def test_restore_mixed_newlines(source, translated, want):
    from gameloc.sheet import restore_newlines
    assert restore_newlines(source, translated) == want


# ── 한글 자리(아틀라스) 넓히기 ──────────────────────────────────────

class _Obj:
    def __init__(self, tree):
        self.tree = tree

    def read_typetree(self):
        return self.tree

    def save_typetree(self, tree):
        self.tree = tree


def _donor(glyphs=(), tex_size=1):
    from types import SimpleNamespace
    by_id = {
        10: _Obj({"m_Name": "BIZUD SDF", "m_AtlasWidth": 1024, "m_AtlasHeight": 1024,
                  "m_IsMultiAtlasTexturesEnabled": 0, "m_GlyphTable": list(glyphs),
                  "m_UsedGlyphRects": [],
                  "m_FreeGlyphRects": [{"m_X": 0, "m_Y": 0, "m_Width": 1023,
                                        "m_Height": 1023}],
                  "m_CreationSettings": {"atlasWidth": 1024, "atlasHeight": 1024},
                  "m_AtlasTextures": [{"m_FileID": 0, "m_PathID": 11}],
                  "m_Material": {"m_FileID": 0, "m_PathID": 12}}),
        11: _Obj({"m_Width": tex_size, "m_Height": tex_size}),
        12: _Obj({"m_SavedProperties": {"m_Floats": [("_TextureWidth", 1024.0),
                                                     ("_TextureHeight", 1024.0)]}}),
    }
    return by_id, SimpleNamespace(patched=[], widened=[])


def test_widen_cleared_donor_atlas():
    from gameloc.font import WIDE_ATLAS, _widen_donor
    by_id, rep = _donor()
    assert _widen_donor(by_id, 10, rep, lambda m: None)
    t = by_id[10].tree
    assert t["m_AtlasWidth"] == t["m_AtlasHeight"] == WIDE_ATLAS
    assert t["m_IsMultiAtlasTexturesEnabled"] == 1
    assert t["m_FreeGlyphRects"][0]["m_Width"] == WIDE_ATLAS - 1
    assert dict(by_id[12].tree["m_SavedProperties"]["m_Floats"])["_TextureWidth"] == WIDE_ATLAS
    assert rep.widened == ["BIZUD SDF"]
    # 두 번째에는 할 일이 없습니다
    rep2 = type(rep)(patched=[], widened=[])
    assert not _widen_donor(by_id, 10, rep2, lambda m: None)


def test_filled_atlas_only_gets_multi_atlas():
    from gameloc.font import _widen_donor
    by_id, rep = _donor(glyphs=[{"m_Index": 1}], tex_size=1024)
    assert _widen_donor(by_id, 10, rep, lambda m: None)
    t = by_id[10].tree
    assert t["m_AtlasWidth"] == 1024           # 그려진 글자 위치를 지킵니다
    assert t["m_IsMultiAtlasTexturesEnabled"] == 1


# ── 화면 이름으로 쓰이는 NickName · 씬에 붙은 대화 그래프 ─────────────────

@pytest.mark.parametrize("cls,allowed", [
    ("Apps.Masters.StatusMaster", True),          # "{name}:{value}円" 의 이름
    ("Cinematic.Smartphone.MediaMaster", True),
    ("Apps.Talks.TalkMaster", False),             # 쓰임새가 분명하지 않음
    ("", False),                                  # 예전 목록 (클래스 모름)
])
def test_nickname_scope_by_class(cls, allowed):
    loc = Location(file="resources.assets", kind="asset", fmt="typetree",
                   ptr="NickName", path_id=1, asset="x", cls=cls)
    assert _scope_allows("visible_text", loc) is allowed


def test_location_cls_round_trip_is_optional():
    loc = Location(file="a", kind="asset", fmt="typetree", ptr="p")
    assert "cls" not in loc.to_dict()
    loc.cls = "Apps.Masters.StatusMaster"
    assert Location.from_dict(loc.to_dict()).cls == "Apps.Masters.StatusMaster"


def test_bound_graph_and_evening_choices():
    import json
    from gameloc import nodecanvas
    graph = {"nodes": [{
        "$type": "NodeCanvas.DialogueTrees.EveningMultipleChoiceNode",
        "availableChoices": [{"statement": {"_text": "寝る"}}],
    }]}
    tree = {"_boundGraphSerialization": json.dumps(graph)}
    assert nodecanvas.field_of(tree) == "_boundGraphSerialization"
    cells = nodecanvas.cells(tree)
    assert [c.text for c in cells] == ["寝る"]
    assert cells[0].ptr == "nodes[0].availableChoices[0].statement._text"

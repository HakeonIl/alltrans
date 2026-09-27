# SPDX-License-Identifier: GPL-3.0-or-later
"""누가 누구에게 하는 말인지 — 엔진별 화자 추출."""

from __future__ import annotations

import json

from gameloc import nodecanvas, speakers
from gameloc.engines import rpgmaker, renpy, tyrano
from gameloc.extract import _collapse
from gameloc.model import Location


# ── RPG Maker ──────────────────────────────────────────────────────

def test_rpgmaker_speaker_sources_in_priority_order():
    assert rpgmaker.speaker_of(["Actor1", 0, 0, 2, "ユリ"], "x") == "ユリ"
    assert rpgmaker.speaker_of(["", 0, 0, 2, ""], "\\n<ハロルド>こんにちは") == "ハロルド"
    assert rpgmaker.speaker_of(["", 0], "【ユリ】\nおはよう") == "ユリ"
    assert rpgmaker.speaker_of(None, "ユリ「おはよう」") == "ユリ"
    assert rpgmaker.speaker_of(["Actor1", 3, 0, 2], "今日は") == "얼굴:Actor1"
    assert rpgmaker.speaker_of(["", 0], "今日はいい天気") == ""


def test_rpgmaker_message_gets_speaker_from_show_text():
    cmds = [
        {"code": 101, "parameters": ["Actor1", 0, 0, 2, "ユリ"]},
        {"code": 401, "parameters": ["おはよう。"]},
        {"code": 401, "parameters": ["今日もいい天気。"]},
        {"code": 101, "parameters": ["", 0, 0, 2, ""]},
        {"code": 401, "parameters": ["風が吹いた。"]},
    ]
    rows = rpgmaker._commands(cmds, "data/Map001.json", ["events", 1], "")
    assert [(t, l.speaker) for t, l in rows] == [
        ("おはよう。\n今日もいい天気。", "ユリ"), ("風が吹いた。", "")]


# ── TyranoScript · Ren'Py ─────────────────────────────────────────

def test_tyrano_name_line_carries_to_following_dialogue():
    body = "#ユリ:smile\nおはよう。[l][r]今日はいい天気だね。[p]\n#\n風が吹いた。[p]"
    who = tyrano.speakers(body)
    got = {t: who.get(p, "") for p, k, t in tyrano.iter_texts(body) if k == "대사"}
    assert got == {"おはよう。": "ユリ", "今日はいい天気だね。": "ユリ", "風が吹いた。": ""}


def test_renpy_say_speaker_uses_character_display_name():
    src = ('define e = Character("Eileen", color="#c8ffc8")\n'
           'define y = Character(_("ユリ"))\n'
           'label start:\n'
           '    e "こんにちは"\n'
           '    "ナレーション"\n'
           '    y "おはよう" (what_color="#f00")\n')
    who: dict[int, str] = {}
    pairs = renpy.rpy_texts(src, who)
    names = renpy.character_names(src)
    says = [(t, names.get(who.get(i, ""), who.get(i, "")))
            for i, (k, t) in enumerate(pairs) if k == "say"]
    assert says == [("こんにちは", "Eileen"), ("ナレーション", ""), ("おはよう", "ユリ")]


# ── Unity: NodeCanvas 배우 → 캐릭터 이름, 듣는 사람 추정 ────────────────

class _Obj:
    def __init__(self, tree):
        self._tree = tree

    def read_typetree(self):
        return self._tree


def test_nodecanvas_actor_names_and_listener():
    graph = {
        "nodes": [
            {"$type": "NodeCanvas.DialogueTrees.StatementNode",
             "_actorName": "Mom", "statement": {"_text": "ちゃんと噛みなさい"}},
            {"$type": "NodeCanvas.DialogueTrees.StatementNode",
             "_actorName": "Player", "statement": {"_text": "うん"}},
            {"$type": "NodeCanvas.DialogueTrees.MultipleChoiceNode",
             "availableChoices": [{"statement": {"_text": "はい"}}]},
        ],
        "derivedData": {"actorParameters": [
            {"_keyName": "Player", "_id": "p", "_actorObject": 1},
            {"_keyName": "Mom", "_id": "m", "_actorObject": 2}]},
    }
    tree = {"_serializedGraph": json.dumps(graph),
            "_objectReferences": [{"m_PathID": 0}, {"m_PathID": 10},
                                  {"m_PathID": 11}]}
    objects = {10: _Obj({"NickName": "プレイヤー"}), 11: _Obj({"NickName": "母"})}
    cells = nodecanvas.cells(tree, {}, objects)
    assert [(c.speaker, c.listener) for c in cells] == [
        ("母", "プレイヤー"), ("プレイヤー", "母"), ("プレイヤー", "母")]


# ── Unity: 참조 데이터 · 번역 DB 의 화자 풀이 ──────────────────────────

def test_book_resolves_sender_ids_and_localized_strings():
    book = speakers.Book()
    book.learn({"m_Name": "J0kK", "NickName": "母"}, 5)
    owner = {"references": {"RefIds": [
        {"type": {"ns": "Cinematic.TweetApps", "class": "TweetPlaybackMessageEntry"},
         "data": {"_author": {"_value": "J0kK"},
                  "_message": {"_stringId": "S1"}}},
        {"type": {"ns": "Apps.Talks", "class": "TalkListenEntry"},
         "data": {"_text": "そういえば"}},
        {"type": {"ns": "Apps.Timeline", "class": "ChatMessageLine"},
         "data": {"_sender": {"m_FileID": 0, "m_PathID": 5}, "_message": "おー"}},
    ]}}
    book.learn(owner, 6)
    db = {"_records": [{"stringId": "S1", "text": "いいの撮れたわ"}]}

    who = [book.mark(owner, "references.RefIds[1].data._text"),
           book.mark(owner, "references.RefIds[2].data._message"),
           book.mark(db, "_records[0].text")]
    assert [(book.resolve(a), book.resolve(b)) for a, b in who] == [
        ("母", "プレイヤー"), ("母", ""), ("母", "")]
    assert book.resolve("@id:unknown") == ""


# ── 같은 문장이라도 화자가 다르면 따로, 모르면 예전 ID 그대로 ─────────────

def _loc(speaker="", kind="loose"):
    return Location(file="a", kind=kind, fmt="json", ptr="p", speaker=speaker)


def test_collapse_splits_by_speaker_but_keeps_old_ids():
    from gameloc.model import make_id
    entries = _collapse([("うん", _loc("母")), ("うん", _loc("プレイヤー")),
                         ("うん", _loc()), ("うん", _loc())], dedup=True)
    assert len(entries) == 3
    plain = [e for e in entries if not e.speaker][0]
    assert plain.id == make_id("うん") and plain.count == 2


def test_collapse_does_not_split_renpy():
    entries = _collapse([("うん", _loc("A", "renpy")), ("うん", _loc("B", "renpy"))],
                        dedup=True)
    assert len(entries) == 1

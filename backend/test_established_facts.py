"""Confirmed-event ledger. Temporary DB only; historical data/*.db unread."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.context_pack import ContextPackService
from backend.established_facts import (CHAPTER_SUMMARY_CAP, ESTABLISHED_FACTS_REASON,
    ESTABLISHED_FACTS_RULE, WORLD_STATE_KEYS, WORLD_STATE_REASON, WORLD_STATE_RULE,
    build_established_facts, build_world_state, established_facts_instruction,
    established_facts_snapshot, is_irreversible_fact, is_scene_absence,
    load_established_facts, present_scene_state, split_accepted_scene_state,
    validate_established_facts, validate_world_state, world_state_instruction)
from backend.progression import progression_baseline_from_state
from backend.siliconflow import (MEMORY_REFUSAL_RETRY_PACK_KEYS, first_draft_writing_instruction,
    planning_progression_instruction, reviewer_plot_instruction, reviewer_style_instruction,
    reviewer_world_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


def expect_empty(snapshot):
    assert snapshot["rule"] == ESTABLISHED_FACTS_RULE
    assert snapshot["facts"] == []
    assert snapshot.get("chapter_summary", "") == ""


# 1. No prior scene → empty ledger.
expect_empty(established_facts_snapshot())
expect_empty(build_established_facts([]))
expect_empty(load_established_facts(None, book_id="b", before_scene_number=1))


# 2 / 3 / 4. Order, skip dicts, keep earliest duplicate text.
scenes = [
    {"scene_id": "s1", "scene_number": 1, "events": ["先到岸边", {"dirty": True}]},
    {"scene_id": "s2", "scene_number": 2, "events": ["进入保存层", ""]},
    {"scene_id": "s3", "scene_number": 3, "events": ["先到岸边", "看见编号"]},
]
fourth = build_established_facts(scenes)
assert [item["text"] for item in fourth["facts"]] == ["先到岸边", "进入保存层", "看见编号"]
assert [item["scene_number"] for item in fourth["facts"]] == [1, 2, 3]
assert fourth["facts"][0]["scene_id"] == "s1"
assert all(isinstance(item["text"], str) for item in fourth["facts"])
assert fourth["chapter_summary"] == ""
assert all(set(item) == {"scene_id", "scene_number", "text", "kind"} for item in fourth["facts"])


# 6. Over 120 keep earliest 30 + latest 90.
overflow = build_established_facts([{
    "scene_id": "s1", "scene_number": 1,
    "events": [f"事件{index}" for index in range(1, 131)],
}])
assert len(overflow["facts"]) == 120
assert [item["text"] for item in overflow["facts"][:30]] == [f"事件{index}" for index in range(1, 31)]
assert [item["text"] for item in overflow["facts"][-90:]] == [f"事件{index}" for index in range(41, 131)]
assert all(item["kind"] == "event" for item in overflow["facts"])
assert "事件31" not in [item["text"] for item in overflow["facts"]]
assert "事件40" not in [item["text"] for item in overflow["facts"]]
assert "事件31" in overflow["chapter_summary"]
assert "事件40" in overflow["chapter_summary"]
assert "事件1" not in overflow["chapter_summary"]
assert "事件130" not in overflow["chapter_summary"]
assert "事件41" not in overflow["chapter_summary"]
assert len(overflow["chapter_summary"]) <= CHAPTER_SUMMARY_CAP

pinned_events = [f"事件{index}" for index in range(1, 131)]
pinned_events[49] = "进入保存层"
pinned = build_established_facts([{
    "scene_id": "s1", "scene_number": 1, "events": pinned_events,
}])
pinned_texts = [item["text"] for item in pinned["facts"]]
assert "进入保存层" in pinned_texts
assert next(item["kind"] for item in pinned["facts"] if item["text"] == "进入保存层") == "canon"
assert len(pinned["facts"]) > 120
assert pinned_texts.index("进入保存层") > 0
assert "事件31" not in pinned_texts
assert "进入保存层" not in [item["text"] for item in overflow["facts"]]
assert "进入保存层" not in pinned["chapter_summary"]

long_a = "甲" * 800
long_b = "乙" * 800
long_events = [f"流水{index}" for index in range(1, 123)]
long_events[30] = long_a
long_events[31] = long_b
long_pack = build_established_facts([{
    "scene_id": "s1", "scene_number": 1, "chapter_number": 3, "events": long_events,
}])
long_kept = [item["text"] for item in long_pack["facts"]]
assert long_a not in long_kept and long_b not in long_kept
assert "第3章" in long_pack["chapter_summary"]
assert "甲" in long_pack["chapter_summary"] and "乙" in long_pack["chapter_summary"]
assert long_pack["chapter_summary"].startswith("第3章：")
assert " / " not in long_pack["chapter_summary"] or long_pack["chapter_summary"].count("第") == 1
assert len(long_pack["chapter_summary"]) <= CHAPTER_SUMMARY_CAP
for text in long_kept:
    assert text not in long_pack["chapter_summary"]


def chapter_part(summary, number):
    prefix = f"第{number}章："
    for part in summary.split(" / "):
        if part.startswith(prefix):
            return part
    raise AssertionError(prefix)


twenty_scenes = [{
    "scene_id": "early", "scene_number": 1, "chapter_number": 99,
    "events": [f"前{index}" for index in range(1, 31)],
}]
for number in range(1, 21):
    twenty_scenes.append({
        "scene_id": f"mid{number}", "scene_number": 1 + number, "chapter_number": number,
        "events": [f"章标记{number}档案室"],
    })
twenty_scenes.append({
    "scene_id": "tail", "scene_number": 22, "chapter_number": 99,
    "events": [f"后{index}" for index in range(1, 91)],
})
twenty = build_established_facts(twenty_scenes)
assert all(f"第{number}章" in twenty["chapter_summary"] for number in range(1, 21))
assert "章标记1" in chapter_part(twenty["chapter_summary"], 1)
assert len(twenty["chapter_summary"]) <= CHAPTER_SUMMARY_CAP

eighty_scenes = [{
    "scene_id": "early", "scene_number": 1, "chapter_number": 99,
    "events": [f"前{index}" for index in range(1, 31)],
}]
for number in range(1, 81):
    eighty_scenes.append({
        "scene_id": f"mid{number}", "scene_number": 1 + number, "chapter_number": number,
        "events": [f"章标{number}" + "x" * 190],
    })
eighty_scenes.append({
    "scene_id": "tail", "scene_number": 82, "chapter_number": 99,
    "events": [f"后{index}" for index in range(1, 91)],
})
eighty = build_established_facts(eighty_scenes)
assert all(f"第{number}章" in eighty["chapter_summary"] for number in range(1, 81))
assert "章标1" in chapter_part(eighty["chapter_summary"], 1)
assert len(eighty["chapter_summary"]) <= CHAPTER_SUMMARY_CAP
assert len(eighty["chapter_summary"]) <= 7200

assert is_irreversible_fact("林照进入档案室并说明来意") is True
assert is_irreversible_fact("守夜人领她进入保存层") is True
assert is_irreversible_fact("林照在涨潮前登上记忆厅") is True
assert is_irreversible_fact("") is False
assert is_irreversible_fact({"dirty": True}) is False
assert is_irreversible_fact("本场未进入") is False
assert is_irreversible_fact("均未进入") is False
assert is_irreversible_fact("她没有跨过门槛") is False
assert is_irreversible_fact("林照正式提出进入字库") is False
assert is_irreversible_fact("提出以核对编号为名进入未成名层") is False
assert is_irreversible_fact("表末添记未开匣") is False
assert is_irreversible_fact("不取匣不开匣") is False
assert is_irreversible_fact("他没有见过匣子上架") is False
assert is_irreversible_fact("送匣人沿通路而来，脚步很轻") is False
assert is_irreversible_fact("昨夜进入保存层，今日未进入字库") is True


instruction = established_facts_instruction()
assert "established_facts" in instruction
assert "context_pack.established_facts" in instruction
assert "progression_baseline" in instruction
assert "kind=canon" in instruction
assert "chapter_summary" in instruction
assert "context_pack.chapter_summary" in instruction
assert "每章" in instruction
assert "林照" not in instruction
assert "灯塔" not in instruction
assert "档案室" not in instruction
assert "established_facts" not in MEMORY_REFUSAL_RETRY_PACK_KEYS

world_instruction = world_state_instruction()
assert "world_state" in world_instruction
assert "此刻" in world_instruction
assert "offstage" in world_instruction
assert "clocks" in world_instruction
assert "measures" in world_instruction
assert "昨日" in world_instruction or "昨天" in world_instruction
assert "林照" not in world_instruction
assert "灯塔" not in world_instruction
assert "档案室" not in world_instruction

assert "established_facts" in first_draft_writing_instruction()
assert "established_facts" in planning_progression_instruction()
assert "world_state" in first_draft_writing_instruction()
assert "world_state" in planning_progression_instruction()
assert "此刻" in first_draft_writing_instruction()
assert "此刻" in planning_progression_instruction()
for reviewer in (
    reviewer_world_instruction(),
    reviewer_plot_instruction(),
    reviewer_style_instruction(),
):
    assert "established_facts" not in reviewer
    assert "validate_established_facts" not in reviewer
    assert "established_facts_conflict" not in reviewer
    assert "established_negation" not in reviewer
    assert "context_pack.chapter_summary" not in reviewer
    assert "被账本裁掉" not in reviewer
    assert "world_state" not in reviewer
    assert "context_pack.world_state" not in reviewer
    assert "validate_world_state" not in reviewer
    assert "world_state_conflict" not in reviewer


LEDGER = established_facts_snapshot(facts=[
    {"scene_id": "s1", "scene_number": 1, "text": "先到岸边"},
])
SAFE = "林照的鞋底陷进湿沙半寸，她停住，没有继续往岸上走。"


def expect_gate(text, established_facts, *, ok, found=None):
    result = validate_established_facts(text, established_facts)
    if ok:
        assert result["status"] == "passed", result
        assert result["reason"] is None
        assert result["conflicts"] == []
    else:
        assert result["status"] == "failed", result
        assert result["reason"] == ESTABLISHED_FACTS_REASON
        assert result["rule"] == ESTABLISHED_FACTS_RULE
        assert len(result["conflicts"]) == 1
        conflict = result["conflicts"][0]
        assert conflict["kind"] == "established_negation"
        assert conflict["found"]
        assert conflict["excerpt"]
        if found:
            assert conflict["found"] == found
    return result


expect_gate("一层也没进", None, ok=True)
expect_gate("一层也没进", established_facts_snapshot(), ok=True)
expect_gate("从未进入", {"facts": []}, ok=True)

for phrase in ("一层也没进", "从未进入", "均未进入"):
    expect_gate(phrase, LEDGER, ok=False, found=phrase)
expect_gate("守夜人仍未现身", LEDGER, ok=False, found="仍未现身")

expect_gate("本场未进入", LEDGER, ok=True)
expect_gate("本场三层均未进入", LEDGER, ok=True)
expect_gate("今夜仍未现身", LEDGER, ok=True)
expect_gate("她没有跨过门槛", LEDGER, ok=True)
expect_gate("她未跨门槛", LEDGER, ok=True)
expect_gate("她仍未进入", LEDGER, ok=True)
expect_gate("她未进入", LEDGER, ok=True)

expect_gate(SAFE, LEDGER, ok=True)
expect_gate("林照的手停在结上。红线下方的双结是妹妹林澜留下的。", LEDGER, ok=True)
expect_gate("林照站起来，膝盖有些僵。她看着守夜人把晶片放回带编号的浅格。", LEDGER, ok=True)


empty_world = build_world_state()
assert set(empty_world) == set(WORLD_STATE_KEYS)
assert empty_world["location"] == ""
assert empty_world["time_context"] == ""
assert empty_world["day_relation"] == ""
assert empty_world["present"] == []
assert empty_world["offstage"] == []
assert empty_world["clocks"] == []
assert empty_world["measures"] == []
assert build_world_state(None) == empty_world
assert build_world_state({}) == empty_world
assert build_world_state("脏") == empty_world

split_world = build_world_state({
    "location": "岸边石阶",
    "time_context": "潮水未退，巳时未到",
    "characters": ["她站在石阶上", "守夜人未登场", "货场的人已留在岸上，不随行", "跟着上来的人"],
})
assert split_world["location"] == "岸边石阶"
assert split_world["time_context"] == "潮水未退，巳时未到"
assert split_world["present"] == ["她站在石阶上", "跟着上来的人"]
assert split_world["offstage"] == ["守夜人未登场", "货场的人已留在岸上，不随行"]
assert "巳时未到" in split_world["clocks"]

late = build_world_state({
    "characters": ["林晚：不在场，其记忆仍归档", "已离开渡口", "还在门口的人"],
})
assert "林晚：不在场，其记忆仍归档" in late["offstage"]
assert "已离开渡口" in late["offstage"]
assert "林晚：不在场，其记忆仍归档" not in late["present"]
assert "还在门口的人" in late["present"]

assert build_world_state({
    "characters": ["在场的人", {"dirty": True}, "同伴未到场", 3, "另一人未上场"],
})["present"] == ["在场的人"]
assert build_world_state({
    "characters": ["在场的人", {"dirty": True}, "同伴未到场", 3, "另一人未上场"],
})["offstage"] == ["同伴未到场", "另一人未上场"]
assert {"dirty": True} not in build_world_state({
    "characters": ["在场的人", {"dirty": True}, "同伴未到场"],
})["present"]
assert {"dirty": True} not in build_world_state({
    "characters": ["在场的人", {"dirty": True}, "同伴未到场"],
})["offstage"]
assert build_world_state({"location": {"name": "门口"}, "time_context": ["夜"]})["location"] == ""
assert build_world_state({"location": {"name": "门口"}, "time_context": ["夜"]})["time_context"] == ""

measured = build_world_state({
    "events": ["绳头露出一拃半", "可见长约一指多一点"],
    "characters": ["手里一拃的人"],
})
assert "一拃半" in measured["measures"]
assert "一指多一点" in measured["measures"]
assert "一拃" not in measured["measures"]
assert measured["measures"] == ["一拃半", "一指多一点"]

assert build_world_state({"time_context": "与上一场同日，上午光斜"})["day_relation"] == "same_day"
assert build_world_state({"time_context": "与上一场相隔一日的同一时段"})["day_relation"] == "next_day"
assert build_world_state({"time_context": "涨潮之夜"})["day_relation"] == ""

clocks = build_world_state({"time_context": "辰时三刻后，巳时未到"})["clocks"]
assert "辰时三刻" in clocks
assert "巳时未到" in clocks


def expect_world(text, world_state, *, ok, kind=None):
    result = validate_world_state(text, world_state)
    if ok:
        assert result["status"] == "passed", result
        assert result["reason"] is None
        assert result["conflicts"] == []
    else:
        assert result["status"] == "failed", result
        assert result["reason"] == WORLD_STATE_REASON
        assert result["rule"] == WORLD_STATE_RULE
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["kind"] == kind
        assert result["conflicts"][0]["found"]
        assert result["conflicts"][0]["excerpt"]
    return result


expect_world("巳时三刻到了", None, ok=True)
expect_world("昨天新露出来", {}, ok=True)
expect_world("巳时三刻到了", build_world_state(), ok=True)

clock_state = {"clocks": ["巳时未到"], "measures": [], "offstage": [], "day_relation": ""}
expect_world("巳时三刻到了", clock_state, ok=False, kind="clock_rewrite")
expect_world("午时她站到门口", clock_state, ok=True)
expect_world("仍是巳时未到", clock_state, ok=True)

measure_state = {"clocks": [], "measures": ["一拃半"], "offstage": [], "day_relation": ""}
expect_world("和昨日记住的长度一样，一指多一点", measure_state, ok=False, kind="measure_rewrite")
expect_world("可见长约一指多一点", measure_state, ok=True)
expect_world("露出一拃半", measure_state, ok=True)

same_day = {"clocks": [], "measures": [], "offstage": [], "day_relation": "same_day"}
expect_world("昨天新露出来的那条边", same_day, ok=False, kind="same_day_yesterday")
expect_world("踩着昨天留下的旧印", same_day, ok=True)
expect_world("昨天新露出来", {"clocks": [], "measures": [], "offstage": [], "day_relation": "next_day"}, ok=True)

offstage_state = {"clocks": [], "measures": [], "offstage": ["林晚：不在场，其记忆仍归档"], "day_relation": ""}
expect_world("林晚跟着来了", offstage_state, ok=False, kind="offstage_arrival")
expect_world("林晚的铜牌仍在原格", offstage_state, ok=True)


DIRTY_EVENTS = [
    "进入保存层", "均未进入", "本场未进入", "一层也没进", "她没有跨过门槛",
    "守夜人仍未现身", "门槛未跨", "她仍未进入", "先到岸边",
]
DIRTY_ABSENCES = [
    "均未进入", "本场未进入", "一层也没进", "她没有跨过门槛",
    "守夜人仍未现身", "门槛未跨", "她仍未进入",
]
DIRTY_STATE = {
    "characters": ["林照"],
    "events": list(DIRTY_EVENTS),
    "relationship_changes": [],
    "unresolved_threads": [],
    "location": "门口",
    "time_context": "夜",
}
split = split_accepted_scene_state(DIRTY_STATE)
assert split["present"]["events"] == ["进入保存层", "先到岸边"]
assert split["absences"] == DIRTY_ABSENCES
assert "present" not in DIRTY_STATE and "absences" not in DIRTY_STATE

CLEAN_STATE = {
    "characters": ["林照"],
    "events": ["先到岸边", "进入保存层"],
    "relationship_changes": [],
    "unresolved_threads": [],
    "location": "门口",
    "time_context": "夜",
}
assert present_scene_state(CLEAN_STATE) == CLEAN_STATE
assert progression_baseline_from_state(CLEAN_STATE) == CLEAN_STATE

assert present_scene_state({"location": "均未进入"})["location"] == ""
assert present_scene_state({"location": "门口"})["location"] == "门口"
assert present_scene_state({"events": ["进入保存层", {"dirty": True}, "均未进入"]})["events"] == [
    "进入保存层", {"dirty": True},
]
assert is_scene_absence({"dirty": True}) is False
assert is_scene_absence("她未进入") is False


def open_book(directory):
    path = Path(directory) / "facts.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    return db


def add_scene(db, number):
    scene = f"s{number}"
    db.execute("insert into scenes values (?,?,?,?,?,?,?,?)",
               (scene, "b", "c", number, None, None, "2026", "2026"))
    return scene


def add_report(db, number, events, *, status="passed", attempt=1):
    scene = f"s{number}"
    chapter = "c"
    draft = f"{scene}_d{attempt}"
    db.execute(
        "insert into prose_drafts values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (draft, "b", chapter, scene, attempt, attempt, 1, 1, "潮", 1, 1250, 1, "{}",
         "passed", "h", "hc", 1, 1, "2026"),
    )
    db.execute(
        "insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{scene}_r{attempt}", "b", chapter, scene, draft, "h", attempt, "completed", "[]",
         0, 0, 0, 0, 0, "complete",
         json.dumps({"events": events}, ensure_ascii=False),
         status, "2026"),
    )


with tempfile.TemporaryDirectory() as directory:
    db = open_book(directory)
    for number in range(1, 5):
        add_scene(db, number)
    add_report(db, 1, ["先到岸边", {"dirty": 1}])
    add_report(db, 2, ["进入保存层"])
    add_report(db, 3, ["先到岸边", "看见编号"])
    add_report(db, 3, ["失败不入账"], status="failed", attempt=2)
    db.commit()
    empty = load_established_facts(db, book_id="b", before_scene_number=1)
    expect_empty(empty)
    loaded = load_established_facts(db, book_id="b", before_scene_number=4)
    assert [item["text"] for item in loaded["facts"]] == ["先到岸边", "进入保存层", "看见编号"]
    assert [item["scene_number"] for item in loaded["facts"]] == [1, 2, 3]
    db.close()


with tempfile.TemporaryDirectory() as directory:
    db = open_book(directory)
    add_scene(db, 1)
    add_scene(db, 2)
    add_report(db, 1, list(DIRTY_EVENTS))
    db.commit()
    loaded = load_established_facts(db, book_id="b", before_scene_number=2)
    assert [item["text"] for item in loaded["facts"]] == ["进入保存层", "先到岸边"]
    assert all(item["text"] not in DIRTY_ABSENCES for item in loaded["facts"])
    stored = json.loads(db.execute(
        "select accepted_scene_state_json from quality_reports where scene_id=?", ("s1",)).fetchone()[0])
    assert stored["events"] == DIRTY_EVENTS
    assert "present" not in stored and "absences" not in stored
    db.close()


passed = established_facts_snapshot(facts=[
    {"scene_id": "s1", "scene_number": 1, "text": "先到岸边"},
])
with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "pack.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',4,null,null,'2026','2026')")
    db.commit()
    previous = {"events": ["上场此刻"], "location": "门口"}
    pack = ContextPackService(db).assemble(
        pack_id="p", book_id="b", chapter_id="c", scene_id="s", version=1,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state=previous, established_facts=passed,
    )
    assert pack["established_facts"] == {
        "canon_version": passed["canon_version"],
        "rule": passed["rule"],
        "facts": passed["facts"],
    }
    assert "chapter_summary" not in pack["established_facts"]
    assert "world_state" not in pack["established_facts"]
    assert pack["chapter_summary"] == ""
    assert pack["established_facts"] is not pack["previous_scene_state"]
    assert pack["previous_scene_state"] == previous
    assert pack["world_state"] == build_world_state(previous)
    assert pack["world_state"] is not pack["previous_scene_state"]
    db.close()


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": ["查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                                      "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索"}],
    }}


def prose(text):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role):
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": "潮", "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": "潮"},
    }}


class FactsDraftAdapter:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose(self.texts.pop(0) if self.texts else SAFE + "潮" * 1000)
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
                "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({
            "review_world": "world_consistency", "review_plot": "character_plot",
            "review_style": "language_experience",
        }[role])


def confirm_scene1(db, book, events=None, *, location="灯塔", time_context="夜", characters=None):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose("潮" * 1000), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": list(characters or ["林照"]), "location": location, "time_context": time_context,
                    "events": list(events or ["调查"]), "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = "一层也没进" + "潮" * 1000
passing = SAFE + "潮" * 1000
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "facts-fail.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book)
    db.close()
    adapter = FactsDraftAdapter([failing, passing])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene.get("block_reason") != ESTABLISHED_FACTS_REASON
    assert scene["final_status"] == "waiting_confirmation"
    roles = [call["task_type"] for call in adapter.calls]
    assert roles.count("planning") == 1
    assert roles.count("writing") == 2
    assert any(role.startswith("review_") for role in roles)
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    assert planning["input"]["context_pack"]["established_facts"]["facts"]
    db = sqlite3.connect(path)
    reasons = [row[0] for row in db.execute(
        "select reason from task_events where task_id=? and event_type='rework_requested' order by created_at",
        (book + "_scene_2_task",))]
    assert ESTABLISHED_FACTS_REASON in reasons
    assert db.execute(
        "select current_node,content_attempt_in_plan from task_states where scene_id=?",
        (book + "_scene_2",)).fetchone()[1] == 1
    queued = db.execute("select count(*) from exception_queue where task_id=?", (book + "_scene_2_task",)).fetchone()[0]
    assert queued == 0
    db.close()


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "facts-split.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book, events=["均未进入", "进入保存层"])
    stored = json.loads(db.execute(
        "select accepted_scene_state_json from quality_reports where scene_id=?",
        (book + "_scene_1",)).fetchone()[0])
    assert stored["events"] == ["均未进入", "进入保存层"]
    assert "present" not in stored and "absences" not in stored
    db.close()
    adapter = FactsDraftAdapter([SAFE + "潮" * 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    previous = planning["input"]["context_pack"]["previous_scene_state"]
    facts = [item["text"] for item in planning["input"]["context_pack"]["established_facts"]["facts"]]
    baseline = planning["input"]["progression_baseline"]
    assert "均未进入" not in previous.get("events", [])
    assert "进入保存层" in previous.get("events", [])
    assert "均未进入" not in facts
    assert "进入保存层" in facts
    assert "均未进入" not in baseline.get("events", [])
    assert "进入保存层" in baseline.get("events", [])


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "facts-summary.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book, events=[f"事件{index}" for index in range(1, 131)])
    db.close()
    adapter = FactsDraftAdapter([SAFE + "潮" * 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    pack = planning["input"]["context_pack"]
    assert "事件31" in pack["chapter_summary"]
    assert "事件31" not in [item["text"] for item in pack["established_facts"]["facts"]]
    assert "chapter_summary" not in pack["established_facts"]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "world-state.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(
        db, book, events=["露出一拃半"],
        location="岸边石阶", time_context="辰时三刻后，巳时未到",
        characters=["她站在石阶上", "守夜人未登场"],
    )
    db.close()
    adapter = FactsDraftAdapter([SAFE + "潮" * 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    pack = planning["input"]["context_pack"]
    assert pack["previous_scene_state"]["location"] == "岸边石阶"
    assert "巳时未到" in pack["previous_scene_state"]["time_context"]
    assert pack["world_state"] == build_world_state(pack["previous_scene_state"])
    assert pack["world_state"]["location"] == "岸边石阶"
    assert "巳时未到" in pack["world_state"]["time_context"]
    assert "巳时未到" in pack["world_state"]["clocks"]
    assert "一拃半" in pack["world_state"]["measures"]
    assert pack["world_state"]["offstage"]
    assert "她站在石阶上" in pack["world_state"]["present"]
    assert "守夜人未登场" in pack["world_state"]["offstage"]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "world-gate.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book, events=["先到岸边"], location="岸边石阶", time_context="巳时未到")
    db.close()
    adapter = FactsDraftAdapter(["巳时三刻到了" + "潮" * 1000, SAFE + "潮" * 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene.get("block_reason") != WORLD_STATE_REASON
    assert scene["final_status"] == "waiting_confirmation"
    roles = [call["task_type"] for call in adapter.calls]
    assert roles.count("planning") == 1
    assert roles.count("writing") == 2
    assert any(role.startswith("review_") for role in roles)
    db = sqlite3.connect(path)
    reasons = [row[0] for row in db.execute(
        "select reason from task_events where task_id=? and event_type='rework_requested' order by created_at",
        (book + "_scene_2_task",))]
    assert WORLD_STATE_REASON in reasons
    assert db.execute(
        "select current_node,content_attempt_in_plan from task_states where scene_id=?",
        (book + "_scene_2",)).fetchone()[1] == 1
    queued = db.execute("select count(*) from exception_queue where task_id=?", (book + "_scene_2_task",)).fetchone()[0]
    assert queued == 0
    db.close()


print("established facts ok")

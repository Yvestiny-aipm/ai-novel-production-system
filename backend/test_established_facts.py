"""Confirmed-event ledger. Temporary DB only; historical data/*.db unread."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import reviewer_result, scene_plan, words

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
    {"scene_id": "s1", "scene_number": 1, "events": ["reached the shore first", {"dirty": True}]},
    {"scene_id": "s2", "scene_number": 2, "events": ["entered the Preservation tier", ""]},
    {"scene_id": "s3", "scene_number": 3, "events": ["reached the shore first", "saw the number"]},
]
fourth = build_established_facts(scenes)
assert [item["text"] for item in fourth["facts"]] == ["reached the shore first", "entered the Preservation tier", "saw the number"]
assert [item["scene_number"] for item in fourth["facts"]] == [1, 2, 3]
assert fourth["facts"][0]["scene_id"] == "s1"
assert all(isinstance(item["text"], str) for item in fourth["facts"])
assert fourth["chapter_summary"] == ""
assert all(set(item) == {"scene_id", "scene_number", "text", "kind"} for item in fourth["facts"])


# 6. Over 120 keep earliest 30 + latest 90.
overflow = build_established_facts([{
    "scene_id": "s1", "scene_number": 1,
    "events": [f"event {index}" for index in range(1, 131)],
}])
assert len(overflow["facts"]) == 120
assert [item["text"] for item in overflow["facts"][:30]] == [f"event {index}" for index in range(1, 31)]
assert [item["text"] for item in overflow["facts"][-90:]] == [f"event {index}" for index in range(41, 131)]
assert all(item["kind"] == "event" for item in overflow["facts"])
assert "event 31" not in [item["text"] for item in overflow["facts"]]
assert "event 40" not in [item["text"] for item in overflow["facts"]]
assert "event 31" in overflow["chapter_summary"]
assert "event 40" in overflow["chapter_summary"]
assert "event 1" not in overflow["chapter_summary"]
assert "event 130" not in overflow["chapter_summary"]
assert "event 41" not in overflow["chapter_summary"]
assert len(overflow["chapter_summary"]) <= CHAPTER_SUMMARY_CAP

pinned_events = [f"event {index}" for index in range(1, 131)]
pinned_events[49] = "entered the Preservation tier"
pinned = build_established_facts([{
    "scene_id": "s1", "scene_number": 1, "events": pinned_events,
}])
pinned_texts = [item["text"] for item in pinned["facts"]]
assert "entered the Preservation tier" in pinned_texts
assert next(item["kind"] for item in pinned["facts"] if item["text"] == "entered the Preservation tier") == "canon"
assert len(pinned["facts"]) > 120
assert pinned_texts.index("entered the Preservation tier") > 0
assert "event 31" not in pinned_texts
assert "entered the Preservation tier" not in [item["text"] for item in overflow["facts"]]
assert "entered the Preservation tier" not in pinned["chapter_summary"]

long_a = "A" * 800
long_b = "B" * 800
long_events = [f"stream {index}" for index in range(1, 123)]
long_events[30] = long_a
long_events[31] = long_b
long_pack = build_established_facts([{
    "scene_id": "s1", "scene_number": 1, "chapter_number": 3, "events": long_events,
}])
long_kept = [item["text"] for item in long_pack["facts"]]
assert long_a not in long_kept and long_b not in long_kept
assert "Chapter 3" in long_pack["chapter_summary"]
assert "A" in long_pack["chapter_summary"] and "B" in long_pack["chapter_summary"]
assert long_pack["chapter_summary"].startswith("Chapter 3: ")
assert " / " not in long_pack["chapter_summary"] or long_pack["chapter_summary"].count("Chapter") == 1
assert len(long_pack["chapter_summary"]) <= CHAPTER_SUMMARY_CAP
for text in long_kept:
    assert text not in long_pack["chapter_summary"]


def chapter_part(summary, number):
    prefix = f"Chapter {number}: "
    for part in summary.split(" / "):
        if part.startswith(prefix):
            return part
    raise AssertionError(prefix)


twenty_scenes = [{
    "scene_id": "early", "scene_number": 1, "chapter_number": 99,
    "events": [f"early {index}" for index in range(1, 31)],
}]
for number in range(1, 21):
    twenty_scenes.append({
        "scene_id": f"mid{number}", "scene_number": 1 + number, "chapter_number": number,
        "events": [f"chapter mark {number} archive"],
    })
twenty_scenes.append({
    "scene_id": "tail", "scene_number": 22, "chapter_number": 99,
    "events": [f"late {index}" for index in range(1, 91)],
})
twenty = build_established_facts(twenty_scenes)
assert all(f"Chapter {number}" in twenty["chapter_summary"] for number in range(1, 21))
assert "chapter mark 1" in chapter_part(twenty["chapter_summary"], 1)
assert len(twenty["chapter_summary"]) <= CHAPTER_SUMMARY_CAP

eighty_scenes = [{
    "scene_id": "early", "scene_number": 1, "chapter_number": 99,
    "events": [f"early {index}" for index in range(1, 31)],
}]
for number in range(1, 81):
    eighty_scenes.append({
        "scene_id": f"mid{number}", "scene_number": 1 + number, "chapter_number": number,
        "events": [f"chap mark {number} " + "x" * 190],
    })
eighty_scenes.append({
    "scene_id": "tail", "scene_number": 82, "chapter_number": 99,
    "events": [f"late {index}" for index in range(1, 91)],
})
eighty = build_established_facts(eighty_scenes)
assert all(f"Chapter {number}" in eighty["chapter_summary"] for number in range(1, 81))
assert "chap mark 1" in chapter_part(eighty["chapter_summary"], 1)
assert len(eighty["chapter_summary"]) <= CHAPTER_SUMMARY_CAP
assert len(eighty["chapter_summary"]) <= 7200

assert is_irreversible_fact("Lin Zhao entered Archive Room and stated her purpose") is True
assert is_irreversible_fact("the night watchman entered the Preservation tier with her") is True
assert is_irreversible_fact("Lin Zhao climbed to Memory Hall before the tide") is True
assert is_irreversible_fact("") is False
assert is_irreversible_fact({"dirty": True}) is False
assert is_irreversible_fact("this scene did not enter") is False
assert is_irreversible_fact("never entered") is False
assert is_irreversible_fact("did not cross the threshold") is False
assert is_irreversible_fact("Lin Zhao formally proposed entering Glyph Vault") is False
assert is_irreversible_fact("proposed to enter the Unnamed tier to check numbers") is False
assert is_irreversible_fact("the register added that the case was not opened") is False
assert is_irreversible_fact("did not take or open the case") is False
assert is_irreversible_fact("he has not seen the case put on the shelf") is False
assert is_irreversible_fact("the case bearer came along the path, steps light") is False
assert is_irreversible_fact("last night entered the Preservation tier, today did not enter Glyph Vault") is True


instruction = established_facts_instruction()
assert "established_facts" in instruction
assert "context_pack.established_facts" in instruction
assert "progression_baseline" in instruction
assert "kind=canon" in instruction
assert "chapter_summary" in instruction
assert "context_pack.chapter_summary" in instruction
assert "each chapter" in instruction
assert "林照" not in instruction
assert "灯塔" not in instruction
assert "档案室" not in instruction
assert "established_facts" not in MEMORY_REFUSAL_RETRY_PACK_KEYS

world_instruction = world_state_instruction()
assert "world_state" in world_instruction
assert "now-state" in world_instruction
assert "offstage" in world_instruction
assert "clocks" in world_instruction
assert "measures" in world_instruction
assert "yesterday" in world_instruction
assert "林照" not in world_instruction
assert "灯塔" not in world_instruction
assert "档案室" not in world_instruction

assert "established_facts" in first_draft_writing_instruction()
assert "established_facts" in planning_progression_instruction()
assert "world_state" in first_draft_writing_instruction()
assert "world_state" in planning_progression_instruction()
assert "now-state" in first_draft_writing_instruction()
assert "now-state" in planning_progression_instruction()
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
    {"scene_id": "s1", "scene_number": 1, "text": "reached the shore first"},
])
SAFE = "Lin Zhao's soles sank half an inch into wet sand. She stopped and did not keep walking up the shore."


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


expect_gate("never entered", None, ok=True)
expect_gate("never entered", established_facts_snapshot(), ok=True)
expect_gate("never entered", {"facts": []}, ok=True)
expect_gate("从未进入", LEDGER, ok=True)

for phrase in ("never entered", "never went in", "has never entered"):
    expect_gate(phrase, LEDGER, ok=False, found=phrase)
expect_gate("still has not appeared", LEDGER, ok=False, found="still has not appeared")

expect_gate("this scene did not enter", LEDGER, ok=True)
expect_gate("this scene never entered the three tiers", LEDGER, ok=True)
expect_gate("tonight still has not appeared", LEDGER, ok=True)
expect_gate("did not cross the threshold", LEDGER, ok=True)
expect_gate("has not crossed the threshold", LEDGER, ok=True)
expect_gate("still has not entered", LEDGER, ok=True)
expect_gate("she did not enter", LEDGER, ok=True)

expect_gate(SAFE, LEDGER, ok=True)
expect_gate("Lin Zhao's hand stopped on the knot. The twin knots below the red thread were left by her younger sister Lin Lan.", LEDGER, ok=True)
expect_gate("Lin Zhao stood up, knees stiff. She watched the night watchman put the chip back in the numbered slot.", LEDGER, ok=True)


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
assert build_world_state("dirty") == empty_world

split_world = build_world_state({
    "location": "stone steps at the shore",
    "time_context": "tide not gone, 4 a.m. not yet",
    "characters": ["she stood on the steps", "the night watchman has not arrived", "people at the yard stayed behind", "the person who came up"],
})
assert split_world["location"] == "stone steps at the shore"
assert split_world["time_context"] == "tide not gone, 4 a.m. not yet"
assert split_world["present"] == ["she stood on the steps", "the person who came up"]
assert split_world["offstage"] == ["the night watchman has not arrived", "people at the yard stayed behind"]
assert "4 a.m." in split_world["clocks"]

late = build_world_state({
    "characters": ["Lin Wan: not present, her memory still archived", "already left the ferry", "the person still at the door"],
})
assert "Lin Wan: not present, her memory still archived" in late["offstage"]
assert "already left the ferry" in late["offstage"]
assert "Lin Wan: not present, her memory still archived" not in late["present"]
assert "the person still at the door" in late["present"]

assert build_world_state({
    "characters": ["people onstage", {"dirty": True}, "a companion did not come", 3, "another person stayed behind"],
})["present"] == ["people onstage"]
assert build_world_state({
    "characters": ["people onstage", {"dirty": True}, "a companion did not come", 3, "another person stayed behind"],
})["offstage"] == ["a companion did not come", "another person stayed behind"]
assert {"dirty": True} not in build_world_state({
    "characters": ["people onstage", {"dirty": True}, "a companion did not come"],
})["present"]
assert {"dirty": True} not in build_world_state({
    "characters": ["people onstage", {"dirty": True}, "a companion did not come"],
})["offstage"]
assert build_world_state({"location": {"name": "door"}, "time_context": ["night"]})["location"] == ""
assert build_world_state({"location": {"name": "door"}, "time_context": ["night"]})["time_context"] == ""

measured = build_world_state({
    "events": ["the rope end showed two spans", "visible length about a finger more"],
    "characters": ["the person with a span in hand"],
})
assert "two spans" in measured["measures"]
assert "a finger" in measured["measures"]
assert "a span" not in measured["measures"]
assert measured["measures"] == ["two spans", "a finger"]

assert build_world_state({"time_context": "the same day as the last scene, morning light"})["day_relation"] == "same_day"
assert build_world_state({"time_context": "the next day at the same hour"})["day_relation"] == "next_day"
assert build_world_state({"time_context": "tide night"})["day_relation"] == ""

clocks = build_world_state({"time_context": "after 4 a.m., 5 a.m. not yet"})["clocks"]
assert "4 a.m." in clocks
assert "5 a.m." in clocks


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


expect_world("4 p.m. arrived", None, ok=True)
expect_world("yesterday's new edge", {}, ok=True)
expect_world("4 p.m. arrived", build_world_state(), ok=True)

clock_state = {"clocks": ["4 a.m."], "measures": [], "offstage": [], "day_relation": ""}
expect_world("4 p.m. arrived", clock_state, ok=False, kind="clock_rewrite")
expect_world("noon she stood at the door", clock_state, ok=True)
expect_world("still 4 a.m.", clock_state, ok=True)

measure_state = {"clocks": [], "measures": ["two spans"], "offstage": [], "day_relation": ""}
expect_world("same as yesterday, a finger more", measure_state, ok=False, kind="measure_rewrite")
expect_world("visible length about a finger more", measure_state, ok=True)
expect_world("showed two spans", measure_state, ok=True)

same_day = {"clocks": [], "measures": [], "offstage": [], "day_relation": "same_day"}
expect_world("yesterday's new edge", same_day, ok=False, kind="same_day_yesterday")
expect_world("stepping on yesterday's old print", same_day, ok=True)
expect_world("yesterday's new edge", {"clocks": [], "measures": [], "offstage": [], "day_relation": "next_day"}, ok=True)

offstage_state = {"clocks": [], "measures": [], "offstage": ["Lin Wan: not present, her memory still archived"], "day_relation": ""}
expect_world("Lin Wan walked in", offstage_state, ok=False, kind="offstage_arrival")
expect_world("Lin Wan's brass plate still in the slot", offstage_state, ok=True)


DIRTY_EVENTS = [
    "entered the Preservation tier", "never entered", "this scene did not enter", "never went in",
    "did not cross the threshold", "still has not appeared", "has not crossed the threshold",
    "still has not entered", "reached the shore first",
]
DIRTY_ABSENCES = [
    "never entered", "this scene did not enter", "never went in", "did not cross the threshold",
    "still has not appeared", "has not crossed the threshold", "still has not entered",
]
DIRTY_STATE = {
    "characters": ["Lin Zhao"],
    "events": list(DIRTY_EVENTS),
    "relationship_changes": [],
    "unresolved_threads": [],
    "location": "door",
    "time_context": "night",
}
split = split_accepted_scene_state(DIRTY_STATE)
assert split["present"]["events"] == ["entered the Preservation tier", "reached the shore first"]
assert split["absences"] == DIRTY_ABSENCES
assert "present" not in DIRTY_STATE and "absences" not in DIRTY_STATE

CLEAN_STATE = {
    "characters": ["Lin Zhao"],
    "events": ["reached the shore first", "entered the Preservation tier"],
    "relationship_changes": [],
    "unresolved_threads": [],
    "location": "door",
    "time_context": "night",
}
assert present_scene_state(CLEAN_STATE) == CLEAN_STATE
assert progression_baseline_from_state(CLEAN_STATE) == CLEAN_STATE

assert present_scene_state({"location": "never entered"})["location"] == ""
assert present_scene_state({"location": "door"})["location"] == "door"
assert present_scene_state({"events": ["entered the Preservation tier", {"dirty": True}, "never entered"]})["events"] == [
    "entered the Preservation tier", {"dirty": True},
]
assert is_scene_absence({"dirty": True}) is False
assert is_scene_absence("she did not enter") is False


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
    add_report(db, 1, ["reached the shore first", {"dirty": 1}])
    add_report(db, 2, ["entered the Preservation tier"])
    add_report(db, 3, ["reached the shore first", "saw the number"])
    add_report(db, 3, ["failed stay out"], status="failed", attempt=2)
    db.commit()
    empty = load_established_facts(db, book_id="b", before_scene_number=1)
    expect_empty(empty)
    loaded = load_established_facts(db, book_id="b", before_scene_number=4)
    assert [item["text"] for item in loaded["facts"]] == ["reached the shore first", "entered the Preservation tier", "saw the number"]
    assert [item["scene_number"] for item in loaded["facts"]] == [1, 2, 3]
    db.close()


with tempfile.TemporaryDirectory() as directory:
    db = open_book(directory)
    add_scene(db, 1)
    add_scene(db, 2)
    add_report(db, 1, list(DIRTY_EVENTS))
    db.commit()
    loaded = load_established_facts(db, book_id="b", before_scene_number=2)
    assert [item["text"] for item in loaded["facts"]] == ["entered the Preservation tier", "reached the shore first"]
    assert all(item["text"] not in DIRTY_ABSENCES for item in loaded["facts"])
    stored = json.loads(db.execute(
        "select accepted_scene_state_json from quality_reports where scene_id=?", ("s1",)).fetchone()[0])
    assert stored["events"] == DIRTY_EVENTS
    assert "present" not in stored and "absences" not in stored
    db.close()


passed = established_facts_snapshot(facts=[
    {"scene_id": "s1", "scene_number": 1, "text": "reached the shore first"},
])
with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "pack.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',4,null,null,'2026','2026')")
    db.commit()
    previous = {"events": ["last scene now"], "location": "door"}
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
    return scene_plan(number)


def prose(text):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, number=1):
    return reviewer_result(role, number=number)


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
            return prose(self.texts.pop(0) if self.texts else words(1000, lead=SAFE + " word", token="beta"))
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
                "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "word",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({
            "review_world": "world_consistency", "review_plot": "character_plot",
            "review_style": "language_experience",
        }[role], number)


def confirm_scene1(db, book, events=None, *, location="lighthouse", time_context="night", characters=None):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose(words(1000)), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": list(characters or ["Lin Zhao"]), "location": location, "time_context": time_context,
                    "events": list(events or ["investigation"]), "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = words(1000, lead="never entered", token="alpha")
passing = words(1000, lead=SAFE + " word", token="beta")
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
    confirm_scene1(db, book, events=["never entered", "entered the Preservation tier"])
    stored = json.loads(db.execute(
        "select accepted_scene_state_json from quality_reports where scene_id=?",
        (book + "_scene_1",)).fetchone()[0])
    assert stored["events"] == ["never entered", "entered the Preservation tier"]
    assert "present" not in stored and "absences" not in stored
    db.close()
    adapter = FactsDraftAdapter([words(1000, lead=SAFE + " word", token="beta")])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    previous = planning["input"]["context_pack"]["previous_scene_state"]
    facts = [item["text"] for item in planning["input"]["context_pack"]["established_facts"]["facts"]]
    baseline = planning["input"]["progression_baseline"]
    assert "never entered" not in previous.get("events", [])
    assert "entered the Preservation tier" in previous.get("events", [])
    assert "never entered" not in facts
    assert "entered the Preservation tier" in facts
    assert "never entered" not in baseline.get("events", [])
    assert "entered the Preservation tier" in baseline.get("events", [])


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "facts-summary.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book, events=[f"event {index}" for index in range(1, 131)])
    db.close()
    adapter = FactsDraftAdapter([words(1000, lead=SAFE + " word", token="beta")])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    pack = planning["input"]["context_pack"]
    assert "event 31" in pack["chapter_summary"]
    assert "event 31" not in [item["text"] for item in pack["established_facts"]["facts"]]
    assert "chapter_summary" not in pack["established_facts"]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "world-state.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(
        db, book, events=["the rope end showed two spans"],
        location="stone steps at the shore", time_context="after 4 a.m., 4 a.m. not yet",
        characters=["she stood on the steps", "the night watchman has not arrived"],
    )
    db.close()
    adapter = FactsDraftAdapter([words(1000, lead=SAFE + " word", token="beta")])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"REAL_TEST_SCENE_COUNT": "2"})
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene["final_status"] == "waiting_confirmation"
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    pack = planning["input"]["context_pack"]
    assert pack["previous_scene_state"]["location"] == "stone steps at the shore"
    assert "4 a.m." in pack["previous_scene_state"]["time_context"]
    assert pack["world_state"] == build_world_state(pack["previous_scene_state"])
    assert pack["world_state"]["location"] == "stone steps at the shore"
    assert "4 a.m." in pack["world_state"]["time_context"]
    assert "4 a.m." in pack["world_state"]["clocks"]
    assert "two spans" in pack["world_state"]["measures"]
    assert pack["world_state"]["offstage"]
    assert "she stood on the steps" in pack["world_state"]["present"]
    assert "the night watchman has not arrived" in pack["world_state"]["offstage"]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "world-gate.db"
    db, book = seed(path, scene_count=2)
    confirm_scene1(db, book, events=["reached the shore first"], location="stone steps at the shore", time_context="4 a.m.")
    db.close()
    adapter = FactsDraftAdapter([
        words(1000, lead="4 p.m. arrived", token="alpha"),
        words(1000, lead=SAFE + " word", token="beta"),
    ])
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

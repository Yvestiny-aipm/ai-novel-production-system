"""Chapter destination signals. Temporary DB only; historical data/*.db unread."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.chapter_state import (CHAPTER_STATE_KEYS, build_chapter_state, chapter_state_instruction,
    empty_chapter_state, load_chapter_context)
from backend.context_pack import ContextPackService
from backend.harness import classify_scene_plan_quality, required_fields_validator
from backend.siliconflow import (MEMORY_REFUSAL_RETRY_PACK_KEYS, first_draft_writing_instruction,
    planning_progression_instruction, reviewer_plot_instruction, reviewer_style_instruction,
    reviewer_world_instruction)


empty = build_chapter_state()
assert set(empty) == set(CHAPTER_STATE_KEYS)
assert empty == empty_chapter_state()
assert empty["chapter_number"] == 0
assert empty["scene_in_chapter"] == 0
assert empty["scenes_in_chapter"] == 0
assert empty["is_chapter_open"] is False
assert empty["is_chapter_close"] is False
assert empty["destination"] == ""
assert empty["previous_destination"] == ""
assert empty["previous_end_location"] == ""
assert build_chapter_state(None) == empty
assert build_chapter_state("脏") == empty
assert build_chapter_state({"destination": "南码头登记处"})["destination"] == "南码头登记处"
assert build_chapter_state({"destination": "南码头登记处"})["chapter_number"] == 0

planning = planning_progression_instruction()
assert "chapter_state" in planning
assert "chapter_destination" in planning
assert "previous_destination" in planning
assert "不得照抄" in planning
chapter_text = chapter_state_instruction()
assert "chapter_state" in chapter_text
assert "林照" not in chapter_text
assert "灯塔" not in chapter_text
assert "档案室" not in chapter_text
assert "旧堤" not in chapter_text
assert "潮水" not in chapter_text
assert "维护所" not in chapter_text
assert "chapter_state" not in first_draft_writing_instruction()
for reviewer in (
    reviewer_world_instruction(),
    reviewer_plot_instruction(),
    reviewer_style_instruction(),
):
    assert "chapter_state" not in reviewer
    assert "chapter_destination" not in reviewer
    assert "validate_chapter" not in reviewer
assert "chapter_state" not in MEMORY_REFUSAL_RETRY_PACK_KEYS

old_plan = {
    "contract_type": "ScenePlan",
    "contract_version": "v1",
    "payload": {
        "scene_goal": "goal",
        "entrance_state": {"x": 1},
        "exit_state": {"x": 2},
        "characters": ["在场的人"],
        "location": "北仓内侧",
        "time_context": "夜晚",
        "conflict": "调查",
        "action_beats": ["进入"],
        "must_happen": ["发现"],
        "must_not_happen": ["解决"],
        "knowledge_boundary": "已知",
        "target_word_count": 1250,
        "acceptance_criteria": ["有效"],
        "validation_result": {"ok": True},
        "ready_for_writing": True,
        "progression_requirements": [{
            "progress_type": "new_clue",
            "target_key": "编号",
            "before_state": "未知",
            "expected_after_state": "获得线索",
            "acceptance_criterion": "正文出现新线索",
        }],
    },
}
assert "chapter_destination" not in old_plan["payload"]
assert classify_scene_plan_quality(old_plan) is None
required_fields_validator(old_plan, "ScenePlan")


def assemble_pack(db, scene_id="s", chapter_id="c", **kwargs):
    return ContextPackService(db).assemble(
        pack_id=f"p_{scene_id}", book_id="b", chapter_id=chapter_id, scene_id=scene_id, version=1,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state={"characters": ["在场的人"]},
        **kwargs,
    )


def add_scene(db, scene, chapter, number):
    db.execute(
        "insert into scenes values (?,?,?,?,?,?,?,?)",
        (scene, "b", chapter, number, None, None, "2026", "2026"),
    )


def add_plan(db, scene, chapter, destination=None, goal="推进"):
    payload = {"scene_goal": goal, "must_happen": ["推进"]}
    if destination is not None:
        payload["chapter_destination"] = destination
    db.execute(
        "insert into scene_plans values (?,?,?,?,?,?,?,?,?,?,?)",
        (f"{scene}_plan_v1", "b", chapter, scene, 1, 1, 1, "ready",
         json.dumps(payload, ensure_ascii=False), "h", "2026"),
    )


def add_passed(db, scene, chapter, location):
    draft = f"{scene}_d1"
    db.execute(
        "insert into prose_drafts values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (draft, "b", chapter, scene, 1, 1, 1, 1, "正", 1, 1250, 1, "{}",
         "passed", "h", "hc", 1, 1, "2026"),
    )
    db.execute(
        "insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{scene}_r1", "b", chapter, scene, draft, "h", 1, "completed", "[]",
         0, 0, 0, 0, 0, "complete",
         json.dumps({"location": location, "events": ["推进"]}, ensure_ascii=False),
         "passed", "2026"),
    )


DEST_NORTH = "拿到北仓第二排货架的编号"
DEST_DOCK = "转到南码头登记处核对"
NORTH_LOCATION = "北仓内侧与第二排货架"

with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "five.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    for number in range(1, 6):
        add_scene(db, f"s{number}", "c", number)
    add_plan(db, "s1", "c", DEST_NORTH)
    db.commit()
    first = build_chapter_state(load_chapter_context(db, "b", "s1"))
    assert first["is_chapter_open"] is True
    assert first["is_chapter_close"] is False
    assert first["scene_in_chapter"] == 1
    assert first["scenes_in_chapter"] == 5
    assert first["chapter_number"] == 1
    assert first["destination"] == ""
    assert first["previous_destination"] == ""
    assert first["previous_end_location"] == ""
    third = build_chapter_state(load_chapter_context(db, "b", "s3"))
    assert third["is_chapter_open"] is False
    assert third["is_chapter_close"] is False
    assert third["scene_in_chapter"] == 3
    assert third["destination"] == DEST_NORTH
    fifth = build_chapter_state(load_chapter_context(db, "b", "s5"))
    assert fifth["is_chapter_close"] is True
    assert fifth["is_chapter_open"] is False
    assert fifth["scene_in_chapter"] == 5
    assert fifth["destination"] == DEST_NORTH
    packed = assemble_pack(db, scene_id="s3")
    assert packed["chapter_state"] == third
    assert "chapter_state" not in packed["established_facts"]
    db.close()

with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "two-chapters.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c1','b',1,null,'2026','2026')")
    db.execute("insert into chapters values ('c2','b',2,null,'2026','2026')")
    add_scene(db, "s1", "c1", 1)
    add_scene(db, "s2", "c1", 2)
    add_scene(db, "s3", "c2", 3)
    add_scene(db, "s4", "c2", 4)
    add_plan(db, "s1", "c1", DEST_NORTH)
    add_passed(db, "s2", "c1", NORTH_LOCATION)
    add_plan(db, "s3", "c2", DEST_DOCK)
    db.commit()
    open_two = build_chapter_state(load_chapter_context(db, "b", "s3"))
    assert open_two["is_chapter_open"] is True
    assert open_two["is_chapter_close"] is False
    assert open_two["destination"] == ""
    assert "北仓第二排" in open_two["previous_destination"]
    assert "北仓内侧" in open_two["previous_end_location"]
    assert "旧堤" not in json.dumps(open_two, ensure_ascii=False)
    assert "灯塔" not in json.dumps(open_two, ensure_ascii=False)
    close_two = build_chapter_state(load_chapter_context(db, "b", "s4"))
    assert close_two["is_chapter_close"] is True
    assert close_two["is_chapter_open"] is False
    assert close_two["destination"] == DEST_DOCK
    passed = assemble_pack(db, scene_id="s3", chapter_id="c2")
    assert passed["chapter_state"] == open_two
    assert "chapter_state" not in passed["established_facts"]
    assert "chapter_state" not in passed["pacing_state"]
    db.close()

with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "empty.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.commit()
    pack = assemble_pack(db)
    assert pack["chapter_state"]["is_chapter_open"] is True
    assert pack["chapter_state"]["destination"] == ""
    assert pack["chapter_state"]["previous_destination"] == ""
    assert pack["pacing_state"]["same_location_run"] == 0
    assert pack["world_state"]["present"] == ["在场的人"]
    assert pack["established_facts"]["facts"] == []
    injected = {
        "chapter_number": 2,
        "scene_in_chapter": 2,
        "scenes_in_chapter": 2,
        "is_chapter_open": False,
        "is_chapter_close": True,
        "destination": DEST_DOCK,
        "previous_destination": DEST_NORTH,
        "previous_end_location": NORTH_LOCATION,
    }
    override = ContextPackService(db).assemble(
        pack_id="p_override", book_id="b", chapter_id="c", scene_id="s", version=2,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state={"characters": ["在场的人"]},
        chapter_context=injected,
    )
    assert override["chapter_state"] == build_chapter_state(injected)
    assert override["chapter_state"]["destination"] == DEST_DOCK
    assert "chapter_state" not in override["established_facts"]
    db.close()

print("chapter state ok")

"""Planning pacing signals. Temporary DB only; historical data/*.db unread."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.context_pack import ContextPackService
from backend.pacing import (PACING_STATE_KEYS, build_pacing_state, empty_pacing_state,
    location_anchor, location_core, locations_same, pacing_state_instruction)
from backend.siliconflow import (MEMORY_REFUSAL_RETRY_PACK_KEYS, first_draft_writing_instruction,
    planning_progression_instruction, reviewer_plot_instruction, reviewer_style_instruction,
    reviewer_world_instruction)


empty = build_pacing_state()
assert set(empty) == set(PACING_STATE_KEYS)
assert empty == empty_pacing_state()
assert empty["same_location_run"] == 0
assert empty["recent_locations"] == []
assert empty["recent_goals"] == []
assert empty["stall_markers"] == []
assert empty["prior_locations"] == []
assert build_pacing_state(None) == empty
assert build_pacing_state("脏") == empty
assert location_core({"name": "北仓"}) == ""
assert location_core("北仓内侧；货架深处") == "北仓内侧"

assert locations_same("北仓内侧与第二排货架", "北仓内侧，靠近第二排货架") is True
assert locations_same("北仓内侧与第二排货架", "南码头登记处") is False
assert locations_same("北仓内侧", "南码头") is False
assert locations_same("", "北仓内侧与第二排货架") is False

travel = "从南码头登记处转到北仓内侧，核对手册"
assert "北仓内侧" in location_anchor(travel)
assert "南码头" not in location_anchor(travel)
assert location_anchor("北仓内侧与第二排货架") == "北仓内侧与第二排货架"
assert location_anchor({"name": "北仓"}) == ""
assert locations_same(travel, "北仓内侧与第二排货架") is True
assert locations_same(travel, "南码头登记处") is False
assert locations_same("从北仓内侧走到南码头登记处", "南码头登记处") is True
assert locations_same("从北仓内侧走到南码头登记处", "北仓内侧与第二排货架") is False

north = "北仓内侧与第二排货架"
north_variant = "北仓内侧，靠近第二排"
four = [
    {"location": north, "scene_goal": "在货架前等待编号", "must_happen": ["复查货架"]},
    {"location": north_variant, "scene_goal": "继续等待", "must_happen": ["复查同一排"]},
    {"location": north, "scene_goal": "等待回音", "must_happen": ["留下记录"]},
    {"location": north_variant, "scene_goal": "复查缺口", "must_happen": ["等待答复"]},
]
stuck = build_pacing_state(four)
assert stuck["same_location_run"] == 4
assert "等待" in stuck["stall_markers"]
assert "复查" in stuck["stall_markers"]
assert stuck["prior_locations"] == []
assert stuck["recent_locations"] == [item["location"] for item in four]
assert stuck["recent_goals"] == [item["scene_goal"] for item in four]

dock_then_north = [{"location": "南码头登记处", "scene_goal": "取得编号", "must_happen": ["拿到编号"]}] + four
moved = build_pacing_state(dock_then_north)
assert moved["same_location_run"] == 4
assert "南码头登记处" in moved["prior_locations"]
assert all(not locations_same(item, north) for item in moved["prior_locations"])

two = [
    {"location": north, "scene_goal": "复核编号", "must_happen": ["复核货架"]},
    {"location": north_variant, "scene_goal": "再复核一次", "must_happen": ["留下"]},
]
short = build_pacing_state(two)
assert short["same_location_run"] == 2
assert "复核" in short["stall_markers"]

arrived = build_pacing_state([
    {"location": "南码头登记处", "scene_goal": "取得编号", "must_happen": ["拿到编号"]},
    {"location": travel, "scene_goal": "核对手册", "must_happen": ["记下编号"]},
])
assert arrived["same_location_run"] == 1
assert "南码头登记处" in arrived["prior_locations"]
assert arrived["recent_locations"] == ["南码头登记处", travel]

planning = planning_progression_instruction()
assert "pacing_state" in planning
assert "same_location_run" in planning
assert "prior_locations" in planning
assert "不得只靠" in planning
pacing_text = pacing_state_instruction()
assert "pacing_state" in pacing_text
assert "不是新门栏" in pacing_text
assert "落脚点" in pacing_text
assert "出发地" in pacing_text
assert "林照" not in pacing_text
assert "灯塔" not in pacing_text
assert "档案室" not in pacing_text
assert "旧堤" not in pacing_text
assert "潮水" not in pacing_text
assert "pacing_state" not in first_draft_writing_instruction()
for reviewer in (
    reviewer_world_instruction(),
    reviewer_plot_instruction(),
    reviewer_style_instruction(),
):
    assert "pacing_state" not in reviewer
    assert "same_location_run" not in reviewer
    assert "validate_pacing" not in reviewer
assert "pacing_state" not in MEMORY_REFUSAL_RETRY_PACK_KEYS


def assemble_pack(db, scene_id="s", **kwargs):
    return ContextPackService(db).assemble(
        pack_id="p", book_id="b", chapter_id="c", scene_id=scene_id, version=1,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state={"characters": ["在场的人"]},
        **kwargs,
    )


with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "empty.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.commit()
    pack = assemble_pack(db)
    assert pack["pacing_state"] == empty
    assert pack["world_state"]["present"] == ["在场的人"]
    assert pack["established_facts"]["facts"] == []
    assert "pacing_state" not in pack["established_facts"]
    db.close()


with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "passed.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',5,null,null,'2026','2026')")
    db.commit()
    pack = assemble_pack(db, pacing_recent=four)
    assert pack["pacing_state"] == stuck
    assert pack["pacing_state"] is not pack["world_state"]
    assert "pacing_state" not in pack["established_facts"]
    db.close()


def add_completed(db, number, location, goal, must):
    scene = f"s{number}"
    db.execute("insert into scenes values (?,?,?,?,?,?,?,?)",
               (scene, "b", "c", number, None, None, "2026", "2026"))
    db.execute(
        """insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,
           active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at)
           values (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"{scene}_task", "scene", "b", "c", scene, "memory_processing", "completed", "wait",
         "[]", "[]", f"{scene}_id", "2026", "2026"),
    )
    db.execute(
        "insert into scene_plans values (?,?,?,?,?,?,?,?,?,?,?)",
        (f"{scene}_plan_v1", "b", "c", scene, 1, 1, 1, "ready",
         json.dumps({"scene_goal": goal, "must_happen": [must]}, ensure_ascii=False),
         "h", "2026"),
    )
    draft = f"{scene}_d1"
    db.execute(
        "insert into prose_drafts values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (draft, "b", "c", scene, 1, 1, 1, 1, "潮", 1, 1250, 1, "{}",
         "passed", "h", "hc", 1, 1, "2026"),
    )
    db.execute(
        "insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{scene}_r1", "b", "c", scene, draft, "h", 1, "completed", "[]",
         0, 0, 0, 0, 0, "complete",
         json.dumps({"location": location, "events": ["推进"]}, ensure_ascii=False),
         "passed", "2026"),
    )


with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "seeded.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    for number, item in enumerate(four, 1):
        add_completed(db, number, item["location"], item["scene_goal"], item["must_happen"][0])
    db.execute("insert into scenes values ('s5','b','c',5,null,null,'2026','2026')")
    db.commit()
    packed = assemble_pack(db, scene_id="s5")
    assert packed["pacing_state"] == build_pacing_state(four)
    assert packed["pacing_state"]["same_location_run"] == 4
    assert "pacing_state" not in packed["established_facts"]
    db.close()


print("pacing ok")

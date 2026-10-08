"""Frozen setting canon and conservative draft gate. No historical DBs opened."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import reviewer_result, scene_plan, words

from backend.setting_canon import (SETTING_CANON_REASON, SETTING_CANON_RULE,
    setting_canon_instruction, setting_canon_snapshot, validate_setting_canon)
from backend.context_pack import ContextPackService
from backend.siliconflow import (MEMORY_REFUSAL_RETRY_PACK_KEYS, first_draft_writing_instruction,
    planning_progression_instruction, reviewer_world_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


MINGLU = "Lin Zhao pushed the stone door and walked into the Inscription Pavilion. The racks had no brass plates."
BEIKU = "Stone slabs stood in the Stele Vault. The lamp keeper said nothing."
STONE_BEIKU = "The Stele Store door was half open. Damp air came in."
MINGWEN = "The Inscription Hall walls were full of names."
TEMPLE = "A blank hung at the center of the Memory Temple."
SAME_ROOM = "The Archive Room is Memory Hall, and the Glyph Vault is the same room."
SAME_THREE = "Archive Room, Memory Hall, and Glyph Vault are the same room."
REWRITE = "The lighthouse rewrote her memory and covered that night."
COMPLETE = "The lighthouse completed the last character of her name."
OUTSIDE = "Lin Zhao went to the public archive. People sat at Amah Zhou's house in town. The Jiang house yard was empty."
LAYERS = "Archive Room racks held chips and brass plates. Glyph Vault kept only wooden cases. Memory Hall showed wall script."
PROPS = "Lin Zhao set the oilcloth bundle and the tin toolbox by her feet and did not open them."
NO_INTERIOR = "Tide water hit the shore. Lin Zhao stood on the sand and did not walk into the tower."
NEGATED = "The lighthouse cannot rewrite a person's memory and cannot complete anyone's name."


def expect(text, *, ok):
    result = validate_setting_canon(text)
    if ok:
        assert result["status"] == "passed", result
        assert result["reason"] is None
        assert result["conflicts"] == []
    else:
        assert result["status"] == "failed", result
        assert result["reason"] == SETTING_CANON_REASON
        assert result["conflicts"]
    return result


expect(MINGLU, ok=False)
expect(BEIKU, ok=False)
expect(STONE_BEIKU, ok=False)
expect(MINGWEN, ok=False)
expect(TEMPLE, ok=False)
expect(SAME_ROOM, ok=False)
expect(SAME_THREE, ok=False)
expect(REWRITE, ok=False)
expect(COMPLETE, ok=False)
expect(OUTSIDE, ok=True)
expect(LAYERS, ok=True)
expect(PROPS, ok=True)
expect(NO_INTERIOR, ok=True)
expect(NEGATED, ok=True)
expect("", ok=True)
expect(None, ok=True)
expect("林照走进铭录阁，柜架上没有铜牌。", ok=True)

canon = setting_canon_snapshot()
assert canon["canon_version"] == 1
assert canon["rule"] == SETTING_CANON_RULE
places = {item["name"]: item for item in canon["places"]}
assert list(places) == ["Archive Room", "Memory Hall", "Glyph Vault"]
assert places["Archive Room"]["layer"] == "Preservation tier"
assert places["Archive Room"]["also"] == ["Preservation tier"]
assert places["Archive Room"]["props"] == ["chips", "brass plates", "racks"]
assert "store archived memory media" in places["Archive Room"]["function"]
assert places["Memory Hall"]["layer"] == "Display tier"
assert places["Memory Hall"]["props"] == ["wall script"]
assert "cannot rewrite" in places["Memory Hall"]["function"]
assert places["Glyph Vault"]["layer"] == "Unnamed tier"
assert places["Glyph Vault"]["props"] == ["wooden cases"]
assert "unnamed" in places["Glyph Vault"]["function"]
assert canon["must_not"]
blob = json.dumps(canon, ensure_ascii=False)
assert "Inscription Pavilion" not in blob

for instruction in (
    setting_canon_instruction(),
    first_draft_writing_instruction(),
    planning_progression_instruction(),
    reviewer_world_instruction(),
):
    assert "setting_canon" in instruction
    assert "context_pack.setting_canon" in instruction
    assert "Archive Room" in instruction and "Memory Hall" in instruction and "Glyph Vault" in instruction

assert "setting_canon" in MEMORY_REFUSAL_RETRY_PACK_KEYS


with tempfile.TemporaryDirectory() as directory:
    db = sqlite3.connect(Path(directory) / "pack.db")
    db.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.commit()
    pack = ContextPackService(db).assemble(
        pack_id="p", book_id="b", chapter_id="c", scene_id="s", version=1,
        target_agent="planning", target_node="planning", brief_version=1, plan_version=1,
        story_state_version=1, canon_version=1, sources=[],
        previous_scene_state={
            "location": "Inscription Pavilion",
            "places": [{"name": "Inscription Pavilion", "layer": "fourth layer"}],
            "events": ["Archive Room is Memory Hall"],
        },
    )
    assert pack["setting_canon"] == setting_canon_snapshot(version=1)
    assert pack["previous_scene_state"]["location"] == "Inscription Pavilion"
    assert pack["setting_canon"]["places"][0]["name"] == "Archive Room"
    assert pack["setting_canon"] != pack["previous_scene_state"]
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


class SettingDraftAdapter:
    def __init__(self, texts):
        self.texts, self.calls = list(texts), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose(self.texts.pop(0) if self.texts else words(1000, lead=LAYERS + " word", token="beta"))
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


def confirm_scene1(db, book):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose(words(1000)), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔", "time_context": "夜",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = words(1000, lead=MINGLU, token="alpha")
passing = words(1000, lead=LAYERS + " word", token="beta")
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "setting-fail.db"
    db, book = seed(path)
    confirm_scene1(db, book)
    db.close()
    adapter = SettingDraftAdapter([failing, passing])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    scene = result["scenes"][1]
    assert scene.get("technical_error") is None
    assert scene.get("block_reason") != SETTING_CANON_REASON
    assert scene["final_status"] == "waiting_confirmation"
    roles = [call["task_type"] for call in adapter.calls]
    assert roles.count("planning") == 1
    assert roles.count("writing") == 2
    assert any(role.startswith("review_") for role in roles)
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    assert planning["input"]["context_pack"]["setting_canon"] == setting_canon_snapshot(version=1)
    assert planning["input"]["context_pack"]["setting_canon"] != planning["input"]["context_pack"]["previous_scene_state"]
    db = sqlite3.connect(path)
    reasons = [row[0] for row in db.execute(
        "select reason from task_events where task_id=? and event_type='rework_requested' order by created_at",
        (book + "_scene_2_task",))]
    assert SETTING_CANON_REASON in reasons
    assert db.execute(
        "select current_node,content_attempt_in_plan from task_states where scene_id=?",
        (book + "_scene_2",)).fetchone()[1] == 1
    queued = db.execute("select count(*) from exception_queue where task_id=?", (book + "_scene_2_task",)).fetchone()[0]
    assert queued == 0
    db.close()


print("setting canon ok")

"""Frozen setting canon and conservative draft gate. No historical DBs opened."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.setting_canon import (SETTING_CANON_REASON, SETTING_CANON_RULE,
    setting_canon_instruction, setting_canon_snapshot, validate_setting_canon)
from backend.context_pack import ContextPackService
from backend.siliconflow import (MEMORY_REFUSAL_RETRY_PACK_KEYS, first_draft_writing_instruction,
    planning_progression_instruction, reviewer_world_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


MINGLU = "林照推开石门，走进铭录阁，柜架上没有铜牌。"
BEIKU = "碑库里立着石板，守灯的不说话。"
STONE_BEIKU = "石碑库的门半开着，潮气灌进来。"
MINGWEN = "铭文殿墙上全是名字。"
TEMPLE = "记忆圣殿中央悬着一块空白。"
SAME_ROOM = "档案室就是记忆厅，字库也在同一间房。"
SAME_THREE = "档案室、记忆厅、字库是同一间房。"
REWRITE = "灯塔改写了她的记忆，把那一夜盖住。"
COMPLETE = "灯塔补全了她的名字末字。"
OUTSIDE = "林照去了公共档案馆。镇上的周阿婆家门口坐着人。蒋家院子空着。"
LAYERS = "档案室柜架上码着晶片和铜牌。字库只收木匣。记忆厅墙上浮着字。"
PROPS = "林照把油布包和铁皮工具箱放在脚边，没有打开。"
NO_INTERIOR = "潮水拍岸，林照站在沙地上，没有往塔里走。"
NEGATED = "灯塔不能改写人的记忆，也不能补全任何人的名字。"


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

canon = setting_canon_snapshot()
assert canon["canon_version"] == 1
assert canon["rule"] == SETTING_CANON_RULE
places = {item["name"]: item for item in canon["places"]}
assert list(places) == ["档案室", "记忆厅", "字库"]
assert places["档案室"]["layer"] == "保存层"
assert places["档案室"]["also"] == ["保存层"]
assert places["档案室"]["props"] == ["晶片", "铜牌", "柜架"]
assert "保存已归档的记忆载体" in places["档案室"]["function"]
assert places["记忆厅"]["layer"] == "展示层"
assert places["记忆厅"]["props"] == ["墙上浮字"]
assert "不能改写" in places["记忆厅"]["function"]
assert places["字库"]["layer"] == "未成名层"
assert places["字库"]["props"] == ["木匣"]
assert "未成名" in places["字库"]["function"]
assert canon["must_not"]
blob = json.dumps(canon, ensure_ascii=False)
assert "抵换记忆" not in blob
assert "蓝布衫" not in blob
assert "周阿婆换名" not in blob
assert "蒋家残片" not in blob
assert "空匣" not in blob
assert "铭录阁" not in blob

for instruction in (
    setting_canon_instruction(),
    first_draft_writing_instruction(),
    planning_progression_instruction(),
    reviewer_world_instruction(),
):
    assert "setting_canon" in instruction
    assert "context_pack.setting_canon" in instruction
    assert "档案室" in instruction and "记忆厅" in instruction and "字库" in instruction

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
            "location": "铭录阁",
            "places": [{"name": "铭录阁", "layer": "第四层"}],
            "events": ["档案室就是记忆厅"],
        },
    )
    assert pack["setting_canon"] == setting_canon_snapshot(version=1)
    assert pack["previous_scene_state"]["location"] == "铭录阁"
    assert pack["setting_canon"]["places"][0]["name"] == "档案室"
    assert pack["setting_canon"] != pack["previous_scene_state"]
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
            return prose(self.texts.pop(0) if self.texts else LAYERS + "潮" * 1000)
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


def confirm_scene1(db, book):
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    save_plan(db, book, chapter, scene, plan(1), "hc_p1")
    save_draft(db, book, chapter, scene, prose("潮" * 1000), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        scene + "_report_v1", book, chapter, scene, scene + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔", "time_context": "夜",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []},
                   ensure_ascii=False),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (scene,))
    db.commit()


failing = MINGLU + "潮" * 1000
passing = LAYERS + "潮" * 1000
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

"""Planning-time before_state must copy the previous confirmed baseline."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import PLANNING_PROMPT_VERSION, validate_scene_plan_against_input, ContractFormatError
from backend.progression import (PLAN_BEFORE_STATE_REASON, plan_before_state_conflict_items,
    plan_before_state_conflict_reason, progression_baseline_from_state)
from backend.siliconflow import (build_chat_messages, contract_system_prompt,
    planning_progression_instruction)
from integration.run_real_test import run, save_draft, save_plan
from integration.seed_real_test import seed


SCENE1 = "realtest_tide_archive_scene_1"
SCENE2 = "realtest_tide_archive_scene_2"
TASK2 = SCENE2 + "_task"

PREVIOUS = {
    "characters": ["林照"],
    "location": "灯塔档案室",
    "time_context": "夜晚",
    "events": ["林照发现姐姐失踪相关便条", "档案有被改动痕迹"],
    "relationship_changes": ["林照对守灯人产生怀疑"],
    "unresolved_threads": ["林澜失踪尚未定位"],
}

GATES_16_ITEMS = [
    {"progress_type": "new_clue", "target_key": "档案改动",
     "before_state": "林照仅知姐姐失踪，便条暗示档案被改",
     "expected_after_state": "确认档案被改页", "acceptance_criterion": "正文写出改页证据"},
    {"progress_type": "character_state_change", "target_key": "林照警觉",
     "before_state": "林照对守灯人警觉怀疑，但尚未主动行动",
     "expected_after_state": "林照开始盘问守灯人", "acceptance_criterion": "正文出现盘问"},
    {"progress_type": "relationship_change", "target_key": "信任",
     "before_state": "信任破裂，但未直接对抗",
     "expected_after_state": "双方公开对峙", "acceptance_criterion": "正文出现对峙"},
    {"progress_type": "thread_advanced", "target_key": "林澜失踪",
     "before_state": "林照只知道姐姐失踪，线索仍含糊",
     "expected_after_state": "日志指向北礁", "acceptance_criterion": "正文出现北礁"},
    {"progress_type": "conflict_change", "target_key": "档案争夺",
     "before_state": "双方已起疑，但还没有撕破脸",
     "expected_after_state": "守灯人抢走档案", "acceptance_criterion": "正文出现抢夺"},
]


def requirement(progress_type, target_key, before, after):
    return {
        "progress_type": progress_type, "target_key": target_key, "before_state": before,
        "expected_after_state": after, "acceptance_criterion": f"正文明确写出{after}",
    }


def plan_payload(requirements, *, goal="第二场追查档案改动", action="核对被改页"):
    return {
        "scene_goal": goal, "entrance_state": {"ready": True}, "exit_state": {"moved": True},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "追查改档",
        "action_beats": [action], "must_happen": ["发现改档"], "must_not_happen": ["结案"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True},
        "ready_for_writing": True, "progression_requirements": requirements,
    }


def scene_plan(requirements, **payload_opts):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": plan_payload(requirements, **payload_opts)}


def first_scene_plan():
    return scene_plan(
        [requirement("new_clue", "灯塔线索", "未知", "发现便条")],
        goal="第一场发现失踪便条", action="翻开潮痕档案",
    )


def prose():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": "潮" * 1000, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}


def reviewer(role):
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": dict(PREVIOUS),
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现便条", "evidence_text": "潮", "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": "潮"},
    }}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
        "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


def expect_plan_input(response, input_payload, *, ok):
    try:
        validate_scene_plan_against_input(response, input_payload)
    except ContractFormatError as error:
        assert not ok, error
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        assert str(error) == PLAN_BEFORE_STATE_REASON
        return
    if not ok:
        raise AssertionError("rewritten before_state accepted")


# Unit cases 1-10.
baseline = progression_baseline_from_state(PREVIOUS)
assert set(baseline) == {
    "characters", "events", "relationship_changes", "unresolved_threads", "location", "time_context",
}
followup = {"scene_number": 2, "progression_baseline": baseline}
first_scene_input = {"scene_number": 1, "progression_baseline": progression_baseline_from_state({})}

expect_plan_input(first_scene_plan(), first_scene_input, ok=True)
expect_plan_input(scene_plan([requirement("new_clue", "便条", "林照发现姐姐失踪相关便条", "确认改档")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("new_clue", "便条", "林照仅知姐姐失踪，便条暗示档案被改", "确认改档")]), followup, ok=False)
expect_plan_input(scene_plan([requirement("character_state_change", "林照", "林照", "林照开始盘问")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("relationship_change", "怀疑", "林照对守灯人产生怀疑", "公开对峙")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("thread_advanced", "林澜失踪", "林澜失踪尚未定位", "指向北礁")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("thread_closed", "林澜失踪", "林澜失踪尚未定位", "林澜已获救")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("new_clue", "新编号", "未知", "潮痕编号A-17")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("thread_opened", "潮声", "未知", "地下室传来求救录音")]), followup, ok=True)
expect_plan_input(scene_plan([requirement("thread_opened", "林澜失踪", "未知", "林澜失踪尚未定位")]), followup, ok=False)
expect_plan_input(scene_plan(GATES_16_ITEMS), followup, ok=False)

prompt = contract_system_prompt("ScenePlan")
assert "progression_baseline" in prompt
assert PLANNING_PROMPT_VERSION == "planning_progression_v4"
assert "不得总结、改写" in planning_progression_instruction()
assert "顶层独立出现" in planning_progression_instruction()

copied_character = "林照神色紧绷地站在档案柜前"
like_20i_baseline = progression_baseline_from_state({
    **PREVIOUS, "characters": [copied_character, "林照"],
})
like_20i_reqs = [requirement("new_clue", "档案改动", copied_character, "确认改档")]
assert plan_before_state_conflict_reason(like_20i_reqs, like_20i_baseline) == PLAN_BEFORE_STATE_REASON
like_20i_items = plan_before_state_conflict_items(like_20i_reqs, like_20i_baseline)
assert like_20i_items and like_20i_items[0]["progress_type"] == "new_clue"
assert like_20i_items[0]["before_state"] == copied_character
assert set(like_20i_items[0]["allowed_fields"]) == {"events", "unresolved_threads"}
assert "characters" not in like_20i_items[0]["allowed_fields"]
ok_reqs = [requirement("new_clue", "便条", "林照发现姐姐失踪相关便条", "确认改档")]
assert plan_before_state_conflict_reason(ok_reqs, baseline) is None
assert plan_before_state_conflict_items(ok_reqs, baseline) == []

no_fb_messages = build_chat_messages({"contract_type": "ScenePlan", "input": followup})
assert len(no_fb_messages) == 3
assert no_fb_messages[2]["content"] == planning_progression_instruction()
assert "你自称" not in "".join(item["content"] for item in no_fb_messages)
assert "1287" not in "".join(item["content"] for item in no_fb_messages)
fb_input = {
    **followup,
    "planning_revision_feedback": {
        "reason": PLAN_BEFORE_STATE_REASON,
        "failed_plan_version": 1,
        "failed_items": like_20i_items,
    },
}
fb_messages = build_chat_messages({"contract_type": "ScenePlan", "input": fb_input})
assert len(fb_messages) == 4
assert fb_messages[2]["content"] == planning_progression_instruction()
assert fb_messages[3]["role"] == "user"
assert PLAN_BEFORE_STATE_REASON in fb_messages[3]["content"]
assert copied_character in fb_messages[3]["content"]
assert "不得从其他列挪句子" in fb_messages[3]["content"]
assert "禁止交回同一套错误 before_state" in fb_messages[3]["content"]
assert "你自称" not in fb_messages[3]["content"]
assert "1287" not in fb_messages[3]["content"]


def confirm_scene1(db, book, accepted=None):
    chapter = book + "_chapter_1"
    save_plan(db, book, chapter, SCENE1, first_scene_plan(), "hc_p1")
    save_draft(db, book, chapter, SCENE1, prose(), "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        SCENE1 + "_report_v1", book, chapter, SCENE1, SCENE1 + "_draft_v1", "h", 1, "completed", "[]",
        0, 0, 0, 0, 0, "complete", json.dumps(accepted or PREVIOUS, ensure_ascii=False), "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?", (SCENE1,))
    db.commit()


class Scene2PlanAdapter:
    def __init__(self, requirements_list):
        self.requirements_list, self.calls = list(requirements_list), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        if role == "planning":
            requirements = self.requirements_list.pop(0) if self.requirements_list else [
                requirement("new_clue", "新编号", "未知", "潮痕编号A-17"),
            ]
            return scene_plan(requirements, goal="第二场追查档案改动", action="核对被改页")
        if role == "writing":
            return prose()
        if role == "memory_extraction":
            return memory()
        if role in ROLES:
            return reviewer(ROLES[role])
        raise AssertionError(role)


def task_counts(db, scene=SCENE2):
    return db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene,)).fetchone()


# 1. First scene with empty previous_scene_state plans normally.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "first-scene.db"
    adapter = Scene2PlanAdapter([[requirement("new_clue", "灯塔线索", "未知", "发现便条")]])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    assert planning["input"]["scene_number"] == 1
    assert "planning_revision_feedback" not in planning["input"]
    assert "progression_baseline" not in planning["input"]
    assert planning["input"]["context_pack"]["previous_scene_state"] == {}
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert any(call["task_type"] == "writing" for call in adapter.calls)


# 11-13 / 16. gates_16-style rewritten before_states fail at Planning.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gates16.db"
    db, book = seed(path)
    confirm_scene1(db, book)
    db.close()
    adapter = Scene2PlanAdapter([GATES_16_ITEMS, [requirement("new_clue", "新编号", "未知", "潮痕编号A-17")]])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][1]["final_status"] == "reworking_planning"
    assert first["scenes"][1].get("progression_failure_reason") == PLAN_BEFORE_STATE_REASON
    assert first["scenes"][1].get("technical_error") is None
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE2,)).fetchone()[0] == 0
    assert db.execute("select count(*) from exception_queue where task_id=?", (TASK2,)).fetchone()[0] == 0
    versions = [row[0] for row in db.execute(
        "select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE2,))]
    assert versions == [1]
    planning = adapter.calls[0]
    assert planning["prompt_version"] == PLANNING_PROMPT_VERSION
    assert "planning_revision_feedback" not in planning["input"]
    assert set(planning["input"]["progression_baseline"]) == set(PREVIOUS)
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert [row[0] for row in db.execute(
        "select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE2,))] == [1, 2]
    assert adapter.calls[1]["task_type"] == "planning"
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    assert adapter.calls[1]["input"]["progression_baseline"]["unresolved_threads"] == PREVIOUS["unresolved_threads"]
    revision = adapter.calls[1]["input"]["planning_revision_feedback"]
    assert revision["reason"] == PLAN_BEFORE_STATE_REASON
    assert revision["failed_plan_version"] == 1
    assert revision["failed_items"]
    assert {item["progress_type"] for item in revision["failed_items"]} == {
        item["progress_type"] for item in GATES_16_ITEMS
    }
    assert "previous_scene_state" not in revision
    assert "progression_requirements" not in revision
    db.close()


# 14. Resume of a saved rewritten Plan also returns to Planning.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "saved-rewrite.db"
    db, book = seed(path)
    confirm_scene1(db, book)
    save_plan(db, book, book + "_chapter_1", SCENE2, scene_plan(GATES_16_ITEMS), "hc_saved_bad")
    db.commit(); db.close()
    adapter = Scene2PlanAdapter([[requirement("new_clue", "新编号", "未知", "潮痕编号A-17")]])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][1]["final_status"] == "reworking_planning"
    assert first["scenes"][1].get("progression_failure_reason") == PLAN_BEFORE_STATE_REASON
    assert adapter.calls == []
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE2,)).fetchone()[0] == 0
    assert db.execute("select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE2,)).fetchall() == [(1,)]
    db.close()


# 2 / 11. Copied before_state proceeds to Writing.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "copied.db"
    db, book = seed(path)
    confirm_scene1(db, book)
    db.close()
    adapter = Scene2PlanAdapter([[
        requirement("character_state_change", "林照", "林照", "林照开始盘问"),
        requirement("relationship_change", "怀疑", "林照对守灯人产生怀疑", "公开对峙"),
        requirement("thread_advanced", "林澜失踪", "林澜失踪尚未定位", "指向北礁"),
    ]])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    planning = next(call for call in adapter.calls if call["task_type"] == "planning")
    assert "planning_revision_feedback" not in planning["input"]
    assert any(call["task_type"] == "writing" for call in adapter.calls)
    assert result["scenes"][1].get("progression_failure_reason") != PLAN_BEFORE_STATE_REASON


# 15. Old v1 Planning responses cannot be reused.
class TimeoutPlanningAdapter(Scene2PlanAdapter):
    def __init__(self):
        super().__init__([[requirement("new_clue", "灯塔线索", "未知", "发现便条")]])
        self.timed_out = False

    def complete(self, request, timeout_seconds):
        if request["task_type"] == "planning" and not self.timed_out:
            self.calls.append(request)
            self.timed_out = True
            raise TimeoutError("The read operation timed out")
        return super().complete(request, timeout_seconds)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v1-reuse.db"
    first_adapter = TimeoutPlanningAdapter()
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    planning_request = next(call for call in first_adapter.calls if call["task_type"] == "planning")
    planted = dict(planning_request)
    planted["prompt_version"] = "v1"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_planning_v1", SCENE1 + "_task", "planning", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(first_scene_plan(), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = Scene2PlanAdapter([[requirement("new_clue", "灯塔线索", "未知", "发现便条")]])
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    planning_calls = [call for call in second_adapter.calls if call["task_type"] == "planning"]
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert planning_calls
    assert all(call["prompt_version"] == PLANNING_PROMPT_VERSION for call in planning_calls)
    assert "hc_planted_planning_v1" not in (second["scenes"][0].get("reused_calls") or [])


print("plan before_state gate ok")

"""Safe Reviewer task-name to formal-role conversion. No impersonation."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import (ContractFormatError, REVIEWER_PROMPT_VERSION,
    REVIEWER_ROLE_BY_TASK, REVIEWER_ROLE_NORMALIZATION_RULE, normalize_reviewer_role,
    required_fields_validator, validate_reviewer_result_against_input,
    validate_reviewer_result_for_task)
from integration.run_real_test import run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
LONG_PROSE = "林照在档案室停住。管理员挡住门口。夜风穿过窗缝。" + ("档案纸页在灯光下翻动。" * 120)
PLAN_ITEM = {
    "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
    "after_state": "发现线索", "evidence_text": "林照在档案室停住。", "evidence_location": "draft.text",
}
ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}
STATE = {
    "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
    "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"],
}


def plan(number=1):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": [f"第{number}场查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                                      "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索"}],
    }}


def long_prose():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": LONG_PROSE, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, *, item=None, status="achieved", result="passed", findings=None, suggestions=None,
             issue_count=None):
    items = list(findings or [])
    payload = {
        "reviewer_role": role, "result": result, "findings": items,
        "suggestions": list(suggestions or []),
        "issue_count": len(items) if issue_count is None else issue_count,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": STATE,
    }
    if role in ("character_plot", "review_plot"):
        achieved = [copy.deepcopy(item or PLAN_ITEM)] if status in ("achieved", "partially_achieved") else []
        missing = [] if achieved else [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知"}]
        payload["progression_assessment"] = {
            "status": status, "achieved_items": achieved, "missing_items": missing,
        }
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查",
        "evidence": "林照在档案室停住。", "evidence_location": "draft.payload.text",
        "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


def plot_input():
    return {"scene_plan": plan(1), "draft": long_prose()}


class RoleAdapter:
    def __init__(self, *, world="world_consistency", plot="character_plot", style="language_experience",
                 plot_status="achieved", corrected=None, timeout_style=False, timeout_world=False,
                 plot_item=None):
        self.world, self.plot, self.style = world, plot, style
        self.plot_status = plot_status
        self.corrected = corrected
        self.timeout_style = timeout_style
        self.timeout_world = timeout_world
        self.plot_item = plot_item
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return long_prose()
        if role == "memory_extraction":
            return memory()
        if role == "review_world":
            if self.timeout_world:
                raise TimeoutError("The read operation timed out")
            return reviewer(self.world)
        if role == "review_style":
            if self.timeout_style:
                raise TimeoutError("The read operation timed out")
            return reviewer(self.style)
        if role == "review_plot":
            correction = request["input"].get("reviewer_contract_correction")
            if correction and self.corrected is not None:
                return reviewer(self.corrected, item=self.plot_item, status="achieved")
            return reviewer(self.plot, item=self.plot_item, status=self.plot_status)
        return reviewer(ROLES[role])


def expect_contract_invalid(response, task_type):
    normalize_reviewer_role(response, task_type)
    try:
        required_fields_validator(response, "ReviewerResult")
        validate_reviewer_result_for_task(response, task_type)
        if task_type == "review_plot":
            validate_reviewer_result_against_input(response, task_type, plot_input())
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        return error
    raise AssertionError("illegal reviewer role accepted")


def saved_calls(db, agent_type):
    return db.execute(
        "select harness_call_id,status,response_json from harness_calls "
        "where task_id=? and agent_type=? order by started_at",
        (TASK, agent_type)).fetchall()


assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
assert REVIEWER_ROLE_BY_TASK == {
    "review_world": "world_consistency",
    "review_plot": "character_plot",
    "review_style": "language_experience",
}


# 1 / 7. review_world → world_consistency, audit keeps both names.
world = reviewer("review_world")
assert normalize_reviewer_role(world, "review_world") == 1
assert world["payload"]["reviewer_role"] == "world_consistency"
assert world["reviewer_role_normalization_audit"] == {
    "rule": REVIEWER_ROLE_NORMALIZATION_RULE,
    "original_reviewer_role": "review_world",
    "normalized_reviewer_role": "world_consistency",
    "assigned_task_type": "review_world",
}
assert world["reviewer_role_normalization_applied"] is True
assert world["reviewer_role_normalization_count"] == 1
required_fields_validator(world, "ReviewerResult")
validate_reviewer_result_for_task(world, "review_world")
assert normalize_reviewer_role(world, "review_world") == 0
assert world["reviewer_role_normalization_count"] == 1


# 2. review_plot → character_plot.
plot = reviewer("review_plot")
assert normalize_reviewer_role(plot, "review_plot") == 1
assert plot["payload"]["reviewer_role"] == "character_plot"
assert plot["reviewer_role_normalization_audit"]["original_reviewer_role"] == "review_plot"
required_fields_validator(plot, "ReviewerResult")
validate_reviewer_result_for_task(plot, "review_plot")
validate_reviewer_result_against_input(plot, "review_plot", plot_input())


# 3. review_style → language_experience.
style = reviewer("review_style")
assert normalize_reviewer_role(style, "review_style") == 1
assert style["payload"]["reviewer_role"] == "language_experience"
required_fields_validator(style, "ReviewerResult")
validate_reviewer_result_for_task(style, "review_style")


# 4. Already-formal roles are left untouched.
for task, role in REVIEWER_ROLE_BY_TASK.items():
    exact = reviewer(role)
    before = copy.deepcopy(exact)
    assert normalize_reviewer_role(exact, task) == 0
    assert exact == before
    required_fields_validator(exact, "ReviewerResult")
    validate_reviewer_result_for_task(exact, task)


# 5. Assigned-task mismatch stays a Contract error.
for task, foreign in (
    ("review_world", "review_plot"),
    ("review_world", "character_plot"),
    ("review_style", "world_consistency"),
    ("review_style", "review_world"),
    ("review_plot", "review_world"),
    ("review_plot", "language_experience"),
):
    response = reviewer(foreign)
    original = response["payload"]["reviewer_role"]
    expect_contract_invalid(copy.deepcopy(response), task)
    assert normalize_reviewer_role(response, task) == 0
    assert response["payload"]["reviewer_role"] == original


# 6. Unknown and empty roles are rejected and not rewritten.
for role in ("", None, "arbiter", "review_memory", "World_Consistency"):
    response = reviewer("world_consistency")
    response["payload"]["reviewer_role"] = role
    expect_contract_invalid(copy.deepcopy(response), "review_world")
    assert normalize_reviewer_role(response, "review_world") == 0
    assert response["payload"]["reviewer_role"] == role


# 9. Conversion still runs findings/suggestions checks.
soft = reviewer("review_style", suggestions=["可保留档案室气味"])
normalize_reviewer_role(soft, "review_style")
required_fields_validator(soft, "ReviewerResult")
assert soft["payload"]["result"] == "passed"
assert soft["payload"]["issue_count"] == 0
hard = reviewer("review_style", result="failed", findings=["硬伤：专名前后不一致"])
normalize_reviewer_role(hard, "review_style")
required_fields_validator(hard, "ReviewerResult")
illegal = reviewer("review_style", result="passed", findings=["硬伤：专名前后不一致"])
expect_contract_invalid(illegal, "review_style")


# 10. review_plot conversion still requires contiguous draft evidence.
ok_plot = reviewer("review_plot", item=PLAN_ITEM)
normalize_reviewer_role(ok_plot, "review_plot")
validate_reviewer_result_against_input(ok_plot, "review_plot", plot_input())
spliced = reviewer("review_plot", item={**PLAN_ITEM, "evidence_text": "林照在档案室停住。夜风穿过窗缝。"})
expect_contract_invalid(spliced, "review_plot")


# 11. Conversion cannot impersonate another reviewer.
world_as_plot = reviewer("review_plot")
assert normalize_reviewer_role(world_as_plot, "review_world") == 0
assert world_as_plot["payload"]["reviewer_role"] == "review_plot"
expect_contract_invalid(reviewer("review_plot"), "review_world")
expect_contract_invalid(reviewer("character_plot"), "review_world")
expect_contract_invalid(reviewer("world_consistency"), "review_style")


# 14. gates_17-style review_world task name completes the scene.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gates17-world.db"
    adapter = RoleAdapter(world="review_world", plot="review_plot", style="review_style")
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene = result["scenes"][0]
    world_row = saved_calls(db, "review_world")[0]
    saved = json.loads(world_row[2])
    counts = db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where task_id=?",
        (TASK,)).fetchone()
    assert scene["final_status"] == "waiting_confirmation"
    assert scene["reviewer_correction_called"] is False
    assert scene["reviewer_role_normalization_applied"] is True
    assert scene["reviewer_role_normalization_count"] == 1
    assert world_row[1] == "success"
    assert saved["payload"]["reviewer_role"] == "world_consistency"
    assert saved["reviewer_role_normalization_audit"]["original_reviewer_role"] == "review_world"
    assert saved["reviewer_role_normalization_audit"]["normalized_reviewer_role"] == "world_consistency"
    assert json.loads(saved_calls(db, "review_plot")[0][2])["payload"]["reviewer_role"] == "character_plot"
    assert json.loads(saved_calls(db, "review_style")[0][2])["payload"]["reviewer_role"] == "language_experience"
    assert counts == (0, 0, "waiting_confirmation")
    db.close()


# 8. Correction responses use the same mapping.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-role.db"
    adapter = RoleAdapter(plot="character_plot", plot_status="partially_achieved", corrected="review_plot")
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = saved_calls(db, "review_plot")
    corrected = json.loads(rows[1][2])
    assert result["scenes"][0]["reviewer_correction_called"] is True
    assert result["scenes"][0]["reviewer_correction_succeeded"] is True
    assert rows[0][1] == "contract_invalid"
    assert rows[1][1] == "success"
    assert corrected["payload"]["reviewer_role"] == "character_plot"
    assert corrected["reviewer_role_normalization_audit"] == {
        "rule": REVIEWER_ROLE_NORMALIZATION_RULE,
        "original_reviewer_role": "review_plot",
        "normalized_reviewer_role": "character_plot",
        "assigned_task_type": "review_plot",
    }
    assert result["scenes"][0]["reviewer_role_normalization_applied"] is True
    db.close()


# 11. End-to-end impersonation still queues a technical exception.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "impersonate.db"
    adapter = RoleAdapter(world="review_plot")
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert db.execute("select status from harness_calls where agent_type='review_world'").fetchone()[0] == "contract_invalid"
    assert db.execute("select count(*) from quality_reports where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total from task_states where task_id=?",
        (TASK,)).fetchone() == (0, 0)
    db.close()


# 12. Recovery reuses the converted success row and does not restack the audit.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-rerole.db"
    first = RoleAdapter(world="review_world", timeout_style=True)
    first_result = run(db_path=path, adapter=first, execution_mode="sequential")
    db = sqlite3.connect(path)
    first_saved = json.loads(saved_calls(db, "review_world")[0][2])
    first_audit = copy.deepcopy(first_saved["reviewer_role_normalization_audit"])
    assert first_result["scenes"][0]["final_status"] == "exception_pending"
    assert first_saved["payload"]["reviewer_role"] == "world_consistency"
    db.close()
    second = RoleAdapter(world="review_world")
    second_result = run(db_path=path, adapter=second, execution_mode="sequential")
    db = sqlite3.connect(path)
    reused = json.loads(saved_calls(db, "review_world")[0][2])
    assert second_result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert saved_calls(db, "review_world")[0][0] in (second_result["scenes"][0].get("reused_calls") or [])
    assert [call["task_type"] for call in second.calls if call["task_type"] == "review_world"] == []
    assert reused["payload"]["reviewer_role"] == "world_consistency"
    assert reused["reviewer_role_normalization_audit"] == first_audit
    assert reused.get("reviewer_role_normalization_count") == 1
    db.close()


# 13. reviewer_contract_v8 does not reuse a v7 success row.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v7-reuse.db"
    first = RoleAdapter(timeout_world=True)
    run(db_path=path, adapter=first, execution_mode="sequential")
    world_request = next(call for call in first.calls if call["task_type"] == "review_world")
    planted = dict(world_request)
    planted["prompt_version"] = "reviewer_contract_v7"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_reviewer_v7", TASK, "review_world", "mock", "mock",
         json.dumps(planted, ensure_ascii=False),
         json.dumps(reviewer("review_world"), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit()
    db.close()
    second = RoleAdapter(world="review_world")
    result = run(db_path=path, adapter=second, execution_mode="sequential")
    assert "hc_planted_reviewer_v7" not in (result["scenes"][0].get("reused_calls") or [])
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second.calls if call["task_type"].startswith("review_"))
    world_calls = [call for call in second.calls if call["task_type"] == "review_world"]
    assert world_calls


print("reviewer role normalization ok")

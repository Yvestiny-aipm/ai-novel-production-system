"""Safe unwrap of one known ReviewerResult nesting. No business rewrite."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import (ContractFormatError, Harness, ModelProfile, MockAdapter,
    REVIEWER_NORMALIZATION_RULE, REVIEWER_PROMPT_VERSION, normalize_reviewer_result,
    required_fields_validator)
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


def assessment(item=None, status="achieved"):
    achieved = [item or PLAN_ITEM] if status in ("achieved", "partially_achieved") else []
    missing = [] if achieved else [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知"}]
    return {"status": status, "achieved_items": achieved, "missing_items": missing}


def reviewer(role, *, item=None, status="achieved", nest=False, top=None, wrapper=None):
    payload = {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": STATE,
    }
    body = assessment(item, status)
    if nest:
        payload["character_plot"] = {"progression_assessment": wrapper if wrapper is not None else body}
        if top is not None:
            payload["progression_assessment"] = top
    elif role == "character_plot":
        payload["progression_assessment"] = body
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
    return {
        "scene_plan": plan(1),
        "draft": long_prose(),
    }


def open_db(directory):
    path = Path(directory) / "x.db"
    con = sqlite3.connect(path)
    con.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')")
    con.commit(); con.close()
    return path


def run_plot(directory, response):
    harness = Harness(open_db(directory), {"review_plot": ModelProfile("mock", "m")}, {"mock": MockAdapter(response)})
    try:
        return harness.run(task_id="t", agent_task_type="review_plot", input_payload=plot_input(),
                           contract_type="ReviewerResult", contract_validator=required_fields_validator)
    finally:
        harness.close()


class NestedPlotAdapter:
    def __init__(self, *, plot_response=None, timeout_style=False):
        self.plot_response = plot_response
        self.timeout_style = timeout_style
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
        if role == "review_style" and self.timeout_style:
            raise TimeoutError("The read operation timed out")
        if role == "review_plot":
            return self.plot_response or reviewer("character_plot", nest=True)
        return reviewer(ROLES[role])


assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
assert REVIEWER_NORMALIZATION_RULE == "unwrap_character_plot_progression_assessment_v1"


# 1-5 / 13-14. Nested V4 Flash structure unwraps, keeps source, skips correction.
with tempfile.TemporaryDirectory() as directory:
    original = reviewer("character_plot", nest=True)
    nested_before = copy.deepcopy(original["payload"]["character_plot"])
    adapter = NestedPlotAdapter(plot_response=original)
    result = run(db_path=Path(directory) / "unwrap.db", adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(Path(directory) / "unwrap.db")
    row = db.execute(
        "select status,response_json from harness_calls where task_id=? and agent_type='review_plot'",
        (TASK,)).fetchone()
    saved = json.loads(row[1])
    scene = result["scenes"][0]
    assert scene["final_status"] == "waiting_confirmation"
    assert scene["reviewer_normalization_applied"] is True
    assert scene["reviewer_normalization_rule"] == REVIEWER_NORMALIZATION_RULE
    assert scene["reviewer_correction_called"] is False
    assert [call["task_type"] for call in adapter.calls].count("review_plot") == 1
    assert row[0] == "success"
    assert saved["payload"]["character_plot"] == nested_before
    assert saved["payload"]["progression_assessment"] == nested_before["progression_assessment"]
    assert saved["contract_normalization_audit"] == {
        "rule": REVIEWER_NORMALIZATION_RULE,
        "source_path": "payload.character_plot.progression_assessment",
        "destination_path": "payload.progression_assessment",
    }
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total,technical_retry_count from task_states where task_id=?",
        (TASK,)).fetchone() == (0, 0, 0)
    db.close()


# 6. Top-level and nested conflict stays contract_invalid.
with tempfile.TemporaryDirectory() as directory:
    conflict = reviewer("character_plot", nest=True, top=assessment(status="not_achieved"))
    try:
        run_plot(directory, conflict)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        assert "conflict" in str(error)
    else:
        raise AssertionError("conflicting assessments accepted")


# 7. Nested non-object is contract_invalid and is not rewritten.
with tempfile.TemporaryDirectory() as directory:
    bad = reviewer("character_plot", nest=True, wrapper="not-an-object")
    try:
        run_plot(directory, bad)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
    else:
        raise AssertionError("non-object nested assessment accepted")
    assert bad["payload"]["character_plot"]["progression_assessment"] == "not-an-object"
    assert "progression_assessment" not in bad["payload"] or not isinstance(bad["payload"].get("progression_assessment"), dict)


# 8. Non-character_plot is not unwrapped.
world = reviewer("world_consistency")
world["payload"]["character_plot"] = {"progression_assessment": assessment()}
assert normalize_reviewer_result(world, "review_world") is False
assert "progression_assessment" not in world["payload"]
assert "contract_normalization_audit" not in world


# 9. Illegal status is not rewritten to a legal value.
with tempfile.TemporaryDirectory() as directory:
    illegal = reviewer("character_plot", nest=True, status="partially_achieved")
    try:
        run_plot(directory, illegal)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
    else:
        raise AssertionError("partially_achieved accepted after unwrap")
    assert illegal["payload"]["character_plot"]["progression_assessment"]["status"] == "partially_achieved"
    assert illegal["payload"]["progression_assessment"]["status"] == "partially_achieved"
    assert illegal["payload"]["progression_assessment"]["status"] != "achieved"


# 10. Missing achieved fields are not filled in.
with tempfile.TemporaryDirectory() as directory:
    incomplete = reviewer("character_plot", nest=True, item={"progress_type": "new_clue", "target_key": "灯塔线索"})
    try:
        run_plot(directory, incomplete)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
    else:
        raise AssertionError("incomplete achieved item accepted")
    assert "before_state" not in incomplete["payload"]["character_plot"]["progression_assessment"]["achieved_items"][0]
    assert "before_state" not in incomplete["payload"]["progression_assessment"]["achieved_items"][0]


# 11. Evidence still must be a contiguous draft substring.
with tempfile.TemporaryDirectory() as directory:
    spliced = reviewer("character_plot", nest=True, item={**PLAN_ITEM, "evidence_text": "林照在档案室停住。夜风穿过窗缝。"})
    try:
        run_plot(directory, spliced)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        assert "contiguous" in str(error)
    else:
        raise AssertionError("spliced evidence accepted after unwrap")


# 12. Invented type/key still fails.
with tempfile.TemporaryDirectory() as directory:
    invented = reviewer("character_plot", nest=True, item={**PLAN_ITEM, "target_key": "另一条线索"})
    try:
        run_plot(directory, invented)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
    else:
        raise AssertionError("invented target_key accepted after unwrap")


# 15. Recovery does not stack a second normalization.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-double.db"
    first = NestedPlotAdapter(timeout_style=True)
    first_result = run(db_path=path, adapter=first, execution_mode="sequential")
    db = sqlite3.connect(path)
    saved = json.loads(db.execute(
        "select response_json from harness_calls where task_id=? and agent_type='review_plot' and status='success'",
        (TASK,)).fetchone()[0])
    nested_before = copy.deepcopy(saved["payload"]["character_plot"])
    audit_before = copy.deepcopy(saved["contract_normalization_audit"])
    assert first_result["scenes"][0]["reviewer_normalization_applied"] is True
    assert normalize_reviewer_result(saved, "review_plot") is False
    assert saved["payload"]["character_plot"] == nested_before
    assert saved["contract_normalization_audit"] == audit_before
    assert not isinstance(saved["contract_normalization_audit"], list)
    plot_id = db.execute(
        "select harness_call_id from harness_calls where task_id=? and agent_type='review_plot' and status='success'",
        (TASK,)).fetchone()[0]
    db.close()
    second = NestedPlotAdapter()
    second_result = run(db_path=path, adapter=second, execution_mode="sequential")
    db = sqlite3.connect(path)
    reused = json.loads(db.execute(
        "select response_json from harness_calls where harness_call_id=?", (plot_id,)).fetchone()[0])
    assert plot_id in (second_result["scenes"][0].get("reused_calls") or [])
    assert reused["contract_normalization_audit"] == audit_before
    assert reused["payload"]["character_plot"] == nested_before
    assert not any(call["task_type"] == "review_plot" for call in second.calls)
    db.close()


# 16. reviewer_contract_v4 success rows are not reused after the v5 upgrade.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v4-reuse.db"
    first = NestedPlotAdapter(timeout_style=True)
    run(db_path=path, adapter=first, execution_mode="sequential")
    plot_request = next(call for call in first.calls if call["task_type"] == "review_plot")
    planted = dict(plot_request)
    planted["prompt_version"] = "reviewer_contract_v4"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_reviewer_v4", TASK, "review_plot", "mock", "mock",
         json.dumps(planted, ensure_ascii=False),
         json.dumps(reviewer("character_plot"), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second = NestedPlotAdapter()
    result = run(db_path=path, adapter=second, execution_mode="sequential")
    assert "hc_planted_reviewer_v4" not in (result["scenes"][0].get("reused_calls") or [])
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second.calls if call["task_type"] == "review_plot")

print("reviewer normalization ok")

"""Real routing retries a technical failure once inside the same harness call."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import words

from backend.harness import Harness, ModelProfile, required_fields_validator
from backend.model_routing import build_harness_setup
from backend.siliconflow import ModelResponseParseError
from integration.recovery import run_recovery
from integration.run_real_test import TYPES


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
ROLES = {
    "review_world": "world_consistency",
    "review_plot": "character_plot",
    "review_style": "language_experience",
}


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": [f"第{number}场查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                                      "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索"}],
    }}


def prose(size=1100):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": words(size), "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role):
    payload = {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
    }
    if role == "character_plot":
        payload["progression_assessment"] = {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": "word", "evidence_location": "draft.text",
        }], "missing_items": []}
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "word",
        "evidence_location": "draft.payload.text", "change_reason": "审查通过",
        "conflict_status": "none", "write_policy": "human_confirmation", "status": "pending",
    }}


def json_invalid():
    return ModelResponseParseError(
        "MODEL_RESPONSE_JSON_INVALID: Expecting ',' delimiter",
        error_code="MODEL_RESPONSE_JSON_INVALID",
        content='{"contract_type":"ReviewerResult" "payload":{}}',
        finish_reason="end_turn",
        parse_error="Expecting ',' delimiter",
    )


class PlotJsonAdapter:
    def __init__(self, *, plot_failures):
        self.plot_failures = plot_failures
        self.plot_attempts = 0
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request["task_type"])
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose()
        if role == "memory_extraction":
            return memory()
        if role == "review_plot":
            self.plot_attempts += 1
            if self.plot_attempts <= self.plot_failures:
                raise json_invalid()
            return reviewer(ROLES[role])
        return reviewer(ROLES[role])


class QueueReviewAdapter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request["task_type"])
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def open_db(directory):
    path = Path(directory) / "x.db"
    con = sqlite3.connect(path)
    con.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute(
        "INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,"
        "active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) "
        "VALUES ('t','book','b','reviewing','running','review','[]','[]','k','2026','2026')"
    )
    con.commit()
    con.close()
    return path


real_routes, _ = build_harness_setup(TYPES, {}, siliconflow_adapter=object())
assert {profile.technical_retries for profile in real_routes.values()} == {1}
mock_routes, _ = build_harness_setup(TYPES, {}, mock=True, siliconflow_adapter=object())
assert {profile.technical_retries for profile in mock_routes.values()} == {0}


# 1. First JSON invalid, second success: one harness success row, two adapter shots.
with tempfile.TemporaryDirectory() as directory:
    path = open_db(directory)
    adapter = QueueReviewAdapter([json_invalid(), reviewer("character_plot")])
    harness = Harness(path, {"review_plot": ModelProfile("mock", "m", technical_retries=1)}, {"mock": adapter})
    result = harness.run(
        task_id="t", agent_task_type="review_plot",
        input_payload={
            "scene_plan": {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
                "progression_requirements": [{
                    "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                    "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索",
                }],
            }},
            "draft": {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {"text": "word"}},
        },
        contract_type="ReviewerResult", contract_validator=required_fields_validator,
    )
    rows = list(harness.db.execute(
        "select status, error_json from harness_calls where task_id='t' and agent_type='review_plot'"
    ))
    harness.close()
    assert result["response"]["payload"]["reviewer_role"] == "character_plot"
    assert adapter.calls == ["review_plot", "review_plot"]
    assert len(rows) == 1
    assert rows[0][0] == "success"
    assert rows[0][1] is None


# 2. Both shots fail: still a technical exception, not a content failure or invented review.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "both-fail.db"
    adapter = PlotJsonAdapter(plot_failures=2)
    result = run_recovery(
        path, adapter, "sequential", mock=False,
        model_environ={"REAL_TEST_SCENE_COUNT": "1"},
    )
    db = sqlite3.connect(path)
    queued = list(db.execute(
        "select source_node,error_code,status from exception_queue where task_id=?", (TASK,)
    ))
    calls = list(db.execute(
        "select status,error_json from harness_calls where task_id=? and agent_type='review_plot'",
        (TASK,),
    ))
    drafts = db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0]
    reports = db.execute("select count(*) from quality_reports where scene_id=?", (SCENE,)).fetchone()[0]
    task = db.execute("select status,current_node from task_states where task_id=?", (TASK,)).fetchone()
    db.close()
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert task == ("exception_pending", "exception_handling")
    assert queued == [("reviewing", "MODEL_RESPONSE_JSON_INVALID", "pending")]
    assert len(calls) == 1
    assert calls[0][0] == "failed"
    audit = json.loads(calls[0][1])
    assert audit["error_code"] == "MODEL_RESPONSE_JSON_INVALID"
    assert adapter.plot_attempts == 2
    assert adapter.calls.count("review_plot") == 2
    assert "review_style" not in adapter.calls
    assert drafts == 1
    assert reports == 0


print("technical retry ok")

"""ModelProfile routing must drive the request, API body, and recovery reuse."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import words

from backend.harness import Harness, ModelProfile, MockAdapter, required_fields_validator
from backend.siliconflow import DEFAULT_SILICONFLOW_MODEL, TimeoutConfigError, build_request_body
from integration.run_real_test import run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}


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


class RecordingAdapter:
    def __init__(self, *, timeout_plot=False):
        self.timeout_plot = timeout_plot
        self.calls = []
        self.timeouts = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        self.timeouts.append((request["task_type"], timeout_seconds))
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose()
        if role == "memory_extraction":
            return memory()
        if role == "review_plot" and self.timeout_plot:
            raise TimeoutError("The read operation timed out")
        return reviewer(ROLES[role])


def models_for(adapter, task_type):
    return [call["model"] for call in adapter.calls if call["task_type"] == task_type]


# 1 / 3 / 12. Harness request.model is persisted and never contains the API key.
with tempfile.TemporaryDirectory() as directory:
    db = Path(directory) / "harness-model.db"
    con = sqlite3.connect(db)
    con.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')")
    con.commit(); con.close()
    adapter = MockAdapter(plan(1))
    harness = Harness(db, {"planning": ModelProfile("mock", "vendor/planning")}, {"mock": adapter})
    result = harness.run(task_id="t", agent_task_type="planning", input_payload={"x": 1},
                         contract_type="ScenePlan", contract_validator=required_fields_validator)
    row = harness.db.execute(
        "select model,request_json from harness_calls where harness_call_id=?",
        (result["harness_call_id"],)).fetchone()
    request = json.loads(row[1])
    body = build_request_body(request, default_model="adapter-default")
    assert request["model"] == "vendor/planning"
    assert request["timeout_seconds"] == 60
    assert row[0] == "vendor/planning" == body["model"]
    assert "api_key" not in request
    assert "SILICONFLOW_API_KEY" not in row[1]
    assert "sk-" not in row[1]
    harness.close()


# 4 / 5 / 7. Writing and Reviewer can differ; three reviewers share REVIEW_MODEL.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "split-models.db"
    adapter = RecordingAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential", model_environ={
        "SILICONFLOW_WRITING_MODEL": "vendor/writing",
        "SILICONFLOW_REVIEW_MODEL": "vendor/review",
    })
    db = sqlite3.connect(path)
    rows = db.execute(
        "select agent_type,model,request_json from harness_calls where task_id=? order by started_at",
        (TASK,)).fetchall()
    by_role = {row[0]: (row[1], json.loads(row[2])["model"]) for row in rows}
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert by_role["writing"] == ("vendor/writing", "vendor/writing")
    assert by_role["planning"] == ("mock", "mock")
    for role in ("review_world", "review_plot", "review_style"):
        assert by_role[role] == ("vendor/review", "vendor/review")
        body = build_request_body(json.loads(next(row[2] for row in rows if row[0] == role)))
        assert body["model"] == "vendor/review"
    assert models_for(adapter, "writing") == ["vendor/writing"]
    assert models_for(adapter, "review_world") == ["vendor/review"]
    assert "sk-" not in "".join(row[2] for row in rows)
    db.close()


# 8 / 9. Switching Reviewer model must not reuse an old success with the same prompt.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "switch-reviewer.db"
    first_adapter = RecordingAdapter(timeout_plot=True)
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential", model_environ={
        "SILICONFLOW_REVIEW_MODEL": "deepseek-ai/DeepSeek-V3",
    })
    db = sqlite3.connect(path)
    old_world = db.execute(
        "select harness_call_id,model,status from harness_calls where task_id=? and agent_type='review_world'",
        (TASK,)).fetchone()
    plans = db.execute("select count(*) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0]
    drafts = db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0]
    content = db.execute(
        "select content_attempt_in_plan,content_attempt_total from task_states where task_id=?",
        (TASK,)).fetchone()
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert old_world[1:] == (DEFAULT_SILICONFLOW_MODEL, "success")
    assert plans == 1 and drafts == 1
    db.close()
    second_adapter = RecordingAdapter()
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential", model_environ={
        "SILICONFLOW_REVIEW_MODEL": "vendor/new-reviewer",
    })
    db = sqlite3.connect(path)
    world_rows = db.execute(
        "select harness_call_id,model,status from harness_calls where task_id=? and agent_type='review_world' order by started_at",
        (TASK,)).fetchall()
    writing_calls = [call for call in second_adapter.calls if call["task_type"] == "writing"]
    planning_calls = [call for call in second_adapter.calls if call["task_type"] == "planning"]
    assert second["scenes"][0]["final_status"] == "waiting_confirmation"
    assert old_world[0] not in (second["scenes"][0].get("reused_calls") or [])
    assert [row[1] for row in world_rows] == [DEFAULT_SILICONFLOW_MODEL, "vendor/new-reviewer"]
    assert world_rows[0][0] != world_rows[1][0]
    assert world_rows[0][2] == "success"
    assert not planning_calls
    assert not writing_calls
    assert db.execute("select count(*) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total from task_states where task_id=?",
        (TASK,)).fetchone() == content
    assert all(call["model"] == "vendor/new-reviewer"
               for call in second_adapter.calls if call["task_type"].startswith("review_"))
    db.close()


# 10. Same model and other conditions still reuse.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "same-model-reuse.db"
    first_adapter = RecordingAdapter(timeout_plot=True)
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential", model_environ={
        "SILICONFLOW_REVIEW_MODEL": "vendor/review",
    })
    db = sqlite3.connect(path)
    old_world = db.execute(
        "select harness_call_id from harness_calls where task_id=? and agent_type='review_world' and status='success'",
        (TASK,)).fetchone()[0]
    db.close()
    second_adapter = RecordingAdapter()
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential", model_environ={
        "SILICONFLOW_REVIEW_MODEL": "vendor/review",
    })
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert second["scenes"][0]["final_status"] == "waiting_confirmation"
    assert old_world in (second["scenes"][0].get("reused_calls") or [])
    assert not any(call["task_type"] == "review_world" for call in second_adapter.calls)


# Timeout: default 60, STRUCTURED covers reviewers, WRITING ignores STRUCTURED, REVIEW overrides.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout-routing.db"
    adapter = RecordingAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential", timeout_environ={
        "SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS": "180",
        "SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "90",
        "SILICONFLOW_WRITING_TIMEOUT_SECONDS": "240",
    })
    db = sqlite3.connect(path)
    rows = db.execute(
        "select agent_type,request_json from harness_calls where task_id=? order by started_at",
        (TASK,)).fetchall()
    timeouts = {row[0]: json.loads(row[1])["timeout_seconds"] for row in rows}
    received = {role: value for role, value in adapter.timeouts}
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert timeouts["planning"] == 180 == received["planning"]
    assert timeouts["writing"] == 240 == received["writing"]
    assert timeouts["review_world"] == 90 == received["review_world"]
    assert timeouts["review_plot"] == 90 == received["review_plot"]
    assert timeouts["review_style"] == 90 == received["review_style"]
    assert timeouts["memory_extraction"] == 180 == received["memory_extraction"]
    assert all("api_key" not in json.loads(row[1]) for row in rows)
    db.close()


# Unconfigured timeout stays 60; invalid timeout fails before any call.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout-default.db"
    adapter = RecordingAdapter()
    run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert {value for _, value in adapter.timeouts} == {60}
    assert {call["timeout_seconds"] for call in adapter.calls} == {60}

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout-invalid.db"
    try:
        run(db_path=path, adapter=RecordingAdapter(), execution_mode="sequential",
            timeout_environ={"SILICONFLOW_WRITING_TIMEOUT_SECONDS": "0"})
    except TimeoutConfigError:
        pass
    else:
        raise AssertionError("invalid timeout was accepted")


# Model switch and timeout switch do not interfere.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout-change-same-model.db"
    first = RecordingAdapter(timeout_plot=True)
    run(db_path=path, adapter=first, execution_mode="sequential",
        model_environ={"SILICONFLOW_REVIEW_MODEL": "vendor/review"},
        timeout_environ={"SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "90"})
    db = sqlite3.connect(path)
    old_world = db.execute(
        "select harness_call_id,model from harness_calls where task_id=? and agent_type='review_world' and status='success'",
        (TASK,)).fetchone()
    db.close()
    second = RecordingAdapter()
    result = run(db_path=path, adapter=second, execution_mode="sequential",
                 model_environ={"SILICONFLOW_REVIEW_MODEL": "vendor/review"},
                 timeout_environ={"SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "180"})
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert old_world[0] in (result["scenes"][0].get("reused_calls") or [])
    assert old_world[1] == "vendor/review"
    assert not any(call["task_type"] == "review_world" for call in second.calls)

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "model-change-same-timeout.db"
    first = RecordingAdapter(timeout_plot=True)
    run(db_path=path, adapter=first, execution_mode="sequential",
        model_environ={"SILICONFLOW_REVIEW_MODEL": "vendor/review"},
        timeout_environ={"SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "180"})
    db = sqlite3.connect(path)
    old_world = db.execute(
        "select harness_call_id from harness_calls where task_id=? and agent_type='review_world' and status='success'",
        (TASK,)).fetchone()[0]
    db.close()
    second = RecordingAdapter()
    switched = run(db_path=path, adapter=second, execution_mode="sequential",
                   model_environ={"SILICONFLOW_REVIEW_MODEL": "vendor/other"},
                   timeout_environ={"SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "180"})
    assert old_world not in (switched["scenes"][0].get("reused_calls") or [])
    assert all(call["model"] == "vendor/other" and call["timeout_seconds"] == 180
               for call in second.calls if call["task_type"].startswith("review_"))

print("model routing ok")

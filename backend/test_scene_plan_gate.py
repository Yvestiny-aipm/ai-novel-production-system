from harness import required_fields_validator, ContractFormatError
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import PLANNING_PROMPT_VERSION, classify_scene_plan_quality
from backend.siliconflow import ModelResponseParseError, contract_system_prompt, planning_progression_instruction
from integration.recovery import reclassify_orphaned_planning_exception
from integration.run_real_test import run, save_plan
from integration.seed_real_test import seed


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
base={'scene_goal':'goal','entrance_state':{'x':1},'exit_state':{'x':2},'characters':['林照'],'location':'灯塔','time_context':'夜晚','conflict':'调查','action_beats':['进入'],'must_happen':['发现'],'must_not_happen':['解决'],'knowledge_boundary':'已知','target_word_count':1250,'acceptance_criteria':['有效'],'validation_result':{'ok':True},'ready_for_writing':True,'progression_requirements':[{'progress_type':'new_clue','target_key':'灯塔线索','before_state':'未知','expected_after_state':'获得线索','acceptance_criterion':'正文出现新线索'}]}
required_fields_validator({'contract_type':'ScenePlan','contract_version':'v1','payload':base},'ScenePlan')
for update in ({'target_word_count':0},{'target_word_count':2000},{'target_word_count':1000},{'target_word_count':1500},{'ready_for_writing':False},{'scene_goal':''}):
    bad=dict(base); bad.update(update)
    try: required_fields_validator({'contract_type':'ScenePlan','contract_version':'v1','payload':bad},'ScenePlan')
    except ContractFormatError as exc: assert exc.code=='CONTRACT_PAYLOAD_INVALID'
    else: raise AssertionError(update)
prompt = contract_system_prompt('ScenePlan')
assert 'exactly 1250' in prompt or 'MUST be exactly 1250' in prompt
assert '2000' in prompt and '1000' in prompt and '1500' in prompt
assert 'progression_baseline' in prompt
assert 'payload top level' in prompt
assert PLANNING_PROMPT_VERSION == 'planning_progression_v4'
assert '顶层独立出现' in planning_progression_instruction()
for field in ('characters', 'location', 'time_context'):
    payload = dict(base)
    del payload[field]
    classified = classify_scene_plan_quality({'contract_type': 'ScenePlan', 'contract_version': 'v1', 'payload': payload})
    assert classified['reason'] == 'plan_required_fields_missing'
    assert classified['missing_fields'] == [field]
nested_payload = dict(base)
nested = {key: nested_payload.pop(key) for key in ('characters', 'location', 'time_context')}
nested_payload['entrance_state'] = {**nested_payload['entrance_state'], **nested}
classified = classify_scene_plan_quality({'contract_type': 'ScenePlan', 'contract_version': 'v1', 'payload': nested_payload})
assert classified['reason'] == 'plan_required_fields_missing'
assert classified['missing_fields'] == ['characters', 'location', 'time_context']
assert classify_scene_plan_quality({'contract_type': 'ScenePlan', 'contract_version': 'v1', 'payload': 'x'}) is None


def plan(number, target=1250):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": [f"第{number}场查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": target,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                                      "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索"}],
    }}


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
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": "潮", "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": "潮"},
    }}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
        "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


class TargetAdapter:
    def __init__(self, targets):
        self.targets, self.calls = list(targets), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            target = self.targets.pop(0) if self.targets else 1250
            return plan(number, target)
        if role == "writing":
            return prose()
        if role == "memory_extraction":
            return memory()
        if role in ROLES:
            return reviewer(ROLES[role])
        raise AssertionError(f"unexpected role {role}")


def task_counts(db):
    return db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where task_id=?",
        (TASK,)).fetchone()


# 4 / 5. target=2000 is a planning-quality failure: keep v1, rework to v2, no Writing.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "target-2000.db"
    adapter = TargetAdapter([2000, 1250])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "reworking_planning"
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    versions = [row[0] for row in db.execute("select plan_version, payload_json from scene_plans where scene_id=? order by plan_version", (SCENE,))]
    assert versions == [1]
    assert '"target_word_count": 2000' in db.execute("select payload_json from scene_plans where scene_id=? and plan_version=1", (SCENE,)).fetchone()[0]
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = db.execute("select plan_version, payload_json from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall()
    assert [row[0] for row in rows] == [1, 2]
    assert '"target_word_count": 2000' in rows[0][1]
    assert '"target_word_count": 1250' in rows[1][1]
    assert [call["task_type"] for call in adapter.calls].count("planning") == 2
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    assert "planning_revision_feedback" not in adapter.calls[0]["input"]
    revision = adapter.calls[1]["input"]["planning_revision_feedback"]
    assert revision["reason"] == "plan_target_word_count_invalid"
    assert revision["failed_plan_version"] == 1
    assert revision["failed_items"] == []
    db.close()


# 3 / 4. 1000 and 1500 are also illegal official targets.
for illegal in (1000, 1500):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"target-{illegal}.db"
        adapter = TargetAdapter([illegal])
        result = run(db_path=path, adapter=adapter, execution_mode="sequential")
        assert result["scenes"][0]["final_status"] == "reworking_planning"
        assert "writing" not in [call["task_type"] for call in adapter.calls]


# 6. Resume of a saved illegal Plan v1 reworks planning and does not call Writing.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "saved-illegal.db"
    db, book = seed(path)
    save_plan(db, book, book + "_chapter_1", SCENE, plan(1, 2000), "hc_saved_illegal")
    db.commit(); db.close()
    adapter = TargetAdapter([1250])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "reworking_planning"
    assert first["scenes"][0].get("technical_error") is None
    assert [call["task_type"] for call in adapter.calls] == []
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert db.execute("select count(*) from exception_queue where task_id=?", (TASK,)).fetchone()[0] == 0
    assert task_counts(db)[:4] == (1, 0, 0, "reworking_planning")
    assert db.execute("select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall() == [(1,)]
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = db.execute("select plan_version, payload_json from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall()
    assert [row[0] for row in rows] == [1, 2]
    assert '"target_word_count": 2000' in rows[0][1]
    assert '"target_word_count": 1250' in rows[1][1]
    assert adapter.calls[0]["task_type"] == "planning"
    assert adapter.calls[0]["input"]["checkpoint"]["plan_version"] == 2
    db.close()


class PlanOnlyAdapter:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        if role == "planning":
            return self.responses.pop(0) if self.responses else plan(1)
        if role == "writing":
            return prose()
        if role == "memory_extraction":
            return memory()
        if role in ROLES:
            return reviewer(ROLES[role])
        raise AssertionError(role)


class NoCallAdapter:
    def complete(self, request, timeout_seconds):
        raise AssertionError(f"unexpected model call {request['task_type']}")


class ParseErrorAdapter:
    def __init__(self):
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        raise ModelResponseParseError("MODEL_RESPONSE_JSON_INVALID: Expecting value", content="not-json {")


def drop_fields(payload, *fields):
    out = dict(payload)
    for field in fields:
        out.pop(field, None)
    return out


def incomplete_plan(*fields):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": drop_fields(plan(1)["payload"], *fields)}


def nested_only_plan(*, into="entrance_state"):
    payload = dict(plan(1)["payload"])
    nested = {key: payload.pop(key) for key in ("characters", "location", "time_context")}
    payload[into] = {**payload[into], **nested}
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": payload}


def empty_plan(field, value):
    payload = dict(plan(1)["payload"])
    payload[field] = value
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": payload}


def assert_planning_rework(result, adapter, db, *, reason, missing=None, empty=None):
    scene = result["scenes"][0]
    assert scene["final_status"] == "reworking_planning"
    assert scene.get("technical_error") is None
    assert scene.get("planning_failure_reason") == reason
    if missing is not None:
        assert scene.get("missing_fields") == missing
    if empty is not None:
        assert scene.get("empty_fields") == empty
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert db.execute("select count(*) from exception_queue where task_id=? and status in ('pending','handling')", (TASK,)).fetchone()[0] == 0
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    saved = json.loads(db.execute("select payload_json from scene_plans where scene_id=? and plan_version=1", (SCENE,)).fetchone()[0])
    if missing:
        for field in missing:
            assert field not in saved


# 1-3. Missing top-level characters / location / time_context return to Planning.
for field in ("characters", "location", "time_context"):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"missing-{field}.db"
        adapter = PlanOnlyAdapter([incomplete_plan(field)])
        result = run(db_path=path, adapter=adapter, execution_mode="sequential")
        db = sqlite3.connect(path)
        assert_planning_rework(result, adapter, db, reason="plan_required_fields_missing", missing=[field])
        db.close()


# 4. Missing all three records the complete missing_fields list.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "missing-three.db"
    adapter = PlanOnlyAdapter([incomplete_plan("characters", "location", "time_context")])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_rework(result, adapter, db, reason="plan_required_fields_missing",
                           missing=["characters", "location", "time_context"])
    db.close()


# 5 / 6. Nested-only fields still count as missing; never copy from entrance/exit.
for into in ("entrance_state", "exit_state"):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"nested-{into}.db"
        nested = nested_only_plan(into=into)
        adapter = PlanOnlyAdapter([nested])
        result = run(db_path=path, adapter=adapter, execution_mode="sequential")
        db = sqlite3.connect(path)
        assert_planning_rework(result, adapter, db, reason="plan_required_fields_missing",
                               missing=["characters", "location", "time_context"])
        saved = json.loads(db.execute("select payload_json from scene_plans where scene_id=? and plan_version=1", (SCENE,)).fetchone()[0])
        assert "characters" not in saved and "location" not in saved and "time_context" not in saved
        assert saved[into]["characters"] == ["林照"]
        db.close()


# 7. Empty required fields return to Planning.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "empty-characters.db"
    adapter = PlanOnlyAdapter([empty_plan("characters", [])])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_rework(result, adapter, db, reason="plan_required_fields_empty", empty=["characters"])
    db.close()


# 8. ready_for_writing=false returns to Planning.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "not-ready.db"
    adapter = PlanOnlyAdapter([empty_plan("ready_for_writing", False)])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_rework(result, adapter, db, reason="plan_not_ready")
    db.close()


# 9. Unparseable JSON remains a technical exception.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "parse-error.db"
    adapter = ParseErrorAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert result["scenes"][0].get("planning_failure_reason") is None
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert db.execute("select count(*) from exception_queue where task_id=? and status='pending'", (TASK,)).fetchone()[0] == 1
    assert task_counts(db)[:3] == (1, 0, 0)
    db.close()


# 10. A non-object payload remains a technical exception.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "payload-not-object.db"
    adapter = PlanOnlyAdapter([{"contract_type": "ScenePlan", "contract_version": "v1", "payload": "not-an-object"}])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert result["scenes"][0].get("planning_failure_reason") is None
    assert db.execute("select count(*) from exception_queue where task_id=? and status='pending'", (TASK,)).fetchone()[0] == 1
    assert task_counts(db)[:3] == (1, 0, 0)
    db.close()


# 11 / 12 / 13. Planning-quality failure does not call Writing, does not increment
# content attempts, increments plan_version on the next run, and keeps the failed response.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "plan-v2-after-missing.db"
    adapter = PlanOnlyAdapter([incomplete_plan("characters"), plan(1)])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_rework(first, adapter, db, reason="plan_required_fields_missing", missing=["characters"])
    invalid_calls = db.execute(
        "select harness_call_id,status,response_json from harness_calls where task_id=? and status='contract_invalid'",
        (TASK,)).fetchall()
    assert len(invalid_calls) == 1
    assert "characters" not in json.loads(invalid_calls[0][2])["payload"]
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = db.execute("select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall()
    assert [row[0] for row in rows] == [1, 2]
    assert db.execute("select count(*) from harness_calls where task_id=? and status='contract_invalid'", (TASK,)).fetchone()[0] == 1
    assert [call["task_type"] for call in adapter.calls].count("planning") == 2
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    revision = adapter.calls[1]["input"]["planning_revision_feedback"]
    assert revision["reason"] == "plan_required_fields_missing"
    assert revision["failed_plan_version"] == 1
    assert task_counts(db)[:3] == (1, 0, 0)
    db.close()


# 14 / 15 / 16. gates_18-style exception_pending reclassifies without a model call.
SCENE3 = "realtest_tide_archive_scene_3"
TASK3 = SCENE3 + "_task"
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gates18-reclassify.db"
    db, book = seed(path)
    chapter = book + "_chapter_1"
    nested = nested_only_plan(into="entrance_state")
    nested["payload"]["exit_state"] = {
        **nested["payload"]["exit_state"],
        "characters": ["林照"], "location": "灯塔出口", "time_context": "黎明",
    }
    request = {
        "task_type": "planning", "contract_type": "ScenePlan", "contract_version": "v1",
        "prompt_version": "planning_progression_v2", "model": "mock",
        "input": {"checkpoint": {"book_id": book, "chapter_id": chapter, "scene_id": SCENE3, "plan_version": 1,
                                 "draft_version": 0, "context_pack_version": 0}},
        "checkpoint": {"book_id": book, "chapter_id": chapter, "scene_id": SCENE3, "plan_version": 1},
    }
    error = {"error": "CONTRACT_PAYLOAD_INVALID", "reason": "missing payload fields: characters,location,time_context"}
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,error_json,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?,?)",
        ("hc_gates18_s3", TASK3, "planning", "mock", "mock", json.dumps(request, ensure_ascii=False),
         json.dumps(nested, ensure_ascii=False), "contract_invalid", json.dumps(error, ensure_ascii=False), "2026", "2026"))
    db.execute(
        "insert into exception_queue(exception_id,task_id,source_node,error_code,error_message,details_json,status,retry_count,created_at) values (?,?,?,?,?,?,?,?,?)",
        ("ex_gates18_s3", TASK3, "planning", "CONTRACT_PAYLOAD_INVALID",
         "missing payload fields: characters,location,time_context",
         json.dumps({"harness_call_id": "hc_gates18_s3"}), "pending", 0, "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing',next_action='none' where task_id in (?,?)",
               (book + "_scene_1_task", book + "_scene_2_task"))
    db.execute("update task_states set status='exception_pending',current_node='exception_handling',next_action='handle_exception',exception_id=? where task_id=?",
               ("ex_gates18_s3", TASK3))
    db.commit(); db.close()
    first = run(db_path=path, adapter=NoCallAdapter(), execution_mode="sequential")
    scene3 = first["scenes"][2]
    assert scene3["planning_exception_reclassified"] is True
    assert scene3["final_status"] == "reworking_planning"
    assert scene3.get("planning_failure_reason") == "plan_required_fields_missing"
    assert scene3.get("missing_fields") == ["characters", "location", "time_context"]
    db = sqlite3.connect(path)
    assert db.execute("select status from harness_calls where harness_call_id='hc_gates18_s3'").fetchone()[0] == "contract_invalid"
    assert db.execute("select status from exception_queue where exception_id='ex_gates18_s3'").fetchone()[0] == "resolved"
    event = db.execute("select payload_json from task_events where task_id=? and event_type='planning_exception_reclassified'", (TASK3,)).fetchone()
    assert event
    assert json.loads(event[0])["missing_fields"] == ["characters", "location", "time_context"]
    assert db.execute("select count(*) from task_events where task_id=? and event_type='technical_retry_started'", (TASK3,)).fetchone()[0] == 0
    counts = db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,technical_retry_count,status from task_states where task_id=?", (TASK3,)).fetchone()
    assert counts == (1, 0, 0, 0, "reworking_planning")
    saved = json.loads(db.execute("select payload_json from scene_plans where scene_id=? and plan_version=1", (SCENE3,)).fetchone()[0])
    assert "characters" not in saved and saved["entrance_state"]["location"] == "灯塔档案室"
    assert saved["exit_state"]["location"] == "灯塔出口"
    db.close()


# 17. planning_progression_v4 must not reuse a v2 success response.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v2-reuse.db"
    db, book = seed(path)
    planted = {
        "task_type": "planning", "contract_type": "ScenePlan", "contract_version": "v1",
        "prompt_version": "planning_progression_v2", "model": "mock",
        "input": {"scene_number": 1, "checkpoint": {"scene_id": SCENE, "plan_version": 1, "draft_version": 1, "context_pack_version": 1}},
    }
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_planning_v2", TASK, "planning", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(plan(1), ensure_ascii=False), "success", "2026", "2026"))
    db.commit(); db.close()
    adapter = PlanOnlyAdapter([plan(1)])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    planning_calls = [call for call in adapter.calls if call["task_type"] == "planning"]
    assert planning_calls
    assert all(call["prompt_version"] == PLANNING_PROMPT_VERSION for call in planning_calls)
    assert "hc_planted_planning_v2" not in (result["scenes"][0].get("reused_calls") or [])


# 18. A later review JSON exception must not be reclassified from an older planning contract_invalid.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "review-not-planning.db"
    db, book = seed(path)
    old_plan = {
        "task_type": "planning", "contract_type": "ScenePlan", "contract_version": "v1",
        "input": {"checkpoint": {"scene_id": SCENE, "plan_version": 1}},
    }
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,error_json,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?,?)",
        ("hc_old_plan_invalid", TASK, "planning", "mock", "mock",
         json.dumps(old_plan, ensure_ascii=False), json.dumps({"contract_type": "ScenePlan", "contract_version": "v1", "payload": base}, ensure_ascii=False),
         "contract_invalid", json.dumps({"error": "CONTRACT_PAYLOAD_INVALID", "planning_reason": "plan_progression_missing"}),
         "1", "1"))
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_later_plan_ok", TASK, "planning", "mock", "mock",
         json.dumps({"task_type": "planning", "input": {"checkpoint": {"scene_id": SCENE, "plan_version": 2}}}, ensure_ascii=False),
         json.dumps({"contract_type": "ScenePlan", "contract_version": "v1", "payload": base}, ensure_ascii=False),
         "success", "2", "2"))
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,status,error_json,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_review_json", TASK, "review_plot", "mock", "mock",
         json.dumps({"task_type": "review_plot", "input": {"checkpoint": {"scene_id": SCENE, "plan_version": 2}}}, ensure_ascii=False),
         "failed", json.dumps({"error": "MODEL_RESPONSE_JSON_INVALID"}), "3", "3"))
    db.execute(
        "insert into exception_queue(exception_id,task_id,source_node,error_code,error_message,details_json,status,retry_count,created_at) values (?,?,?,?,?,?,?,?,?)",
        ("ex_review_json", TASK, "reviewing", "MODEL_RESPONSE_JSON_INVALID", "bad json",
         json.dumps({"harness_call_id": "hc_review_json"}), "pending", 0, "2026"))
    db.execute(
        "update task_states set status='exception_pending',current_node='exception_handling',next_action='handle_exception',exception_id=? where task_id=?",
        ("ex_review_json", TASK))
    db.commit()
    assert reclassify_orphaned_planning_exception(db, TASK) is False
    assert db.execute("select status from exception_queue where exception_id='ex_review_json'").fetchone()[0] == "pending"
    assert db.execute("select status from task_states where task_id=?", (TASK,)).fetchone()[0] == "exception_pending"
    db.close()


print('scene plan gate ok')

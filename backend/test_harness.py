import json, sqlite3, tempfile
from pathlib import Path
from harness import (Harness, ModelProfile, MockAdapter, required_fields_validator, ContractFormatError,
    PLANNING_PROMPT_VERSION, REVIEWER_PROMPT_VERSION, REVIEWER_ROLE_BY_TASK, validate_reviewer_result_against_input,
    validate_reviewer_result_for_task)
from backend.prose_length import WRITING_PROMPT_VERSION
from backend.progression import verify_progression
from backend.siliconflow import (build_chat_messages, reviewer_correction_instruction,
    reviewer_evidence_instruction, reviewer_findings_instruction, reviewer_plot_instruction,
    reviewer_style_instruction, reviewer_world_instruction)
from integration.run_real_test import run

STATE = {
    "characters": ["林照"], "location": "灯塔", "time_context": "夜晚",
    "events": ["调查"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"],
}


def plot_assessment(status="achieved"):
    return {
        "status": status,
        "achieved_items": [{
            "progress_type": "new_clue", "target_key": "线索", "before_state": "未知",
            "after_state": "发现", "evidence_text": "林照", "evidence_location": "draft.text",
        }],
        "missing_items": [],
    }


def reviewer_response(role, **updates):
    payload = {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [],
        "issue_count": 0, "severity": "ordinary", "impact_scope": "local",
        "true_conflict_candidate": False, "scene_state": STATE,
    }
    if role == "character_plot":
        payload["progression_assessment"] = plot_assessment()
    payload.update(updates)
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}


def expect_invalid(response, contract_type="ReviewerResult"):
    try:
        required_fields_validator(response, contract_type)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        return
    raise AssertionError("invalid ReviewerResult accepted")


def open_harness_db(directory):
    db = Path(directory) / "x.db"
    con = sqlite3.connect(db)
    con.executescript((Path(__file__).parents[1] / "db/migrations/001_initial.sql").read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')")
    con.commit(); con.close()
    return db


DEFAULT_DRAFT_TEXT = "林照在档案室停住。管理员挡住门口。夜风穿过窗缝。"
DEFAULT_REQUIREMENT = {
    "progress_type": "new_clue", "target_key": "线索", "before_state": "未知",
    "expected_after_state": "发现", "acceptance_criterion": "正文出现发现",
}


def plot_review_input(text=DEFAULT_DRAFT_TEXT, requirements=None):
    return {
        "scene_plan": {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
            "progression_requirements": list(requirements or [DEFAULT_REQUIREMENT]),
        }},
        "draft": {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {"text": text}},
    }


def run_review(db, task_type, response, input_payload=None):
    harness = Harness(db, {task_type: ModelProfile("mock", "m")}, {"mock": MockAdapter(response)})
    try:
        return harness.run(
            task_id="t", agent_task_type=task_type, input_payload=input_payload or plot_review_input(),
            contract_type="ReviewerResult", contract_validator=required_fields_validator,
        )
    finally:
        harness.close()


def latest_call_status(db):
    con = sqlite3.connect(db)
    status = con.execute("select status from harness_calls order by started_at desc limit 1").fetchone()[0]
    con.close()
    return status


with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; con=sqlite3.connect(db); con.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')"); con.commit(); con.close()
    h=Harness(db, {'planning':ModelProfile('mock','m',technical_retries=1)}, {'mock':MockAdapter({'contract_type':'ScenePlan','contract_version':'v1','payload':{'scene_goal':'推进调查','entrance_state':{'location':'灯塔'},'exit_state':{'clue':'异常记录'},'characters':['林照'],'location':'灯塔','time_context':'夜晚','conflict':'寻找线索','action_beats':['翻阅档案'],'must_happen':['发现线索'],'must_not_happen':['谜团解决'],'knowledge_boundary':'灯塔只能展示记忆','target_word_count':1250,'acceptance_criteria':['推进剧情'],'validation_result':{'complete':True},'ready_for_writing':True,'progression_requirements':[{'progress_type':'new_clue','target_key':'异常记录','before_state':'未知','expected_after_state':'发现记录','acceptance_criterion':'正文发现记录'}]}})})
    result=h.run(task_id='t',agent_task_type='planning',input_payload={'x':1},contract_type='ScenePlan',contract_validator=required_fields_validator); assert result['harness_call_id'].startswith('hc_')
    stored=h.db.execute("select model,request_json from harness_calls where harness_call_id=?",(result['harness_call_id'],)).fetchone()
    request=json.loads(stored[1]); assert request['model']=='m'==stored[0]; assert request['timeout_seconds']==60; assert request['json_mode'] is False
    try: Harness(db, {'planning':ModelProfile('mock','m')}, {'mock':MockAdapter({})}).run(task_id='t',agent_task_type='planning',input_payload={},contract_type='ScenePlan',contract_validator=required_fields_validator)
    except ContractFormatError: pass
    else: raise AssertionError('invalid contract accepted')
    h.close()


# 1 / 3 / 4. Bound roles succeed when they match the task.
with tempfile.TemporaryDirectory() as directory:
    db = open_harness_db(directory)
    assert run_review(db, "review_world", reviewer_response("world_consistency"))["harness_call_id"].startswith("hc_")
    assert latest_call_status(db) == "success"
    assert run_review(db, "review_plot", reviewer_response("character_plot"))["response"]["payload"]["reviewer_role"] == "character_plot"
    assert run_review(db, "review_style", reviewer_response("language_experience"))["response"]["payload"]["reviewer_role"] == "language_experience"


# 2 / 5. Role impersonation is contract_invalid before QualityReport.
with tempfile.TemporaryDirectory() as directory:
    db = open_harness_db(directory)
    try:
        run_review(db, "review_world", reviewer_response("character_plot"))
    except ContractFormatError:
        assert latest_call_status(db) == "contract_invalid"
    else:
        raise AssertionError("review_world impersonating character_plot accepted")
    try:
        run_review(db, "review_style", reviewer_response("world_consistency"))
    except ContractFormatError:
        assert latest_call_status(db) == "contract_invalid"
    else:
        raise AssertionError("review_style impersonating world_consistency accepted")
    validate_reviewer_result_for_task(reviewer_response("world_consistency"), "review_world")
    try:
        validate_reviewer_result_for_task(reviewer_response("character_plot"), "review_world")
    except ContractFormatError:
        pass
    else:
        raise AssertionError("task/role mismatch accepted")


# 6 / 7. progression_assessment.status accepts only the three formal values.
expect_invalid(reviewer_response("character_plot", progression_assessment=plot_assessment("partial")))
expect_invalid(reviewer_response("character_plot", progression_assessment=plot_assessment("partial_success")))
for status in ("achieved", "not_achieved", "unclear"):
    required_fields_validator(reviewer_response("character_plot", progression_assessment=plot_assessment(status)), "ReviewerResult")


# 8 / 9. severity only ordinary/serious.
expect_invalid(reviewer_response("world_consistency", severity="moderate"))
for severity in ("ordinary", "serious"):
    required_fields_validator(reviewer_response("world_consistency", severity=severity), "ReviewerResult")


# 10 / 11. impact_scope only the four formal values.
expect_invalid(reviewer_response("language_experience", impact_scope="plot_progression"))
for scope in ("local", "cross_scene", "cross_chapter", "book"):
    required_fields_validator(reviewer_response("language_experience", impact_scope=scope), "ReviewerResult")


# 12 / 13. Non-plot reviewers may omit progression_assessment; plot may not.
required_fields_validator(reviewer_response("world_consistency"), "ReviewerResult")
required_fields_validator(reviewer_response("language_experience"), "ReviewerResult")
expect_invalid(reviewer_response("character_plot", progression_assessment=None))
# Optional assessment on world/style still cannot use illegal statuses.
expect_invalid(reviewer_response("world_consistency", progression_assessment={"status": "partial", "achieved_items": [], "missing_items": []}))


# findings/suggestions contract: arrays, issue_count binding, result consistency.
required_fields_validator(reviewer_response("world_consistency", findings=[], suggestions=["可酌情精简一处分句"], issue_count=0), "ReviewerResult")
expect_invalid(reviewer_response("world_consistency", findings="通过", suggestions=[], issue_count=0))
expect_invalid(reviewer_response("world_consistency", findings=[], suggestions="可优化", issue_count=0))
expect_invalid(reviewer_response("world_consistency", findings=[], suggestions=[], issue_count=1))
expect_invalid(reviewer_response("language_experience", result="passed", findings=["略显重复"], suggestions=[], issue_count=1))
expect_invalid(reviewer_response("language_experience", result="failed", findings=[], suggestions=["可酌情精简"], issue_count=0))
expect_invalid(reviewer_response("world_consistency", result="pass_with_notes", findings=[], suggestions=[], issue_count=0))
required_fields_validator(reviewer_response(
    "world_consistency", result="failed", findings=["世界规则冲突"], suggestions=[], issue_count=1,
), "ReviewerResult")


# 16. Role-specific last instructions are distinct and name the bound role.
world_messages = build_chat_messages({"contract_type": "ReviewerResult", "task_type": "review_world", "input": {"draft": {}}})
plot_messages = build_chat_messages({"contract_type": "ReviewerResult", "task_type": "review_plot", "input": {"draft": {}}})
style_messages = build_chat_messages({"contract_type": "ReviewerResult", "task_type": "review_style", "input": {"draft": {}}})
assert world_messages[2]["content"] == reviewer_world_instruction()
assert plot_messages[2]["content"] == reviewer_plot_instruction()
assert style_messages[2]["content"] == reviewer_style_instruction()
assert world_messages[2]["content"] != plot_messages[2]["content"] != style_messages[2]["content"]
assert "world_consistency" in world_messages[2]["content"]
assert "character_plot" in plot_messages[2]["content"]
assert "language_experience" in style_messages[2]["content"]
assert "不得冒充 character_plot" in world_messages[2]["content"]
assert "不得冒充 character_plot" in style_messages[2]["content"]
assert reviewer_findings_instruction() in world_messages[2]["content"]
assert reviewer_findings_instruction() in plot_messages[2]["content"]
assert reviewer_findings_instruction() in style_messages[2]["content"]
assert "不得为了显得认真而强行制造 findings" in reviewer_findings_instruction()
assert "允许 findings=[]" in reviewer_findings_instruction()
assert reviewer_findings_instruction() in reviewer_correction_instruction()
assert "pass_with_notes" in reviewer_correction_instruction()
assert "partial" in plot_messages[2]["content"]
assert "partially_achieved" in plot_messages[2]["content"]
assert "有至少一个合法 achieved_item" in plot_messages[2]["content"]
assert reviewer_evidence_instruction() in plot_messages[2]["content"]
assert "evidence_text in draft.payload.text" in plot_messages[2]["content"]
assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
correction_messages = build_chat_messages({
    "contract_type": "ReviewerResult", "task_type": "review_plot",
    "input": {**plot_review_input(), "reviewer_contract_correction": {
        "original_call_id": "hc_old", "correction_attempt": 1,
    }},
})
assert correction_messages[2]["content"] == reviewer_plot_instruction()
assert correction_messages[3]["content"] == reviewer_correction_instruction()
assert "partially_achieved" in reviewer_correction_instruction()
assert "expected_after_state" in reviewer_correction_instruction()
assert REVIEWER_ROLE_BY_TASK == {
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


def prose(size):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": "潮" * size, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def runner_reviewer(role):
    payload = reviewer_response(role)["payload"]
    payload["scene_state"] = {
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"],
    }
    if role == "character_plot":
        payload["progression_assessment"] = {
            "status": "achieved", "achieved_items": [{
                "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
                "after_state": "发现线索", "evidence_text": "潮", "evidence_location": "draft.text",
            }], "missing_items": [], "evidence": "潮",
        }
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
        "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}


class BoundReviewAdapter:
    def __init__(self, world_role="world_consistency", timeout_world=False):
        self.world_role, self.timeout_world, self.calls = world_role, timeout_world, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return prose(1100)
        if role == "memory_extraction":
            return memory()
        if role == "review_world":
            if self.timeout_world:
                raise TimeoutError("The read operation timed out")
            return runner_reviewer(self.world_role)
        return runner_reviewer(ROLES[role])


# 14 / 15. A role mismatch is a technical exception: no QualityReport, no content count.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "wrong-role.db"
    adapter = BoundReviewAdapter(world_role="character_plot")
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert db.execute("select status,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?",
                      ("realtest_tide_archive_scene_1",)).fetchone() == ("exception_pending", 0, 0)
    assert db.execute("select count(*) from quality_reports where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 0
    assert db.execute("select status from harness_calls where agent_type='review_world'").fetchone()[0] == "contract_invalid"
    db.close()


# 17. Old reviewer prompt_version responses cannot be reused after the upgrade.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v1-review-reuse.db"
    first_adapter = BoundReviewAdapter(timeout_world=True)
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    world_request = next(call for call in first_adapter.calls if call["task_type"] == "review_world")
    planted = dict(world_request)
    planted["prompt_version"] = "v1"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_review_v1", "realtest_tide_archive_scene_1_task", "review_world", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(runner_reviewer("world_consistency"), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = BoundReviewAdapter()
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    world_calls = [call for call in second_adapter.calls if call["task_type"] == "review_world"]
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert world_calls
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION for call in world_calls)
    assert "hc_planted_review_v1" not in (second["scenes"][0].get("reused_calls") or [])
    assert WRITING_PROMPT_VERSION == "prose_quality_v5"
    assert {call["prompt_version"] for call in second_adapter.calls if call["task_type"] == "planning"} <= {PLANNING_PROMPT_VERSION}
    assert {call["prompt_version"] for call in second_adapter.calls if call["task_type"] == "writing"} <= {WRITING_PROMPT_VERSION}


def plot_item(**updates):
    item = {
        "progress_type": "new_clue", "target_key": "线索", "before_state": "未知",
        "after_state": "发现", "evidence_text": "林照在档案室停住。", "evidence_location": "draft.text",
    }
    item.update(updates)
    return item


def plot_against_input(*, status="achieved", achieved=None, missing=None, text=DEFAULT_DRAFT_TEXT):
    if achieved is None:
        achieved = [plot_item()] if status == "achieved" else []
    response = reviewer_response("character_plot", progression_assessment={
        "status": status, "achieved_items": achieved, "missing_items": list(missing or []),
    })
    validate_reviewer_result_against_input(response, "review_plot", plot_review_input(text))
    return response


def expect_plot_input_invalid(**kwargs):
    try:
        plot_against_input(**kwargs)
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        return
    raise AssertionError("illegal plot evidence accepted")


# 1 / 2. Contiguous one- and two-sentence evidence passes.
plot_against_input(achieved=[plot_item(evidence_text="林照在档案室停住。")])
plot_against_input(achieved=[plot_item(evidence_text="林照在档案室停住。管理员挡住门口。")])
with tempfile.TemporaryDirectory() as directory:
    db = open_harness_db(directory)
    assert run_review(db, "review_plot", reviewer_response("character_plot", progression_assessment={
        "status": "achieved", "achieved_items": [plot_item()], "missing_items": [],
    }))["harness_call_id"].startswith("hc_")
    assert latest_call_status(db) == "success"

# 3. Spliced non-adjacent paragraphs omit the middle sentence.
expect_plot_input_invalid(achieved=[plot_item(evidence_text="林照在档案室停住。夜风穿过窗缝。")])
# 4. Rewritten prose is not evidence.
expect_plot_input_invalid(achieved=[plot_item(evidence_text="林照在档案室内停下脚步")])
# 5. Empty evidence_text.
expect_plot_input_invalid(achieved=[plot_item(evidence_text="")])
# 6 / 7. Evidence may not come from ContextPack or ScenePlan.
expect_plot_input_invalid(achieved=[plot_item(evidence_location="ContextPack.previous_scene_state")])
expect_plot_input_invalid(achieved=[plot_item(evidence_location="ScenePlan.progression_requirements")])
# 8. Invented achieved type/key.
expect_plot_input_invalid(achieved=[plot_item(progress_type="character_development", target_key="情感成长")])
# 9. before_state must copy the plan.
expect_plot_input_invalid(achieved=[plot_item(before_state="已经找到林澜")])
# 10. Invented missing type/key.
expect_plot_input_invalid(
    status="not_achieved",
    missing=[{"progress_type": "world_expansion", "target_key": "新世界观"}],
)
# 11. achieved without items.
expect_plot_input_invalid(status="achieved", achieved=[])
# 12. not_achieved without missing items.
expect_plot_input_invalid(status="not_achieved", missing=[])
# 13. Same type/key cannot appear in both lists.
expect_plot_input_invalid(
    achieved=[plot_item()],
    missing=[{"progress_type": "new_clue", "target_key": "线索"}],
)
# after_state must contain the planned expected_after_state.
expect_plot_input_invalid(achieved=[plot_item(after_state="无关结果")])


LONG_PROSE = "林照在档案室停住。管理员挡住门口。夜风穿过窗缝。" + ("档案纸页在灯光下翻动。" * 120)
PLAN_ITEM = {
    "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
    "after_state": "发现线索", "evidence_text": "林照在档案室停住。", "evidence_location": "draft.text",
}


def long_prose():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": LONG_PROSE, "word_count": 1250, "target_word_count": 1250, "complete": True,
        "writer_self_check": {"complete": True},
    }}


class PlotEvidenceAdapter:
    def __init__(self, plot_item=None, *, timeout_plot=False, same_text=False):
        self.plot_item = plot_item
        self.timeout_plot = timeout_plot
        self.same_text = same_text
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
            raise AssertionError("17. Reviewer contract failure must not call Memory")
        if role == "review_plot":
            if self.timeout_plot:
                raise TimeoutError("The read operation timed out")
            payload = runner_reviewer("character_plot")["payload"]
            payload["progression_assessment"] = {
                "status": "achieved",
                "achieved_items": [self.plot_item or PLAN_ITEM],
                "missing_items": [],
            }
            return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}
        return runner_reviewer(ROLES[role])


# 14-17 / 19. Spliced plot evidence is a technical contract error.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "spliced-plot.db"
    adapter = PlotEvidenceAdapter(plot_item={**PLAN_ITEM, "evidence_text": "林照在档案室停住。夜风穿过窗缝。"})
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene = "realtest_tide_archive_scene_1"
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert db.execute("select count(*) from quality_reports where scene_id=?", (scene,)).fetchone()[0] == 0
    assert db.execute("select count(*) from scene_progression_checks where scene_id=?", (scene,)).fetchone()[0] == 0
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene,)).fetchone() == (0, 0, "exception_pending")
    assert [call["task_type"] for call in adapter.calls].count("writing") == 1
    assert not any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    assert db.execute("select status from harness_calls where agent_type='review_plot'").fetchone()[0] == "contract_invalid"
    plot_call = next(call for call in adapter.calls if call["task_type"] == "review_plot")
    assert plot_call["prompt_version"] == REVIEWER_PROMPT_VERSION
    assert [call["task_type"] for call in adapter.calls].count("review_plot") == 2
    assert result["scenes"][0]["reviewer_correction_called"] is True
    assert result["scenes"][0]["reviewer_correction_succeeded"] is False
    db.close()

# 18. Resume cannot reuse an old v2 illegal-evidence success row.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v2-plot-reuse.db"
    first_adapter = PlotEvidenceAdapter(timeout_plot=True)
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    plot_request = next(call for call in first_adapter.calls if call["task_type"] == "review_plot")
    planted = dict(plot_request)
    planted["prompt_version"] = "reviewer_contract_v2"
    illegal = {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        **runner_reviewer("character_plot")["payload"],
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            **PLAN_ITEM, "evidence_text": "林照在档案室停住。夜风穿过窗缝。",
        }], "missing_items": []},
    }}
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_plot_v2", "realtest_tide_archive_scene_1_task", "review_plot", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(illegal, ensure_ascii=False),
         "success", "2026", "2026"))
    v3_planted = dict(plot_request)
    v3_planted["prompt_version"] = "reviewer_contract_v3"
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_plot_v3_illegal", "realtest_tide_archive_scene_1_task", "review_plot", "mock", "mock",
         json.dumps(v3_planted, ensure_ascii=False), json.dumps(illegal, ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = PlotEvidenceAdapter(plot_item=PLAN_ITEM)
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    reused = second["scenes"][0].get("reused_calls") or []
    assert "hc_planted_plot_v2" not in reused
    assert "hc_planted_plot_v3_illegal" not in reused
    assert any(call["task_type"] == "review_plot" and call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second_adapter.calls)

# 20. Backend verify_progression still rejects non-contiguous evidence.
with tempfile.TemporaryDirectory() as directory:
    from integration.seed_real_test import seed
    db, book = seed(Path(directory) / "verify-substring.db")
    db.execute("pragma foreign_keys=OFF")
    spliced = verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id="case_splice_plan", draft_id="case_splice_draft", report_id="case_splice_report",
        requirements=[{
            "progress_type": "new_clue", "target_key": "潮痕编号", "before_state": "未知",
            "expected_after_state": "潮痕编号A-17", "acceptance_criterion": "正文揭示潮痕编号A-17",
        }],
        reviews=[{"payload": {"reviewer_role": "character_plot", "progression_assessment": {
            "status": "achieved", "achieved_items": [{
                "progress_type": "new_clue", "target_key": "潮痕编号", "before_state": "未知",
                "after_state": "潮痕编号A-17",
                "evidence_text": "林照发现潮痕编号A-17。潮声掠过档案室。",
                "evidence_location": "draft.text",
            }], "missing_items": []}}}],
        text="林照发现潮痕编号A-17。管理员拦住去路。潮声掠过档案室。",
        previous_scene_id=None, previous_state={},
        accepted_scene_state={"characters": ["林照"], "location": "灯塔", "time_context": "夜晚",
                              "events": ["潮痕编号A-17"], "relationship_changes": [], "unresolved_threads": []},
    )
    assert spliced["progression_failure_reason"] == "progression_evidence_not_in_draft"
    db.close()

print("ok")

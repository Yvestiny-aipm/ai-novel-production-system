"""Fixed coverage for ReviewerResult findings vs suggestions."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import REVIEWER_PROMPT_VERSION, required_fields_validator, ContractFormatError
from backend.siliconflow import reviewer_findings_instruction, reviewer_style_instruction
from integration.run_real_test import aggregate_quality, run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
GATES_14_NOTE = "记忆只能保存和展示出现多次，可酌情精简一处分句"
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


def long_prose():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": LONG_PROSE, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, *, result="passed", findings=None, suggestions=None, issue_count=None,
             severity="ordinary", impact_scope="local", true_conflict=False, status="achieved"):
    items = list(findings or [])
    notes = list(suggestions or [])
    count = len(items) if issue_count is None else issue_count
    payload = {
        "reviewer_role": role, "result": result, "findings": items, "suggestions": notes,
        "issue_count": count, "severity": severity, "impact_scope": impact_scope,
        "true_conflict_candidate": true_conflict, "scene_state": STATE,
    }
    if role == "character_plot":
        achieved = [PLAN_ITEM] if status == "achieved" else []
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


def arbiter_report():
    return {"contract_type": "QualityReport", "contract_version": "v1", "payload": {
        "review_completion_status": "completed", "reviewer_results": [], "deduped_issue_count": 0,
        "ordinary_issue_count": 0, "serious_issue_count": 0, "has_true_conflict": False,
        "needs_arbiter": False, "routing_recommendation": "complete",
        "accepted_scene_state": STATE, "status": "passed",
    }}


class ReviewAdapter:
    def __init__(self, *, world=None, plot=None, style=None, same_text=False):
        self.world, self.plot, self.style = world, plot, style
        self.same_text = same_text
        self.calls, self.writes = [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            self.writes += 1
            payload = long_prose()
            if not self.same_text:
                payload["payload"]["text"] = LONG_PROSE + f"第{self.writes}稿。"
            return payload
        if role == "memory_extraction":
            return memory()
        if role == "arbiter":
            return arbiter_report()
        if role == "review_world":
            return self.world or reviewer("world_consistency")
        if role == "review_plot":
            return self.plot or reviewer("character_plot")
        return self.style or reviewer("language_experience")


def roles(adapter):
    return [call["task_type"] for call in adapter.calls]


def report_blob(path):
    db = sqlite3.connect(path)
    row = db.execute("select reviewer_results_json,status,needs_arbiter from quality_reports where scene_id=?",
                     (SCENE,)).fetchone()
    db.close()
    return row


def reviewer_payloads(blob):
    stored = json.loads(blob)
    if stored and isinstance(stored[0], dict) and stored[0].get("contract_type") == "QualityReport":
        return stored[0]["payload"].get("reviewer_results") or []
    return stored


assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
assert "不得为了显得认真而强行制造 findings" in reviewer_style_instruction()
assert reviewer_findings_instruction() in reviewer_style_instruction()


# 1 / 2 / 18. Empty findings + gates_14-style suggestion is passed with issue_count=0.
style_note = reviewer(
    "language_experience", suggestions=[GATES_14_NOTE],
)
required_fields_validator(style_note, "ReviewerResult")
assert style_note["payload"]["result"] == "passed"
assert style_note["payload"]["issue_count"] == 0
soft = aggregate_quality([
    reviewer("world_consistency"),
    reviewer("character_plot"),
    style_note,
])
assert soft["payload"]["status"] == "passed"
assert soft["payload"]["ordinary_issue_count"] == 0
assert soft["payload"]["serious_issue_count"] == 0
assert soft["payload"]["needs_arbiter"] is False


# 7. issue_count must equal findings length.
try:
    required_fields_validator(reviewer("world_consistency", findings=["世界规则冲突"], issue_count=0), "ReviewerResult")
except ContractFormatError:
    pass
else:
    raise AssertionError("mismatched issue_count accepted")


# 8 / 9 / 10. result/findings consistency and array types.
try:
    required_fields_validator(reviewer("world_consistency", result="passed", findings=["世界规则冲突"], issue_count=1), "ReviewerResult")
except ContractFormatError:
    pass
else:
    raise AssertionError("passed with findings accepted")
try:
    required_fields_validator(reviewer("world_consistency", result="failed", findings=[], suggestions=[GATES_14_NOTE]), "ReviewerResult")
except ContractFormatError:
    pass
else:
    raise AssertionError("failed with empty findings accepted")
try:
    required_fields_validator(reviewer("world_consistency", findings="通过", suggestions=[]), "ReviewerResult")
except ContractFormatError:
    pass
else:
    raise AssertionError("string findings accepted")


# 1-5 / 17 / 18. Suggestions do not trigger Writing, Arbiter, or Memory block.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "suggestions-pass.db"
    adapter = ReviewAdapter(style=style_note)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    blob, status, needs_arbiter = report_blob(path)
    payloads = reviewer_payloads(blob)
    scene = result["scenes"][0]
    assert scene["final_status"] == "waiting_confirmation"
    assert scene["arbiter_called"] is False
    assert roles(adapter).count("writing") == 1
    assert "arbiter" not in roles(adapter)
    assert "memory_extraction" in roles(adapter)
    assert status == "passed"
    assert needs_arbiter == 0
    style_payload = next(
        (item.get("payload") or item) for item in payloads
        if (item.get("payload") or item).get("reviewer_role") == "language_experience"
    )
    assert style_payload["suggestions"] == [GATES_14_NOTE]
    assert style_payload["findings"] == []
    assert style_payload["issue_count"] == 0


# 16. issue_count=0 cross_scene suggestions do not trigger Arbiter.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "cross-scene-suggestion.db"
    adapter = ReviewAdapter(style=reviewer(
        "language_experience", suggestions=["节奏还有优化空间，但不影响阅读"], impact_scope="cross_scene",
    ))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["arbiter_called"] is False
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert "arbiter" not in roles(adapter)
    assert roles(adapter).count("writing") == 1


# 6. One finding sets issue_count=1 and reworks Writing.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "one-finding-rework.db"
    adapter = ReviewAdapter(world=reviewer(
        "world_consistency", result="failed", findings=["世界规则冲突"], issue_count=1,
    ))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    writing = [call for call in adapter.calls if call["task_type"] == "writing"]
    assert len(writing) >= 2
    feedback = writing[1]["input"]["quality_revision_feedback"]
    assert feedback["reviewer_findings"][0]["issue_count"] == 1
    assert feedback["reviewer_findings"][0]["findings"] == ["世界规则冲突"]
    assert result["scenes"][0]["arbiter_called"] is False


# 11. World-rule conflict still blocks / reworks.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "world-block.db"
    adapter = ReviewAdapter(world=reviewer(
        "world_consistency", result="failed", findings=["世界规则冲突：灯塔只能保存记忆"], issue_count=1,
    ), same_text=True)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["final_status"] in ("reworking_writing", "reworking_planning", "blocked")
    assert "memory_extraction" not in roles(adapter) or result["scenes"][0]["final_status"] != "waiting_confirmation"


# 12. Failed progression still blocks even with empty findings.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "progression-block.db"
    adapter = ReviewAdapter(plot=reviewer("character_plot", status="not_achieved"))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["final_status"] in ("reworking_writing", "reworking_planning", "blocked")
    assert "memory_extraction" not in roles(adapter)


# 13. Obvious language errors still rework.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "language-block.db"
    adapter = ReviewAdapter(style=reviewer(
        "language_experience", result="failed",
        findings=["严重语法错误导致无法阅读"], issue_count=1,
    ))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert roles(adapter).count("writing") >= 2
    assert result["scenes"][0]["arbiter_called"] is False


# 14. Cross-scene hard findings still trigger Arbiter.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "cross-scene-hard.db"
    adapter = ReviewAdapter(world=reviewer(
        "world_consistency", result="failed", findings=["跨场事实矛盾"],
        issue_count=1, impact_scope="cross_scene",
    ))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["arbiter_called"] is True


# 15. true_conflict_candidate still triggers Arbiter independently.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "true-conflict.db"
    adapter = ReviewAdapter(world=reviewer("world_consistency", true_conflict=True))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["arbiter_called"] is True
    assert result["scenes"][0]["arbiter_succeeded"] is True


# 20. reviewer_contract_v8 does not reuse old v5 responses.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v5-reuse.db"
    first = ReviewAdapter(style=reviewer("language_experience", suggestions=[GATES_14_NOTE]))
    run(db_path=path, adapter=first, execution_mode="sequential")
    style_request = next(call for call in first.calls if call["task_type"] == "review_style")
    planted = dict(style_request)
    planted["prompt_version"] = "reviewer_contract_v5"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_reviewer_v5", TASK, "review_style", "mock", "mock",
         json.dumps(planted, ensure_ascii=False),
         json.dumps(reviewer("language_experience", suggestions=[GATES_14_NOTE]), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second = ReviewAdapter(style=reviewer("language_experience", suggestions=[GATES_14_NOTE]))
    result = run(db_path=path, adapter=second, execution_mode="sequential")
    assert "hc_planted_reviewer_v5" not in (result["scenes"][0].get("reused_calls") or [])
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second.calls if call["task_type"].startswith("review_"))


print("reviewer findings suggestions ok")

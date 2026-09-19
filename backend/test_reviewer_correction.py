"""One-shot ReviewerResult contract correction and v4 prompt reuse."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import REVIEWER_PROMPT_VERSION
from backend.siliconflow import reviewer_correction_instruction
from integration.run_real_test import run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
LONG_PROSE = "林照在档案室停住。管理员挡住门口。夜风穿过窗缝。" + ("档案纸页在灯光下翻动。" * 120)
PLAN_ITEM = {
    "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
    "after_state": "发现线索", "evidence_text": "林照在档案室停住。", "evidence_location": "draft.text",
}
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


def long_prose():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": LONG_PROSE, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, *, item=None, status="achieved"):
    payload = {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
    }
    if role == "character_plot":
        achieved = [item or PLAN_ITEM] if status == "achieved" or status == "partially_achieved" else []
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


class CorrectionAdapter:
    def __init__(self, *, first_status="partially_achieved", first_item=None, corrected_item=None,
                 fail_again=False):
        self.first_status = first_status
        self.first_item = first_item or PLAN_ITEM
        self.corrected_item = corrected_item or PLAN_ITEM
        self.fail_again = fail_again
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
        if role == "review_plot":
            correction = request["input"].get("reviewer_contract_correction")
            if correction:
                if self.fail_again:
                    return reviewer("character_plot", item=self.first_item, status=self.first_status)
                return reviewer("character_plot", item=self.corrected_item, status="achieved")
            return reviewer("character_plot", item=self.first_item, status=self.first_status)
        return reviewer(ROLES[role])


def plot_rows(db):
    return db.execute(
        "select harness_call_id,status,request_json,response_json from harness_calls "
        "where task_id=? and agent_type='review_plot' order by started_at",
        (TASK,)).fetchall()


def content_counts(db):
    return db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where task_id=?",
        (TASK,)).fetchone()


assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
assert "partially_achieved" in reviewer_correction_instruction()
assert "expected_after_state" in reviewer_correction_instruction()


# 1-6 / 16. partially_achieved triggers one correction, then QualityReport continues.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-partial.db"
    adapter = CorrectionAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential",
                 model_environ={"SILICONFLOW_REVIEW_MODEL": "vendor/review"})
    db = sqlite3.connect(path)
    rows = plot_rows(db)
    first_request = json.loads(rows[0][2])
    correction_request = json.loads(rows[1][2])
    correction = correction_request["input"]["reviewer_contract_correction"]
    scene = result["scenes"][0]
    assert scene["final_status"] == "waiting_confirmation"
    assert scene["reviewer_correction_called"] is True
    assert scene["reviewer_correction_succeeded"] is True
    assert scene["corrected_reviewer_role"] == "character_plot"
    assert rows[0][1] == "contract_invalid"
    assert rows[1][1] == "success"
    assert rows[0][0] != rows[1][0]
    assert "reviewer_contract_correction" not in first_request["input"]
    assert correction["original_call_id"] == rows[0][0]
    assert correction["original_response"]["payload"]["progression_assessment"]["status"] == "partially_achieved"
    assert correction["validation_error"]["code"] == "CONTRACT_PAYLOAD_INVALID"
    assert correction["correction_attempt"] == 1
    assert correction["allowed_status"] == ["achieved", "not_achieved", "unclear"]
    assert first_request["prompt_version"] == REVIEWER_PROMPT_VERSION
    assert correction_request["prompt_version"] == REVIEWER_PROMPT_VERSION
    assert first_request["model"] == "vendor/review"
    assert correction_request["model"] == "vendor/review"
    assert db.execute("select model from harness_calls where harness_call_id=?", (rows[1][0],)).fetchone()[0] == "vendor/review"
    assert db.execute("select count(*) from quality_reports where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute("select count(*) from exception_queue where task_id=?", (TASK,)).fetchone()[0] == 0
    assert content_counts(db)[:2] == (0, 0)
    assert [call["task_type"] for call in adapter.calls].count("review_plot") == 2
    db.close()


# 7-8. A second illegal correction enters the exception queue and does not loop.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-again-fails.db"
    adapter = CorrectionAdapter(fail_again=True)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = plot_rows(db)
    scene = result["scenes"][0]
    assert scene["final_status"] == "exception_pending"
    assert scene["reviewer_correction_called"] is True
    assert scene["reviewer_correction_succeeded"] is False
    assert scene["corrected_reviewer_role"] == "character_plot"
    assert [row[1] for row in rows] == ["contract_invalid", "contract_invalid"]
    assert rows[0][0] != rows[1][0]
    assert json.loads(rows[1][2])["input"]["reviewer_contract_correction"]["correction_attempt"] == 1
    assert [call["task_type"] for call in adapter.calls].count("review_plot") == 2
    assert db.execute("select count(*) from quality_reports where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert db.execute(
        "select source_node,error_code,status,retry_count from exception_queue where task_id=?",
        (TASK,)).fetchone() == ("reviewing", "CONTRACT_PAYLOAD_INVALID", "pending", 0)
    assert content_counts(db) == (0, 0, "exception_pending")
    db.close()


# 9-11. after_state mismatch is a Reviewer contract error; correction must copy Plan and draft.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-after-state.db"
    adapter = CorrectionAdapter(
        first_status="achieved",
        first_item={**PLAN_ITEM, "after_state": "档案室停留"},
        corrected_item=PLAN_ITEM,
    )
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = plot_rows(db)
    corrected = json.loads(rows[1][3])["payload"]["progression_assessment"]
    scene = result["scenes"][0]
    assert scene["reviewer_correction_called"] is True
    assert scene["reviewer_correction_succeeded"] is True
    assert rows[0][1] == "contract_invalid"
    assert "does not match expected_after_state" in json.loads(
        db.execute("select error_json from harness_calls where harness_call_id=?", (rows[0][0],)).fetchone()[0]
    )["reason"]
    assert corrected["achieved_items"][0]["after_state"] == "发现线索"
    assert "林照在档案室停住。" in LONG_PROSE
    assert corrected["achieved_items"][0]["evidence_text"] == "林照在档案室停住。"
    assert corrected["achieved_items"][0]["evidence_text"] in LONG_PROSE
    assert scene["final_status"] == "waiting_confirmation"
    assert content_counts(db)[:2] == (0, 0)
    db.close()


# 16. Old reviewer_contract_v3 success rows cannot be reused after the v4 upgrade.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v3-reuse.db"
    first_adapter = CorrectionAdapter(fail_again=True)
    run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    plot_request = next(
        call for call in first_adapter.calls
        if call["task_type"] == "review_plot" and "reviewer_contract_correction" not in call["input"]
    )
    planted = dict(plot_request)
    planted["prompt_version"] = "reviewer_contract_v3"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_reviewer_v3", TASK, "review_plot", "mock", "mock",
         json.dumps(planted, ensure_ascii=False),
         json.dumps(reviewer("character_plot"), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = CorrectionAdapter()
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    assert "hc_planted_reviewer_v3" not in (second["scenes"][0].get("reused_calls") or [])
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second_adapter.calls if call["task_type"] == "review_plot")

class PassWithNotesAdapter(CorrectionAdapter):
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
        if role == "review_plot":
            if request["input"].get("reviewer_contract_correction"):
                return reviewer("character_plot")
            old = reviewer("character_plot")
            old["payload"]["result"] = "pass_with_notes"
            old["payload"]["findings"] = "记忆只能保存和展示出现多次，可酌情精简一处分句"
            old["payload"]["suggestions"] = []
            old["payload"]["issue_count"] = 1
            return old
        return reviewer(ROLES[role])


# 19. One-shot correction can repair the old pass_with_notes structure.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-pass-with-notes.db"
    adapter = PassWithNotesAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = plot_rows(db)
    scene = result["scenes"][0]
    assert scene["reviewer_correction_called"] is True
    assert scene["reviewer_correction_succeeded"] is True
    assert rows[0][1] == "contract_invalid"
    assert rows[1][1] == "success"
    reason = json.loads(
        db.execute("select error_json from harness_calls where harness_call_id=?", (rows[0][0],)).fetchone()[0]
    )["reason"]
    assert "invalid result" in reason or "findings must be an array" in reason
    corrected = json.loads(rows[1][3])["payload"]
    assert corrected["result"] == "passed"
    assert corrected["findings"] == []
    assert corrected["suggestions"] == []
    assert corrected["issue_count"] == 0
    assert scene["final_status"] == "waiting_confirmation"
    db.close()


print("reviewer correction ok")

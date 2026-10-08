"""Technical exception enqueue and explicit-retry audit for the real runner."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import words

from backend.backup_restore import SCENE_TABLES, create_full_backup, restore_full_backup, verify_backup
from backend.harness import ContractFormatError
from backend.siliconflow import ModelResponseParseError
from integration.recovery import (queue_technical_exception, reconstruct_orphaned_exception,
    start_technical_retry)
from integration.run_real_test import run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"


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
        "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}


class WritingTimeoutAdapter:
    def __init__(self, sizes, *, timeout_first=False, timeout_after=None):
        self.sizes, self.timeout_first, self.timeout_after = list(sizes), timeout_first, timeout_after
        self.calls, self.writes = [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            self.writes += 1
            if self.timeout_first and self.writes == 1:
                raise TimeoutError("The read operation timed out")
            if self.timeout_after is not None and self.writes > self.timeout_after:
                raise TimeoutError("The read operation timed out")
            size = self.sizes.pop(0) if self.sizes else 1000
            unique = chr(0x4E00 + self.writes)
            payload = prose(max(size, 1))
            payload["payload"]["text"] = words(size, lead="word", token=f"tok{self.writes}") if size else "word"
            return payload
        if role == "memory_extraction":
            return memory()
        return reviewer(ROLES[role])


def task_row(db):
    return db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,technical_retry_count,"
        "status,current_node,next_action,exception_id,last_error_json from task_states where task_id=?",
        (TASK,)).fetchone()


def exceptions(db):
    return db.execute(
        "select exception_id,source_node,error_code,status,retry_count,resolved_at from exception_queue "
        "where task_id=? order by created_at", (TASK,)).fetchall()


def event_types(db, *kinds):
    return [row[0] for row in db.execute(
        "select event_type from task_events where task_id=? and event_type in ({}) order by rowid".format(
            ",".join("?" * len(kinds))),
        (TASK, *kinds))]


# 1-5 / 6. First writing timeout queues one pending exception and does not count content.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "first-timeout.db"
    first = run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    row = task_row(db)
    queued = exceptions(db)
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert queued == [(row[7], "writing", "TECHNICAL_ERROR", "pending", 0, None)]
    assert row[3:][:4] == (0, "exception_pending", "exception_handling", "handle_exception")
    assert row[7] and json.loads(row[8])["exception_id"] == row[7]
    assert row[:3] == (1, 0, 0)
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert event_types(db, "technical_exception_queued") == ["technical_exception_queued"]
    payload = json.loads(db.execute(
        "select payload_json from task_events where task_id=? and event_type='technical_exception_queued'",
        (TASK,)).fetchone()[0])
    assert payload["source_node"] == "writing"
    assert payload["exception_id"] == row[7]
    assert payload["error_code"] == "TECHNICAL_ERROR"
    queued_error = db.execute(
        "select error_code,error_message,details_json from exception_queue where exception_id=?",
        (row[7],)).fetchone()
    last_error = json.loads(row[8])
    details = json.loads(queued_error[2])
    assert queued_error[0] == "TECHNICAL_ERROR"
    assert queued_error[1] == "The read operation timed out"
    assert last_error["error_code"] == "TECHNICAL_ERROR"
    assert last_error["error_message"] == "The read operation timed out"
    assert details["harness_error"]["error"] == "The read operation timed out"
    assert details["harness_call_id"]
    first_id = queue_technical_exception(
        db, TASK, source_node="writing", error=TimeoutError("The read operation timed out"),
        checkpoint={"scene_id": SCENE, "plan_version": 1, "draft_version": 1})
    assert first_id == row[7]
    assert exceptions(db) == queued
    failed_calls = db.execute(
        "select harness_call_id,status from harness_calls where task_id=? and agent_type='writing' and status='failed'",
        (TASK,)).fetchall()
    assert failed_calls
    db.close()


# 7-12 / 15. Explicit retry marks handling, reuses Plan, then resolves on success.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "retry-success.db"
    adapter = WritingTimeoutAdapter([346, 1000], timeout_after=1)
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    first_exception = exceptions(db)[0]
    first_failed = [row[0] for row in db.execute(
        "select harness_call_id from harness_calls where task_id=? and status='failed' order by started_at",
        (TASK,))]
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert first_exception[3:5] == ("pending", 0)
    assert task_row(db)[:4] == (1, 0, 0, 0)
    assert db.execute("select count(*) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 1
    db.close()
    adapter.timeout_after = None
    adapter.sizes = [1000]
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    row = task_row(db)
    queued = exceptions(db)
    assert second["scenes"][0]["final_status"] == "waiting_confirmation"
    assert queued[0][0] == first_exception[0]
    assert queued[0][3] == "resolved"
    assert queued[0][4] == 1
    assert queued[0][5]
    assert row[3] == 1
    assert row[7] is None
    assert row[8] is None
    assert row[:3] == (1, 0, 0)
    assert [call["task_type"] for call in adapter.calls].count("planning") == 1
    assert db.execute("select count(*) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 2
    assert event_types(db, "technical_retry_started", "technical_exception_resolved") == [
        "technical_retry_started", "technical_exception_resolved"]
    later_failed = [row[0] for row in db.execute(
        "select harness_call_id from harness_calls where task_id=? and status='failed' order by started_at",
        (TASK,))]
    success_ids = [row[0] for row in db.execute(
        "select harness_call_id from harness_calls where task_id=? and agent_type='writing' and status='success' order by started_at",
        (TASK,))]
    assert later_failed == first_failed
    assert success_ids[-1] not in first_failed
    db.close()


# 13 / 14. The same exception returns to pending; the next explicit retry becomes 2.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "retry-again.db"
    first = run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    exception_id = exceptions(db)[0][0]
    assert task_row(db)[3] == 0
    db.close()
    second = run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    row = task_row(db)
    assert second["scenes"][0]["final_status"] == "exception_pending"
    assert queued == [(exception_id, "writing", "TECHNICAL_ERROR", "pending", 1, None)]
    assert row[3] == 1
    assert row[:3] == (1, 0, 0)
    assert row[7] == exception_id
    db.close()
    third = run(db_path=path, adapter=WritingTimeoutAdapter([1000]), execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    row = task_row(db)
    assert third["scenes"][0]["final_status"] == "waiting_confirmation"
    assert queued[0][0] == exception_id
    assert queued[0][3:5] == ("resolved", 2)
    assert row[3] == 2
    assert row[7] is None
    db.close()


# 16. Contract invalid is queued and is not a content failure.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "contract-invalid.db"

    class WrongRoleAdapter:
        def __init__(self):
            self.calls = []

        def complete(self, request, timeout_seconds):
            self.calls.append(request)
            role = request["task_type"]
            number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
            if role == "planning":
                return plan(number)
            if role == "writing":
                return prose(1100)
            if role == "memory_extraction":
                raise AssertionError("contract invalid must not call Memory")
            if role == "review_world":
                return reviewer("character_plot")
            return reviewer(ROLES[role])

    adapter = WrongRoleAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    row = task_row(db)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert queued[0][1:5] == ("reviewing", "CONTRACT_PAYLOAD_INVALID", "pending", 0)
    assert row[:4] == (1, 0, 0, 0)
    assert db.execute("select count(*) from quality_reports where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert not any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    db.close()


# 17. Backup/restore keeps exception_queue rows.
assert "exception_queue" in SCENE_TABLES
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "backup-source.db"
    run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    before = exceptions(db)
    assert before and before[0][3] == "pending"
    db.close()
    backup = create_full_backup(path, Path(directory) / "backups", "exception-queue")
    assert verify_backup(backup)["status"] == "backup_success"
    restored = restore_full_backup(backup, Path(directory) / "restored.db")
    db = sqlite3.connect(restored)
    assert exceptions(db) == before
    db.close()


def orphan_pre_fix_state(db):
    db.execute("delete from exception_queue where task_id=?", (TASK,))
    db.execute("delete from task_events where task_id=? and event_type like 'technical_%'", (TASK,))
    db.execute(
        """update task_states set exception_id=null,last_error_json=null,technical_retry_count=0,
           status='exception_pending',current_node='exception_handling',next_action='handle_exception'
           where task_id=?""",
        (TASK,))
    db.commit()


def latest_failed_call(db):
    return db.execute(
        """select harness_call_id,agent_type,request_json,error_json,status from harness_calls
           where task_id=? and status in ('failed','contract_invalid') order by started_at desc limit 1""",
        (TASK,)).fetchone()


# Pre-fix orphaned exception_pending is reconstructed, then retried once.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "orphan-writing.db"
    run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    failed = latest_failed_call(db)
    checkpoint = json.loads(failed[2])["input"]["checkpoint"]
    plans_before = db.execute("select * from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall()
    drafts_before = db.execute("select * from prose_drafts where scene_id=? order by draft_version", (SCENE,)).fetchall()
    failed_ids = [row[0] for row in db.execute(
        "select harness_call_id from harness_calls where task_id=? and status='failed' order by started_at", (TASK,))]
    content_before = task_row(db)[:3]
    orphan_pre_fix_state(db)
    assert exceptions(db) == []
    assert task_row(db)[7] is None
    db.close()
    second = run(db_path=path, adapter=WritingTimeoutAdapter([1000]), execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    row = task_row(db)
    details = json.loads(db.execute(
        "select details_json from exception_queue where task_id=?", (TASK,)).fetchone()[0])
    events = event_types(db, "technical_exception_reconstructed", "technical_retry_started")
    assert second["scenes"][0]["final_status"] == "waiting_confirmation"
    assert queued[0][1] == "writing"
    assert queued[0][3:5] == ("resolved", 1)
    assert row[3] == 1
    assert details["reconstructed_from_orphaned_state"] is True
    assert details["harness_call_id"] == failed[0]
    assert details["checkpoint"] == checkpoint
    assert events == ["technical_exception_reconstructed", "technical_retry_started"]
    assert task_row(db)[:3] == content_before
    assert db.execute("select * from scene_plans where scene_id=? order by plan_version", (SCENE,)).fetchall() == plans_before
    assert drafts_before == []
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert [row[0] for row in db.execute(
        "select harness_call_id from harness_calls where task_id=? and status='failed' order by started_at",
        (TASK,))] == failed_ids
    db.close()


# A second explicit run does not reconstruct again.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "orphan-once.db"
    run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    orphan_pre_fix_state(db)
    db.close()
    run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    assert event_types(db, "technical_exception_reconstructed") == ["technical_exception_reconstructed"]
    assert exceptions(db)[0][3:5] == ("pending", 1)
    db.close()
    run(db_path=path, adapter=WritingTimeoutAdapter([1000]), execution_mode="sequential")
    db = sqlite3.connect(path)
    assert event_types(db, "technical_exception_reconstructed") == ["technical_exception_reconstructed"]
    assert exceptions(db)[0][3:5] == ("resolved", 2)
    db.close()


# A normal task is never reconstructed into an exception.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "normal-no-reconstruct.db"
    result = run(db_path=path, adapter=WritingTimeoutAdapter([1000]), execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert event_types(db, "technical_exception_reconstructed") == []
    assert reconstruct_orphaned_exception(db, TASK) is None
    assert exceptions(db) == []
    db.close()


# Contract-invalid orphaned state restores the original error code.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "orphan-contract.db"

    class WrongRoleAdapter:
        def complete(self, request, timeout_seconds):
            role = request["task_type"]
            number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
            if role == "planning":
                return plan(number)
            if role == "writing":
                return prose(1100)
            if role == "review_world":
                return reviewer("character_plot")
            return reviewer(ROLES[role])

    run(db_path=path, adapter=WrongRoleAdapter(), execution_mode="sequential")
    db = sqlite3.connect(path)
    failed = latest_failed_call(db)
    orphan_pre_fix_state(db)
    reconstructed = reconstruct_orphaned_exception(db, TASK)
    queued = exceptions(db)
    details = json.loads(db.execute(
        "select details_json from exception_queue where exception_id=?", (reconstructed,)).fetchone()[0])
    assert queued[0][1:5] == ("reviewing", "CONTRACT_PAYLOAD_INVALID", "pending", 0)
    assert details["reconstructed_from_orphaned_state"] is True
    assert details["harness_call_id"] == failed[0]
    assert reconstruct_orphaned_exception(db, TASK) is None
    db.close()


# Direct reopen keeps a single open record.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "idempotent.db"
    run(db_path=path, adapter=WritingTimeoutAdapter([1000], timeout_first=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    exception_id = exceptions(db)[0][0]
    start_technical_retry(db, TASK)
    assert exceptions(db)[0][3:5] == ("handling", 1)
    again = queue_technical_exception(
        db, TASK, source_node="reviewing",
        error=ContractFormatError("invalid", code="CONTRACT_PAYLOAD_INVALID"),
        checkpoint={"scene_id": SCENE})
    assert again == exception_id
    assert len(exceptions(db)) == 1
    assert exceptions(db)[0][1:5] == ("reviewing", "CONTRACT_PAYLOAD_INVALID", "pending", 1)
    failed = json.loads(db.execute(
        "select payload_json from task_events where task_id=? and event_type='technical_retry_failed'",
        (TASK,)).fetchone()[0])
    assert failed["exception_id"] == exception_id
    assert failed["source_node"] == "reviewing"
    assert failed["error_code"] == "CONTRACT_PAYLOAD_INVALID"
    db.close()


class WritingThenPlotInvalidAdapter:
    def __init__(self):
        self.calls, self.writes = [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            self.writes += 1
            if self.writes == 1:
                raise TimeoutError("The read operation timed out")
            return prose(1100)
        if role == "memory_extraction":
            raise AssertionError("reviewer contract failure must not call Memory")
        if role == "review_plot":
            payload = reviewer("character_plot")["payload"]
            payload["progression_assessment"] = {
                "status": "partially_achieved",
                "achieved_items": payload["progression_assessment"]["achieved_items"],
                "missing_items": [],
            }
            return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}
        return reviewer(ROLES[role])


# Same exception_id moves from writing timeout to reviewing contract failure.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "source-node-update.db"
    adapter = WritingThenPlotInvalidAdapter()
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    first_row = exceptions(db)[0]
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert first_row[1:5] == ("writing", "TECHNICAL_ERROR", "pending", 0)
    exception_id = first_row[0]
    content_before = task_row(db)[:3]
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)[0]
    row = task_row(db)
    failed = json.loads(db.execute(
        "select payload_json from task_events where task_id=? and event_type='technical_retry_failed' order by rowid desc limit 1",
        (TASK,)).fetchone()[0])
    plot_calls = db.execute(
        "select harness_call_id,status from harness_calls where task_id=? and agent_type='review_plot' order by started_at",
        (TASK,)).fetchall()
    assert second["scenes"][0]["final_status"] == "exception_pending"
    assert queued[0] == exception_id
    assert queued[1:5] == ("reviewing", "CONTRACT_PAYLOAD_INVALID", "pending", 1)
    assert row[:3] == content_before
    assert row[3] == 1
    assert row[7] == exception_id
    assert failed["exception_id"] == exception_id
    assert failed["source_node"] == "reviewing"
    assert failed["error_code"] == "CONTRACT_PAYLOAD_INVALID"
    assert failed["harness_call_id"] == plot_calls[-1][0]
    assert failed["retry_count"] == 1
    assert [item[1] for item in plot_calls] == ["contract_invalid", "contract_invalid"]
    db.close()

class WritingParseErrorAdapter:
    def __init__(self, *, extra=True, truncated=False):
        self.extra, self.truncated, self.calls = extra, truncated, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            if self.truncated:
                raise ModelResponseParseError(
                    "MODEL_OUTPUT_TRUNCATED: Unterminated string",
                    error_code="MODEL_OUTPUT_TRUNCATED",
                    content='{"contract_type":"ProseDraft","payload":{"text":"潮',
                    finish_reason="length", usage={"completion_tokens": 8},
                    parse_error="Unterminated string",
                )
            raise ModelResponseParseError(
                "MODEL_RESPONSE_JSON_INVALID: Extra data",
                error_code="MODEL_RESPONSE_JSON_INVALID",
                content='{"a":1}{"b":2}',
                finish_reason="stop", usage=None,
                parse_error="Extra data",
            )
        raise AssertionError("parse failure must not continue past writing")


# 13 / 14. Unparseable writing JSON is technical: no draft, no content count.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "parse-extra.db"
    result = run(db_path=path, adapter=WritingParseErrorAdapter(), execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    row = task_row(db)
    audit = json.loads(db.execute(
        "select error_json from harness_calls where agent_type='writing' order by started_at desc limit 1"
    ).fetchone()[0])
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert queued[0][1:4] == ("writing", "MODEL_RESPONSE_JSON_INVALID", "pending")
    assert row[:3] == (1, 0, 0)
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert audit["error_code"] == "MODEL_RESPONSE_JSON_INVALID"
    assert audit["content_length"] > 0
    assert audit["content_hash"]
    assert audit["response_excerpt"]
    assert audit["finish_reason"] == "stop"
    assert "Extra data" in audit["parse_error"]
    db.close()


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "parse-truncated.db"
    result = run(db_path=path, adapter=WritingParseErrorAdapter(truncated=True), execution_mode="sequential")
    db = sqlite3.connect(path)
    queued = exceptions(db)
    audit = json.loads(db.execute(
        "select error_json from harness_calls where agent_type='writing' order by started_at desc limit 1"
    ).fetchone()[0])
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert queued[0][2] == "MODEL_OUTPUT_TRUNCATED"
    assert task_row(db)[:3] == (1, 0, 0)
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert audit["error_code"] == "MODEL_OUTPUT_TRUNCATED"
    assert audit["finish_reason"] == "length"
    db.close()


print("exception queue ok")

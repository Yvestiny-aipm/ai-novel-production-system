"""Fixed regression tests for the authoritative prose length quality gate."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import PLANNING_PROMPT_VERSION
from backend.prose_length import (DEFAULT_TARGET_WORD_COUNT, GATE_MIN_CHARACTER_COUNT,
    MAX_CHARACTER_COUNT, MIN_CHARACTER_COUNT, PREFERRED_SOFT_MAX, PREFERRED_SOFT_MIN,
    WRITING_PROMPT_VERSION, actual_character_count, length_revision_feedback,
    planning_length_rework_feedback, validate_prose_length)
from backend.siliconflow import (build_chat_messages, first_draft_writing_instruction,
    writing_length_edit_instruction, writing_quality_edit_instruction)
from integration.run_real_test import run, save_draft
from integration.seed_real_test import seed


def prose(size, reported=1250):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": "潮" * size, "word_count": reported, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


# Whitespace never counts; all remaining visible characters do.
assert GATE_MIN_CHARACTER_COUNT == 800
assert MIN_CHARACTER_COUNT == 1000
assert MAX_CHARACTER_COUNT == 2300
assert WRITING_PROMPT_VERSION == "prose_quality_v8"
assert actual_character_count(" 潮\n痕\t") == 2
for size, status, reason in ((0, "failed", "empty_text"), (346, "failed", "under_length"),
                             (799, "failed", "under_length"), (800, "passed", None),
                             (999, "passed", None), (1000, "passed", None),
                             (1250, "passed", None), (1500, "passed", None),
                             (1501, "passed", None), (2300, "passed", None),
                             (2301, "failed", "over_length")):
    result = validate_prose_length("潮" * size)
    assert (result["actual_character_count"], result["length_validation_status"], result["length_validation_reason"]) == (size, status, reason)


def failed_draft(draft_id, size, reason, attempt=1):
    return {
        "draft_id": draft_id, "text": "潮" * size, "actual_character_count": size,
        "length_validation_status": "failed", "length_validation_reason": reason,
        "content_attempt_in_plan": attempt,
    }


expand = length_revision_feedback(failed_draft("s_draft_v1", 682, "under_length"))
assert expand["adjustment_direction"] == "expand"
assert expand["character_delta_to_target"] == 1250 - 682
assert expand["minimum_character_count"] == MIN_CHARACTER_COUNT
assert expand["required_minimum_character_delta"] == MIN_CHARACTER_COUNT - 682
assert expand["required_maximum_character_delta"] == MAX_CHARACTER_COUNT - 682
assert expand["preferred_character_delta"] == 1250 - 682
assert expand["preferred_output_minimum"] == PREFERRED_SOFT_MIN
assert expand["preferred_output_maximum"] == PREFERRED_SOFT_MAX
assert expand["previous_text"] == "潮" * 682
assert "previous_model_reported_word_count" not in expand
trim = length_revision_feedback(failed_draft("s_draft_v2", 2317, "over_length", 2))
assert trim["adjustment_direction"] == "trim" and trim["character_delta_to_target"] == 1250 - 2317
assert trim["required_minimum_character_delta"] == 2317 - MAX_CHARACTER_COUNT
assert trim["preferred_character_delta"] == 2317 - 1250
assert length_revision_feedback({"length_validation_status": "passed", "length_validation_reason": None}) is None

# 5/6. gates_7 quantitative deltas: 683 expand, 2398 trim.
gates7_expand = length_revision_feedback(failed_draft("g7_v1", 683, "under_length"))
assert gates7_expand["required_minimum_character_delta"] == 317
assert gates7_expand["required_maximum_character_delta"] == MAX_CHARACTER_COUNT - 683
assert gates7_expand["preferred_character_delta"] == 567
assert gates7_expand["character_delta_to_target"] == 567
assert gates7_expand["approximate_output_ratio"] == 1.83
gates7_trim = length_revision_feedback(failed_draft("g7_v2", 2398, "over_length", 2))
assert gates7_trim["required_minimum_character_delta"] == 2398 - MAX_CHARACTER_COUNT
assert gates7_trim["required_maximum_character_delta"] == 2398 - MIN_CHARACTER_COUNT
assert gates7_trim["preferred_character_delta"] == 2398 - 1250
assert gates7_trim["character_delta_to_target"] == 1250 - 2398
assert gates7_trim["approximate_output_ratio"] == round(1250 / 2398, 2)
assert gates7_expand["preferred_output_minimum"] == 1200
assert gates7_trim["preferred_output_maximum"] == 1350

# 1-4/7-10. Message structure is a pure function and keeps the edit after previous_text.
first_request = {"contract_type": "ProseDraft", "input": {
    "context_pack": {"pack_id": "p1"}, "scene_plan": {"payload": {"scene_goal": "推进"}},
}}
first_messages = build_chat_messages(first_request)
assert [item["role"] for item in first_messages] == ["system", "user", "user"]
assert "contract_type" in first_messages[0]["content"] and "ProseDraft" in first_messages[0]["content"]
assert "revision_feedback" not in first_messages[1]["content"]
assert first_messages[2]["content"] == first_draft_writing_instruction()
assert "1000～2300" in first_messages[2]["content"] and "1200～1350" in first_messages[2]["content"]
assert "800～2300" not in first_messages[2]["content"]
assert "不能只改word_count" in first_messages[2]["content"]
assert "超过2300不合格" in first_messages[2]["content"]
assert "必须压到硬上限以下" in first_messages[2]["content"]
assert "不是官方计数" in first_messages[2]["content"]
assert "must_not_happen" in first_messages[2]["content"]
assert "knowledge_boundary" in first_messages[2]["content"]
assert "已批准世界规则" in first_messages[2]["content"]

under_request = {"contract_type": "ProseDraft", "input": {
    "context_pack": {"pack_id": "p1"}, "scene_plan": {"payload": {"scene_goal": "推进"}},
    "revision_feedback": gates7_expand,
}}
over_request = {"contract_type": "ProseDraft", "input": {
    "context_pack": {"pack_id": "p1"}, "scene_plan": {"payload": {"scene_goal": "推进"}},
    "revision_feedback": gates7_trim,
}}
under_messages = build_chat_messages(under_request)
over_messages = build_chat_messages(over_request)
assert under_messages[1]["content"].index("revision_feedback") < under_messages[1]["content"].index("previous_text")
assert gates7_expand["previous_text"] in under_messages[1]["content"]
assert gates7_expand["previous_text"] not in under_messages[0]["content"]
assert "context_pack" in under_messages[1]["content"] and "scene_plan" in under_messages[1]["content"]
assert under_messages[2]["content"] == writing_length_edit_instruction(gates7_expand)
assert over_messages[2]["content"] == writing_length_edit_instruction(gates7_trim)
assert under_messages[2]["content"] != over_messages[2]["content"]
assert gates7_expand["previous_text"] not in under_messages[2]["content"]
assert "至少增加317" in under_messages[2]["content"] and "建议增加567" in under_messages[2]["content"]
assert "写得更具体" in under_messages[2]["content"]
assert "禁止交回同一篇" in under_messages[2]["content"]
assert "必须加到硬下限以上" in under_messages[2]["content"]
assert "会被立即阻断" in under_messages[2]["content"]
assert "不得新增未铺垫人物、地点、世界机制" in under_messages[2]["content"]
assert "不得让灯塔具备保存与展示记忆以外的能力" in under_messages[2]["content"]
assert "至少删除98" in over_messages[2]["content"] and "建议删除1148" in over_messages[2]["content"]
assert "真正删除" in over_messages[2]["content"]
assert "禁止交回同一篇" in over_messages[2]["content"]
assert "必须删到硬上限以下" in over_messages[2]["content"]
assert "会被立即阻断" in over_messages[2]["content"]
assert "不能只改word_count" in over_messages[2]["content"]
assert "不得新增未铺垫人物" not in over_messages[2]["content"]
assert "写得更具体" not in over_messages[2]["content"]
assert "整篇不动" not in over_messages[2]["content"]
for instruction in (under_messages[2]["content"], over_messages[2]["content"]):
    assert "1000～2300" in instruction and "1200～1350" in instruction
    assert "800～2300" not in instruction
    assert "后端实算" in instruction
    assert "不是官方计数" in instruction
    assert "1287" not in instruction
assert WRITING_PROMPT_VERSION == "prose_quality_v8"
reported_trim = length_revision_feedback({
    **failed_draft("h_draft_v2", 1622, "over_length", 2),
    "model_reported_word_count": 1287,
})
assert reported_trim["previous_model_reported_word_count"] == 1287
assert reported_trim["previous_actual_character_count"] == 1622
reported_trim_text = writing_length_edit_instruction(reported_trim)
assert "1287" in reported_trim_text and "1622" in reported_trim_text
assert "以1622为准" in reported_trim_text
assert "后端实算" in reported_trim_text
assert "必须删到硬上限以下" in reported_trim_text
assert "会被立即阻断" in reported_trim_text
assert "不得新增未铺垫人物" not in reported_trim_text
quality_only = {
    "failure_type": "quality_report",
    "reviewer_findings": [{
        "reviewer_role": "world_consistency", "result": "failed", "issue_count": 1,
        "findings": ["世界规则冲突"],
    }],
}
both_messages = build_chat_messages({"contract_type": "ProseDraft", "input": {
    "scene_plan": {"payload": {"scene_goal": "推进"}},
    "revision_feedback": gates7_expand,
    "quality_revision_feedback": quality_only,
}})
assert both_messages[2]["content"] == writing_length_edit_instruction(gates7_expand)
assert both_messages[3]["content"] == writing_quality_edit_instruction(quality_only)
assert "不得新增未铺垫人物" in both_messages[2]["content"]
assert "世界规则冲突" in both_messages[3]["content"]
assert "必须改写或删除" in both_messages[3]["content"]
assert "保留已通过内容" not in both_messages[3]["content"]
assert "禁止原样返回" in both_messages[3]["content"]
assert "禁止只改结构化字段或word_count" in both_messages[3]["content"]
assert planning_length_rework_feedback([
    {"length_validation_reason": "under_length", "actual_character_count": 682},
    {"length_validation_reason": "under_length", "actual_character_count": 624},
    {"length_validation_reason": "over_length", "actual_character_count": 2317},
])["reason"] == "consecutive_length_failures"


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "audit.db"
    db, book = seed(path)
    # The model's lie never becomes the formal word_count.
    draft_id, _ = save_draft(db, book, book + "_chapter_1", book + "_scene_1", prose(346, 1250), "hc_audit")
    row = db.execute("select word_count,model_reported_word_count,actual_character_count,length_validation_status,length_validation_reason from prose_drafts where draft_id=?", (draft_id,)).fetchone()
    assert row == (346, 1250, 346, "failed", "under_length")
    draft_id, _ = save_draft(db, book, book + "_chapter_1", book + "_scene_1", prose(1250, 500), "hc_audit_2", version=2)
    row = db.execute("select word_count,model_reported_word_count,actual_character_count,length_validation_status from prose_drafts where draft_id=?", (draft_id,)).fetchone()
    assert row == (1250, 500, 1250, "passed")
    db.close()
    # Reopening an existing test database applies no migration twice and
    # leaves both immutable draft revisions intact.
    db, _ = seed(path)
    assert db.execute("select count(*) from prose_drafts").fetchone()[0] == 2
    assert {row[1] for row in db.execute("pragma table_info(prose_drafts)")} >= {
        "model_reported_word_count", "actual_character_count",
        "length_validation_status", "length_validation_reason",
    }
    db.close()


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": ["查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type":"new_clue","target_key":"灯塔线索","before_state":"未知","expected_after_state":"发现线索","acceptance_criterion":"正文出现线索"}],
    }}


def reviewer(role, number):
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status":"achieved","achieved_items":[{"progress_type":"new_clue","target_key":"灯塔线索","before_state":"未知","after_state":"发现线索","evidence_text":"潮","evidence_location":"draft.text"}],"missing_items":[],"evidence":"潮"},
    }}


class LengthSequenceAdapter:
    """Four length drafts stay on the same plan; Planning is not involved."""
    def __init__(self):
        self.calls = []
        self.writing_sizes = [346, 799, 2301, 1000]

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            size = self.writing_sizes.pop(0) if number == 1 else 1000
            return prose(size, 1250)
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
                "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "潮",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}[role], number)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "length-rework.db"
    adapter = LengthSequenceAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    # First three failed lengths stay on Plan v1. The fourth draft (1000)
    # enters review; Planning is never asked to fix model length.
    rows = db.execute("select draft_version,plan_version,content_attempt_in_plan,content_attempt_total,word_count,length_validation_status,length_validation_reason from prose_drafts where scene_id=? order by draft_version", ("realtest_tide_archive_scene_1",)).fetchall()
    assert rows == [(1, 1, 1, 1, 346, "failed", "under_length"), (2, 1, 2, 2, 799, "failed", "under_length"), (3, 1, 3, 3, 2301, "failed", "over_length"), (4, 1, 4, 4, 1000, "passed", None)]
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone() == (1, 0, 0)
    assert db.execute("select count(*) from quality_reports where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    assert db.execute("select draft_id from quality_reports where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0].endswith("draft_v4")
    review_calls = [call for call in adapter.calls if call["task_type"].startswith("review_")]
    assert len(review_calls) == 3
    assert {call["input"]["draft"]["payload"]["word_count"] for call in review_calls} == {1000}
    length_events = [row[0] for row in db.execute("select event_type from task_events where task_id=? and event_type in ('length_rework_requested','length_failure_blocked','rework_requested') order by created_at", ("realtest_tide_archive_scene_1_task",))]
    assert length_events == ["length_rework_requested", "length_rework_requested", "length_rework_requested"]
    assert db.execute("select count(*) from scene_plans where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert result["scenes"][0]["length_failure_count_in_plan"] == 3
    assert result["scenes"][0]["length_failure_count_total"] == 3
    assert result["scenes"][0]["semantic_failure_count_in_plan"] == 0
    assert result["scenes"][0]["semantic_failure_count_total"] == 0
    writing_calls = [call for call in adapter.calls if call["task_type"] == "writing"]
    planning_calls = [call for call in adapter.calls if call["task_type"] == "planning"]
    assert "revision_feedback" not in writing_calls[0]["input"]
    assert "previous_text" not in writing_calls[0]["input"]
    assert len(planning_calls) == 1
    assert "planning_rework_feedback" not in planning_calls[0]["input"]
    assert writing_calls[3]["input"]["revision_feedback"]["adjustment_direction"] == "trim"
    assert writing_calls[3]["input"]["revision_feedback"]["previous_actual_character_count"] == 2301
    assert {call["prompt_version"] for call in writing_calls} == {WRITING_PROMPT_VERSION}
    assert {call["prompt_version"] for call in planning_calls} == {PLANNING_PROMPT_VERSION}
    db.close()


def writing_calls(adapter):
    return [call for call in adapter.calls if call["task_type"] == "writing"]


class FeedbackSequenceAdapter(LengthSequenceAdapter):
    def __init__(self, sizes):
        super().__init__()
        self.writing_sizes = list(sizes)


# 2/4/5/9/10. A 682-character miss produces expand feedback and a new Harness call.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "expand-feedback.db"
    adapter = FeedbackSequenceAdapter([682, 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    calls = writing_calls(adapter)
    assert "revision_feedback" not in calls[0]["input"]
    feedback = calls[1]["input"]["revision_feedback"]
    first_id = "realtest_tide_archive_scene_1_draft_v1"
    first_text = db.execute("select text,actual_character_count,length_validation_status from prose_drafts where draft_id=?", (first_id,)).fetchone()
    assert first_text == ("潮" * 682, 682, "failed")
    assert feedback["previous_draft_id"] == first_id
    assert feedback["previous_text"] == "潮" * 682
    assert feedback["adjustment_direction"] == "expand"
    assert feedback["character_delta_to_target"] == 1250 - 682
    assert feedback["required_minimum_character_delta"] == 318
    assert feedback["required_maximum_character_delta"] == MAX_CHARACTER_COUNT - 682
    assert feedback["preferred_character_delta"] == 568
    assert feedback["approximate_output_ratio"] == round(1250 / 682, 2)
    assert calls[1]["input"]["checkpoint"] != calls[0]["input"]["checkpoint"]
    assert not result["scenes"][0]["reused_calls"]
    assert db.execute("select text from prose_drafts where draft_id=?", (first_id,)).fetchone()[0] == "潮" * 682
    db.close()


# 3/4/6. A 2317-character miss produces trim feedback; reviewers only see the passing draft.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "trim-feedback.db"
    adapter = FeedbackSequenceAdapter([2317, 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    calls = writing_calls(adapter)
    feedback = calls[1]["input"]["revision_feedback"]
    first_id = "realtest_tide_archive_scene_1_draft_v1"
    assert feedback["adjustment_direction"] == "trim"
    assert feedback["character_delta_to_target"] == 1250 - 2317
    assert feedback["previous_draft_id"] == first_id
    assert feedback["previous_text"] == "潮" * 2317
    assert db.execute("select text,actual_character_count from prose_drafts where draft_id=?", (first_id,)).fetchone() == ("潮" * 2317, 2317)
    review_calls = [call for call in adapter.calls if call["task_type"].startswith("review_")]
    assert {call["input"]["draft"]["payload"]["word_count"] for call in review_calls} == {1000}
    assert all("潮" * 2317 not in json.dumps(call["input"]["draft"], ensure_ascii=False) for call in review_calls)
    db.close()


# 4/5/8. Four length failures on the same plan block; over/under share one counter.
class BlockAfterFourAdapter(LengthSequenceAdapter):
    def __init__(self):
        super().__init__()
        self.writing_sizes = [682, 624, 384, 2317]


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "fourth-length-blocks.db"
    adapter = BlockAfterFourAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "blocked"
    assert result["scenes"][0]["current_node"] == "writing"
    assert result["scenes"][0]["block_reason"] == "length_attempts_exhausted"
    rows = db.execute("select draft_version,plan_version,actual_character_count,length_validation_reason from prose_drafts where scene_id=? order by draft_version", ("realtest_tide_archive_scene_1",)).fetchall()
    assert rows == [(1, 1, 682, "under_length"), (2, 1, 624, "under_length"), (3, 1, 384, "under_length"), (4, 1, 2317, "over_length")]
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone() == (1, 0, 0, "blocked")
    assert db.execute("select coalesce(max(plan_version),0) from scene_plans where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    writing = writing_calls(adapter)
    assert writing[1]["input"]["revision_feedback"]["adjustment_direction"] == "expand"
    assert writing[1]["input"]["revision_feedback"]["character_delta_to_target"] == 1250 - 682
    assert writing[2]["input"]["revision_feedback"]["previous_actual_character_count"] == 624
    assert writing[3]["input"]["revision_feedback"]["previous_actual_character_count"] == 384
    planning = [call for call in adapter.calls if call["task_type"] == "planning"]
    assert len(planning) == 1
    assert "planning_rework_feedback" not in planning[0]["input"]
    assert result["scenes"][0]["length_failure_count_in_plan"] == 4
    assert result["scenes"][0]["length_failure_count_total"] == 4
    assert result["scenes"][0]["semantic_failure_count_in_plan"] == 0
    assert [row[0] for row in db.execute("select status from task_states where scene_id!=? order by scene_id", ("realtest_tide_archive_scene_1",))] == ["queued"] * 4
    db.close()


# 21 / 22. gates_17 scene 4: 2418→982→2338 may still write a 4th length draft; 2411 then blocks.
class Gates17LengthAdapter(LengthSequenceAdapter):
    def __init__(self, sizes):
        super().__init__()
        self.writing_sizes = list(sizes)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gates17-fourth-allowed.db"
    adapter = Gates17LengthAdapter([2418, 799, 2338, 1250])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert [call["task_type"] for call in adapter.calls].count("planning") == 1
    assert [call["task_type"] for call in adapter.calls].count("writing") == 4
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert db.execute("select draft_version,plan_version,actual_character_count,length_validation_reason from prose_drafts where scene_id=? order by draft_version", ("realtest_tide_archive_scene_1",)).fetchall() == [
        (1, 1, 2418, "over_length"), (2, 1, 799, "under_length"), (3, 1, 2338, "over_length"), (4, 1, 1250, None),
    ]
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone() == (1, 0, 0, "waiting_confirmation")
    db.close()


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "gates17-fourth-blocks.db"
    adapter = Gates17LengthAdapter([2418, 799, 2338, 2411])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert [call["task_type"] for call in adapter.calls].count("planning") == 1
    assert result["scenes"][0]["final_status"] == "blocked"
    assert result["scenes"][0]["block_reason"] == "length_attempts_exhausted"
    assert db.execute("select actual_character_count from prose_drafts where scene_id=? order by draft_version", ("realtest_tide_archive_scene_1",)).fetchall() == [(2418,), (799,), (2338,), (2411,)]
    assert db.execute("select coalesce(max(plan_version),0) from scene_plans where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    db.close()


# 11. A technical timeout creates neither fake revision_feedback nor a content count.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout-feedback.db"

    class TimeoutFirstAdapter(LengthSequenceAdapter):
        def complete(self, request, timeout_seconds):
            self.calls.append(request)
            if request["task_type"] == "writing":
                raise TimeoutError("The read operation timed out")
            role = request["task_type"]
            number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
            if role == "planning":
                return plan(number)
            raise AssertionError("timeout must happen before reviewers")

    adapter = TimeoutFirstAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone() == (1, 0, 0, "exception_pending")
    assert db.execute("select count(*) from prose_drafts where scene_id=?", ("realtest_tide_archive_scene_1",)).fetchone()[0] == 0
    assert all("revision_feedback" not in call["input"] for call in adapter.calls)
    db.close()


# 12. A prose_length_v2 success must not be reused after the Writing prompt upgrade.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v2-reuse.db"

    class TimeoutFirstAdapter(LengthSequenceAdapter):
        def complete(self, request, timeout_seconds):
            self.calls.append(request)
            if request["task_type"] == "writing":
                raise TimeoutError("The read operation timed out")
            number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
            return plan(number)

    first_adapter = TimeoutFirstAdapter()
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    writing_request = next(call for call in first_adapter.calls if call["task_type"] == "writing")
    planted = dict(writing_request)
    planted["prompt_version"] = "prose_length_v2"
    planted_text = "旧提示版本不能复用" * 80
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_v2", "realtest_tide_archive_scene_1_task", "writing", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(prose(len(planted_text)), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = FeedbackSequenceAdapter([1000])
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert writing_calls(second_adapter)
    assert all(call["prompt_version"] == WRITING_PROMPT_VERSION for call in writing_calls(second_adapter))
    assert "hc_planted_v2" not in (second["scenes"][0].get("reused_calls") or [])
    draft_text = db.execute("select text from prose_drafts where scene_id=? order by draft_version", ("realtest_tide_archive_scene_1",)).fetchone()[0]
    assert draft_text == "潮" * 1000
    assert planted_text not in draft_text
    db.close()

# Same-scene identical short drafts are duplicate_draft_content, not more length failures.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "same-short-hash.db"
    adapter = FeedbackSequenceAdapter([710, 710, 710])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    writing = writing_calls(adapter)
    assert len(writing) == 2
    assert result["scenes"][0]["final_status"] == "blocked"
    assert result["scenes"][0]["block_reason"] == "duplicate_draft_content"
    length_events = [row[0] for row in db.execute(
        "select event_type from task_events where task_id=? and event_type in "
        "('length_rework_requested','length_failure_blocked') order by created_at",
        ("realtest_tide_archive_scene_1_task",))]
    assert length_events == ["length_rework_requested"]
    hashes = [row[0] for row in db.execute(
        "select draft_hash from prose_drafts where scene_id=? order by draft_version",
        ("realtest_tide_archive_scene_1",))]
    assert len(hashes) == 2 and hashes[0] == hashes[1]
    db.close()


print("prose length gate ok")

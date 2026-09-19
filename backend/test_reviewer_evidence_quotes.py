"""Safe quote-style evidence normalize. No semantic fuzzy match."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import (ContractFormatError, EVIDENCE_QUOTE_NORMALIZATION_RULE,
    REVIEWER_PROMPT_VERSION, normalize_reviewer_evidence,
    validate_reviewer_result_against_input)
from integration.run_real_test import run


SCENE = "realtest_tide_archive_scene_1"
TASK = SCENE + "_task"
CN_DOUBLE_0107 = "“0107”"
CN_SINGLE_0107 = "‘0107’"
ASCII_DOUBLE_0107 = '"0107"'
CN_DOUBLE_ARCHIVE = "“档案室底层”"
CN_SINGLE_ARCHIVE = "‘档案室底层”".replace("”", "’")
QUOTE_CORE = f"林照在档案室停住。门牌写着{CN_DOUBLE_0107}。他走进{CN_DOUBLE_ARCHIVE}。管理员挡住门口。"
QUOTE_DRAFT = QUOTE_CORE + ("档案纸页在灯光下翻动。" * 120)
EXACT_EVIDENCE = "林照在档案室停住。"
PLAN_ITEM = {
    "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
    "after_state": "发现线索", "evidence_text": EXACT_EVIDENCE, "evidence_location": "draft.text",
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


def long_prose(text=QUOTE_DRAFT):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": text, "word_count": 1250, "target_word_count": 1250,
        "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role="character_plot", *, item=None, status="achieved", findings=None, suggestions=None):
    payload = {
        "reviewer_role": role, "result": "passed",
        "findings": list(findings or []), "suggestions": list(suggestions or []),
        "issue_count": len(findings or []), "severity": "ordinary", "impact_scope": "local",
        "true_conflict_candidate": False, "scene_state": STATE,
    }
    if role == "character_plot":
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
        "evidence": EXACT_EVIDENCE, "evidence_location": "draft.payload.text",
        "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


def plot_input(text=QUOTE_DRAFT):
    return {"scene_plan": plan(1), "draft": long_prose(text)}


def quote_item(evidence):
    return {**PLAN_ITEM, "evidence_text": evidence}


class QuoteAdapter:
    def __init__(self, *, plot_item=None, first_status="achieved", corrected_item=None,
                 timeout_style=False, timeout_plot=False, draft_text=QUOTE_DRAFT):
        self.plot_item = plot_item or PLAN_ITEM
        self.first_status = first_status
        self.corrected_item = corrected_item
        self.timeout_style = timeout_style
        self.timeout_plot = timeout_plot
        self.draft_text = draft_text
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return long_prose(self.draft_text)
        if role == "memory_extraction":
            return memory()
        if role == "review_style" and self.timeout_style:
            raise TimeoutError("The read operation timed out")
        if role == "review_plot":
            if self.timeout_plot:
                raise TimeoutError("The read operation timed out")
            correction = request["input"].get("reviewer_contract_correction")
            if correction and self.corrected_item is not None:
                return reviewer(item=self.corrected_item, status="achieved")
            return reviewer(item=self.plot_item, status=self.first_status)
        return reviewer(ROLES[role])


def expect_invalid(item=None, text=QUOTE_DRAFT, **kwargs):
    response = reviewer(item=item, **kwargs)
    try:
        validate_reviewer_result_against_input(response, "review_plot", plot_input(text))
    except ContractFormatError as error:
        assert error.code == "CONTRACT_PAYLOAD_INVALID"
        return error
    raise AssertionError("illegal plot evidence accepted")


def saved_plot(db):
    return db.execute(
        "select harness_call_id,status,response_json from harness_calls "
        "where task_id=? and agent_type='review_plot' order by started_at",
        (TASK,)).fetchall()


assert REVIEWER_PROMPT_VERSION == "reviewer_contract_v8"
assert CN_SINGLE_ARCHIVE == "‘档案室底层’"
assert CN_DOUBLE_0107 in QUOTE_DRAFT
assert CN_SINGLE_0107 not in QUOTE_DRAFT
assert CN_DOUBLE_ARCHIVE in QUOTE_DRAFT
assert CN_SINGLE_ARCHIVE not in QUOTE_DRAFT


# 1. Exact evidence is left untouched.
exact = reviewer(item=quote_item(EXACT_EVIDENCE))
before = copy.deepcopy(exact)
assert normalize_reviewer_evidence(exact, plot_input()) == 0
assert exact == before
assert "reviewer_evidence_normalization_applied" not in exact
assert "evidence_normalization_audit" not in exact["payload"]["progression_assessment"]["achieved_items"][0]
validate_reviewer_result_against_input(exact, "review_plot", plot_input())
assert exact["payload"]["progression_assessment"]["achieved_items"][0]["evidence_text"] == EXACT_EVIDENCE


# 2 / 4 / 5. Chinese single vs double quotes are rewritten to the draft span.
cn = reviewer(item=quote_item(CN_SINGLE_0107), findings=[], suggestions=["可保留档案室气味"])
validate_reviewer_result_against_input(cn, "review_plot", plot_input())
item = cn["payload"]["progression_assessment"]["achieved_items"][0]
assert item["evidence_text"] == CN_DOUBLE_0107
assert item["evidence_text"] in QUOTE_DRAFT
assert item["evidence_text"] == QUOTE_DRAFT[item["evidence_normalization_audit"]["start_offset"]:
                                           item["evidence_normalization_audit"]["end_offset"]]
assert item["evidence_normalization_audit"] == {
    "rule": EVIDENCE_QUOTE_NORMALIZATION_RULE,
    "original_evidence_text": CN_SINGLE_0107,
    "exact_draft_evidence_text": CN_DOUBLE_0107,
    "start_offset": QUOTE_DRAFT.index(CN_DOUBLE_0107),
    "end_offset": QUOTE_DRAFT.index(CN_DOUBLE_0107) + len(CN_DOUBLE_0107),
}
assert cn["reviewer_evidence_normalization_applied"] is True
assert cn["reviewer_evidence_normalization_count"] == 1
assert cn["payload"]["suggestions"] == ["可保留档案室气味"]
assert cn["payload"]["findings"] == []
assert cn["payload"]["reviewer_role"] == "character_plot"


# 3. ASCII quotes vs Chinese double quotes.
ascii_quotes = reviewer(item=quote_item(ASCII_DOUBLE_0107))
validate_reviewer_result_against_input(ascii_quotes, "review_plot", plot_input())
ascii_item = ascii_quotes["payload"]["progression_assessment"]["achieved_items"][0]
assert ascii_item["evidence_text"] == CN_DOUBLE_0107
assert ascii_item["evidence_normalization_audit"]["original_evidence_text"] == ASCII_DOUBLE_0107
assert ascii_item["evidence_normalization_audit"]["exact_draft_evidence_text"] == CN_DOUBLE_0107


# 6. One non-quote character still fails.
expect_invalid(quote_item("‘0108’"))
expect_invalid(quote_item("林照在档案室停步。"))


# 7. Punctuation and whitespace still fail.
expect_invalid(quote_item("林照在档案室停住！"))
expect_invalid(quote_item("林照在档案室 停住。"))


# 8. Cross-paragraph splice still fails.
expect_invalid(quote_item("林照在档案室停住。管理员挡住门口。"))


# 9. Multiple normalized hits cannot choose a span.
dup_text = QUOTE_CORE + f"他又看见{CN_DOUBLE_0107}。" + ("档案纸页在灯光下翻动。" * 80)
assert dup_text.count(CN_DOUBLE_0107) == 2
dup = reviewer(item=quote_item(CN_SINGLE_0107))
assert normalize_reviewer_evidence(dup, plot_input(dup_text)) == 0
assert dup["payload"]["progression_assessment"]["achieved_items"][0]["evidence_text"] == CN_SINGLE_0107
expect_invalid(quote_item(CN_SINGLE_0107), text=dup_text)


# 10. Empty evidence still fails and is not rewritten.
empty = reviewer(item=quote_item(""))
assert normalize_reviewer_evidence(empty, plot_input()) == 0
expect_invalid(quote_item(""))


# 11. Quote fix does not skip the rest of Plan validation.
expect_invalid({**quote_item(CN_SINGLE_0107), "after_state": "无关结果"})
expect_invalid({**quote_item(CN_SINGLE_0107), "target_key": "伪造线索"})
expect_invalid({**quote_item(CN_SINGLE_0107), "before_state": "已经找到林澜"})


# 16. gates_17 both quote-style samples become the real draft spans.
for original, exact_span in ((CN_SINGLE_0107, CN_DOUBLE_0107),
                             (CN_SINGLE_ARCHIVE, CN_DOUBLE_ARCHIVE)):
    response = reviewer(item=quote_item(original))
    validate_reviewer_result_against_input(response, "review_plot", plot_input())
    fixed = response["payload"]["progression_assessment"]["achieved_items"][0]
    assert fixed["evidence_text"] == exact_span
    assert fixed["evidence_text"] in QUOTE_DRAFT
    assert fixed["evidence_normalization_audit"]["original_evidence_text"] == original
    assert fixed["evidence_normalization_audit"]["exact_draft_evidence_text"] == exact_span


# 2 / 4 / 12 / 13. End-to-end: Chinese quotes pass, draft and content counts stay put.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "cn-quotes.db"
    draft_before = QUOTE_DRAFT
    adapter = QuoteAdapter(plot_item=quote_item(CN_SINGLE_0107), draft_text=draft_before)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene = result["scenes"][0]
    row = saved_plot(db)[0]
    saved = json.loads(row[2])
    item = saved["payload"]["progression_assessment"]["achieved_items"][0]
    stored_draft = db.execute("select text from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0]
    counts = db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where task_id=?",
        (TASK,)).fetchone()
    assert scene["final_status"] == "waiting_confirmation"
    assert scene["reviewer_correction_called"] is False
    assert scene["reviewer_evidence_normalization_applied"] is True
    assert scene["reviewer_evidence_normalization_count"] == 1
    assert row[1] == "success"
    assert item["evidence_text"] == CN_DOUBLE_0107
    assert item["evidence_text"] in stored_draft
    assert item["evidence_normalization_audit"]["original_evidence_text"] == CN_SINGLE_0107
    assert item["evidence_normalization_audit"]["exact_draft_evidence_text"] == CN_DOUBLE_0107
    assert stored_draft == draft_before
    assert counts == (0, 0, "waiting_confirmation")
    assert [call["task_type"] for call in adapter.calls].count("review_plot") == 1
    assert [call["task_type"] for call in adapter.calls].count("writing") == 1
    db.close()


# 16. Second gates_17 sample also completes the scene.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "cn-archive.db"
    adapter = QuoteAdapter(plot_item=quote_item(CN_SINGLE_ARCHIVE))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    saved = json.loads(saved_plot(db)[0][2])
    item = saved["payload"]["progression_assessment"]["achieved_items"][0]
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert item["evidence_text"] == CN_DOUBLE_ARCHIVE
    assert item["evidence_normalization_audit"]["original_evidence_text"] == CN_SINGLE_ARCHIVE
    db.close()


# 11. Correction responses use the same quote rule, then full Plan checks.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "correct-quotes.db"
    adapter = QuoteAdapter(
        plot_item=quote_item(CN_SINGLE_0107),
        first_status="partially_achieved",
        corrected_item=quote_item(CN_SINGLE_ARCHIVE),
    )
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = saved_plot(db)
    corrected = json.loads(rows[1][2])
    item = corrected["payload"]["progression_assessment"]["achieved_items"][0]
    assert result["scenes"][0]["reviewer_correction_called"] is True
    assert result["scenes"][0]["reviewer_correction_succeeded"] is True
    assert rows[0][1] == "contract_invalid"
    assert rows[1][1] == "success"
    assert item["evidence_text"] == CN_DOUBLE_ARCHIVE
    assert item["evidence_normalization_audit"]["rule"] == EVIDENCE_QUOTE_NORMALIZATION_RULE
    assert result["scenes"][0]["reviewer_evidence_normalization_applied"] is True
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total from task_states where task_id=?",
        (TASK,)).fetchone() == (0, 0)
    db.close()


# 14. Recovery reuses the already-normalized success row and does not restack the audit.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-renorm.db"
    first = QuoteAdapter(plot_item=quote_item(CN_SINGLE_0107), timeout_style=True)
    first_result = run(db_path=path, adapter=first, execution_mode="sequential")
    db = sqlite3.connect(path)
    first_saved = json.loads(saved_plot(db)[0][2])
    first_item = copy.deepcopy(first_saved["payload"]["progression_assessment"]["achieved_items"][0])
    assert first_result["scenes"][0]["final_status"] == "exception_pending"
    assert first_item["evidence_normalization_audit"]["original_evidence_text"] == CN_SINGLE_0107
    db.close()
    second = QuoteAdapter(plot_item=quote_item(CN_SINGLE_0107))
    second_result = run(db_path=path, adapter=second, execution_mode="sequential")
    db = sqlite3.connect(path)
    rows = saved_plot(db)
    reused = json.loads(rows[0][2])
    reused_item = reused["payload"]["progression_assessment"]["achieved_items"][0]
    assert second_result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert rows[0][0] in (second_result["scenes"][0].get("reused_calls") or [])
    assert [call["task_type"] for call in second.calls if call["task_type"] == "review_plot"] == []
    assert reused_item == first_item
    assert reused.get("reviewer_evidence_normalization_count") == 1
    assert "evidence_normalization_audit" in reused_item
    assert list(reused_item.keys()).count("evidence_normalization_audit") == 1
    db.close()


# 15. reviewer_contract_v8 does not reuse a v6 success row.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v6-reuse.db"
    first = QuoteAdapter(timeout_plot=True)
    run(db_path=path, adapter=first, execution_mode="sequential")
    plot_request = next(call for call in first.calls if call["task_type"] == "review_plot")
    planted = dict(plot_request)
    planted["prompt_version"] = "reviewer_contract_v6"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_reviewer_v6", TASK, "review_plot", "mock", "mock",
         json.dumps(planted, ensure_ascii=False),
         json.dumps(reviewer(item=quote_item(CN_SINGLE_0107)), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit()
    db.close()
    second = QuoteAdapter(plot_item=quote_item(CN_SINGLE_0107))
    result = run(db_path=path, adapter=second, execution_mode="sequential")
    assert "hc_planted_reviewer_v6" not in (result["scenes"][0].get("reused_calls") or [])
    assert all(call["prompt_version"] == REVIEWER_PROMPT_VERSION
               for call in second.calls if call["task_type"].startswith("review_"))


print("reviewer evidence quotes ok")

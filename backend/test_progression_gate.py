"""Fixed coverage for all 26 confirmed progression-gate requirements."""
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.progression import (already_has_verified_state, quality_revision_feedback, sync_verified_progression_state,
    validate_requirements, verify_progression)
from backend.harness import ARBITER_PROMPT_VERSION, REVIEWER_PROMPT_VERSION
from backend.prose_length import WRITING_PROMPT_VERSION
from backend.siliconflow import (arbiter_quality_instruction, build_chat_messages, reviewer_plot_instruction,
    reviewer_progression_instruction, writing_quality_edit_instruction)
from integration.run_real_test import aggregate_quality, run, save_draft, save_plan, save_proposal, save_report
from integration.seed_real_test import seed


BASE_REQUIREMENT = {
    "progress_type": "new_clue", "target_key": "潮痕编号", "before_state": "未知",
    "expected_after_state": "潮痕编号A-17", "acceptance_criterion": "正文揭示潮痕编号A-17",
}
BASE_PREVIOUS = {
    "characters": ["林照"], "location": "灯塔", "time_context": "夜晚",
    "events": ["已知线索A", "尚未决定", "口头对峙"], "relationship_changes": ["林照与管理员互不信任"],
    "unresolved_threads": ["林澜失踪案尚未定位"],
}


def state(*, events=(), relationships=(), threads=(), location="灯塔"):
    return {
        "characters": ["林照"], "location": location, "time_context": "夜晚",
        "events": list(events), "relationship_changes": list(relationships),
        "unresolved_threads": list(threads),
    }


def requirement(progress_type, target_key, before, after):
    return {
        "progress_type": progress_type, "target_key": target_key, "before_state": before,
        "expected_after_state": after, "acceptance_criterion": f"正文明确写出{after}",
    }


def plot_review(req, after, evidence, location="draft.text", *, status="achieved"):
    item = {
        "progress_type": req["progress_type"], "target_key": req["target_key"],
        "before_state": req["before_state"], "after_state": after,
        "evidence_text": evidence, "evidence_location": location,
    }
    return {"payload": {"reviewer_role": "character_plot", "progression_assessment": {
        "status": status, "achieved_items": [item] if status == "achieved" else [],
        "missing_items": [] if status == "achieved" else [item],
    }}}


def direct_case(db, book, case, req, after, evidence, accepted, *, previous=BASE_PREVIOUS,
                location="draft.text", previous_scene_id=None, status="achieved"):
    text = f"正文证据：{evidence}。"
    return verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id=f"case_{case}_plan", draft_id=f"case_{case}_draft",
        report_id=f"case_{case}_report", requirements=[req],
        reviews=[plot_review(req, after, evidence, location, status=status)], text=text,
        previous_scene_id=previous_scene_id or book + "_scene_1",
        previous_state=previous, accepted_scene_state=accepted,
    )


# 12/13. Empty, illegal, or vague plans are planning-quality failures.
validate_requirements([BASE_REQUIREMENT])
for bad in (
    [], [{**BASE_REQUIREMENT, "progress_type": "invalid"}],
    [{**BASE_REQUIREMENT, "target_key": "继续调查"}],
    [{**BASE_REQUIREMENT, "expected_after_state": "推进剧情"}],
):
    try:
        validate_requirements(bad)
    except ValueError as error:
        assert str(error) == "plan_progression_missing"
    else:
        raise AssertionError("invalid progression plan accepted")


with tempfile.TemporaryDirectory() as directory:
    db, book = seed(Path(directory) / "direct.db")
    db.execute("pragma foreign_keys=OFF")

    passing = [
        # 1. New clue with draft evidence.
        (1, requirement("new_clue", "潮痕编号", "未知", "潮痕编号A-17"),
         "潮痕编号A-17", "林照发现潮痕编号A-17", state(events=["潮痕编号A-17"])),
        # 2. Consequential decision.
        (2, requirement("decision_or_consequence", "封锁决定", "尚未决定", "林照决定封锁北门"),
         "林照决定封锁北门", "林照决定封锁北门并派人守卫", state(events=["林照决定封锁北门"])),
        # 3. Real relationship change.
        (3, requirement("relationship_change", "林照与管理员", "互不信任", "管理员开始协助林照"),
         "管理员开始协助林照", "管理员把密钥交给林照并开始协助", state(relationships=["管理员开始协助林照"])),
        # 4. Conflict escalates with a consequence.
        (4, requirement("conflict_change", "档案争夺", "口头对峙", "管理员烧毁航海日志"),
         "管理员烧毁航海日志", "管理员点火烧毁航海日志", state(events=["管理员烧毁航海日志"])),
        # 5. Effective new thread.
        (5, requirement("thread_opened", "地下潮声", "未知", "地下室传来林澜的求救录音"),
         "地下室传来林澜的求救录音", "地下室突然传来林澜的求救录音", state(threads=["地下室传来林澜的求救录音"])),
        # 6. Existing thread gains new information.
        (6, requirement("thread_advanced", "林澜失踪", "林澜失踪案尚未定位", "林澜最后出现在北礁"),
         "林澜最后出现在北礁", "日志证实林澜最后出现在北礁", state(threads=["林澜最后出现在北礁"])),
        # 7. Existing thread closes.
        (7, requirement("thread_closed", "林澜失踪", "林澜失踪案尚未定位", "林澜已在北礁获救"),
         "林澜已在北礁获救", "救援队确认林澜已在北礁获救", state(events=["林澜已在北礁获救"])),
        # 18. Valid evidence with a paraphrased scene_state is synced, not failed.
        (18, BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17", state(events=["别的事件"])),
    ]
    for case, req, after, evidence, accepted in passing:
        result = direct_case(db, book, case, req, after, evidence, accepted)
        assert result["progression_status"] == "passed", (case, result)

    failures = [
        # 8. Repeating a known clue is not new progress.
        (8, requirement("new_clue", "旧线索", "未知", "已知线索A"), "已知线索A",
         "林照再次读到已知线索A", state(events=["已知线索A"]), "progression_reuses_previous_state", {}),
        # 9. Investigation without a result.
        (9, requirement("new_clue", "调查结果", "未知", "找到新的航海证据"), "继续调查",
         "林照继续调查", state(events=["继续调查"]), "non_substantive_progression", {}),
        (9.1, requirement("new_clue", "管理员回答", "未知", "管理员说出藏匿地点"), "再次询问同一个问题",
         "林照再次询问同一个问题", state(events=["再次询问同一个问题"]), "non_substantive_progression", {}),
        # 10. Environment and emotion only.
        (10, requirement("character_state_change", "林照", "平静", "林照决定封锁北门"), "雨夜里更加焦虑",
         "雨越下越大，林照更加焦虑", state(events=["雨夜里更加焦虑"]), "non_substantive_progression", {}),
        (10.1, requirement("character_state_change", "林照状态", "未知", "林照负伤"), "林照",
         "镜头仍然只有林照", state(), "non_substantive_progression", {}),
        # 11. Location-only change.
        (11, requirement("goal_milestone", "调查地点", "未知", "码头"), "码头",
         "林照从灯塔走到码头", state(location="码头"), "after_state_missing_from_accepted_scene_state", {}),
        # 14. Reviewer says achieved but supplies no evidence.
        (14, BASE_REQUIREMENT, "潮痕编号A-17", "", state(events=["潮痕编号A-17"]),
         "progression_evidence_not_in_draft", {}),
        # 15. Evidence is absent from the current draft.
        (15, BASE_REQUIREMENT, "潮痕编号A-17", "不存在的证据", state(events=["潮痕编号A-17"]),
         "progression_evidence_not_in_draft", {"text_override": "正文没有这句话"}),
        # 20. Spliced non-contiguous paragraphs are not a draft substring.
        (15.2, BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17。潮声掠过档案室。",
         state(events=["潮痕编号A-17"]), "progression_evidence_not_in_draft",
         {"text_override": "林照发现潮痕编号A-17。管理员拦住去路。潮声掠过档案室。"}),
        # 16. Evidence points to ContextPack.
        (16, BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17", state(events=["潮痕编号A-17"]),
         "progression_evidence_not_in_draft", {"location": "ContextPack.previous_scene_state"}),
        # 17. Before state conflicts with the previous accepted state.
        (17, requirement("thread_advanced", "林澜失踪", "已经找到林澜", "林澜在北礁"), "林澜在北礁",
         "日志显示林澜在北礁", state(threads=["林澜在北礁"]), "before_state_conflicts_previous_scene", {}),
        # 19. A previously confirmed state cannot masquerade as new progress.
        (19, requirement("thread_advanced", "林澜失踪", "林澜失踪案尚未定位", "林澜失踪案尚未定位"),
         "林澜失踪案尚未定位", "众人确认案件尚未定位", state(threads=["林澜失踪案尚未定位"]),
         "progression_reuses_previous_state", {}),
    ]
    for case, req, after, evidence, accepted, reason, options in failures:
        text = options.pop("text_override", f"正文证据：{evidence}。")
        result = verify_progression(
            db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
            plan_id=f"case_{case}_plan", draft_id=f"case_{case}_draft", report_id=f"case_{case}_report",
            requirements=[req], reviews=[plot_review(req, after, evidence, options.get("location", "draft.text"))],
            text=text, previous_scene_id=book + "_scene_1", previous_state=BASE_PREVIOUS,
            accepted_scene_state=accepted,
        )
        assert result["progression_status"] == "failed" and result["progression_failure_reason"] == reason, (case, result)

    # 25. A previous scene from another book is rejected before its state can be compared.
    db.execute("insert into books values ('other','其他书',null,1,'2026','2026')")
    db.execute("insert into chapters values ('other_chapter','other',1,null,'2026','2026')")
    db.execute("insert into scenes values ('other_scene','other','other_chapter',1,null,null,'2026','2026')")
    isolated = direct_case(db, book, 25, BASE_REQUIREMENT, "潮痕编号A-17",
                           "林照发现潮痕编号A-17", state(events=["潮痕编号A-17"]),
                           previous_scene_id="other_scene")
    assert isolated["progression_failure_reason"] == "previous_scene_book_mismatch"
    # 6. An invented progress_type/target_key still fails the planned item.
    invented = verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id="case_invented_plan", draft_id="case_invented_draft", report_id="case_invented_report",
        requirements=[BASE_REQUIREMENT], reviews=[{"payload": {"reviewer_role": "character_plot",
            "progression_assessment": {"status": "achieved", "achieved_items": [{
                "progress_type": "character_development", "target_key": "情感成长",
                "before_state": "未知", "after_state": "潮痕编号A-17",
                "evidence_text": "林照发现潮痕编号A-17", "evidence_location": "draft.text",
            }], "missing_items": []}}}],
        text="正文证据：林照发现潮痕编号A-17。", previous_scene_id=book + "_scene_1",
        previous_state=BASE_PREVIOUS, accepted_scene_state=state(events=["潮痕编号A-17"]),
    )
    assert invented["progression_status"] == "failed"
    assert invented["progression_failure_reason"] == "planned_progression_not_achieved"

    # 1-4. Sync only the missing after_state; never mutate the reviewer payload.
    original_accepted = state(events=["语义相近的英文描述"])
    original_copy = json.loads(json.dumps(original_accepted))
    reviews = [plot_review(BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17")]
    review_copy = json.loads(json.dumps(reviews))
    synced_result = verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id="case_sync_plan", draft_id="case_sync_draft", report_id="case_sync_report",
        requirements=[BASE_REQUIREMENT], reviews=reviews, text="正文证据：林照发现潮痕编号A-17。",
        previous_scene_id=book + "_scene_1", previous_state=BASE_PREVIOUS,
        accepted_scene_state=original_accepted,
    )
    assert synced_result["progression_status"] == "passed"
    assert original_accepted == original_copy
    assert reviews == review_copy
    events = synced_result["accepted_scene_state"]["events"]
    assert "语义相近的英文描述" in events
    record = next(item for item in events if isinstance(item, dict) and item.get("source") == "verified_progression")
    assert record["progress_type"] == "new_clue"
    assert record["target_key"] == "潮痕编号"
    assert record["state"] == "潮痕编号A-17"
    assert record["evidence_text"] == "林照发现潮痕编号A-17"
    again, again_records = sync_verified_progression_state(synced_result["accepted_scene_state"], [{
        "progress_type": "new_clue", "target_key": "潮痕编号", "after_state": "潮痕编号A-17",
        "evidence_text": "林照发现潮痕编号A-17",
    }])
    assert again_records == []
    assert already_has_verified_state(again, record)
    assert sum(1 for item in again["events"] if isinstance(item, dict) and item.get("source") == "verified_progression") == 1

    # thread_closed: write after_state to events, drop only the before_state thread.
    closed_req = requirement("thread_closed", "林澜失踪", "林澜失踪案尚未定位", "林澜已在北礁获救")
    closed_accepted = state(
        events=["语义相近的关闭描述"],
        threads=["林澜失踪案尚未定位", "管理员仍在隐瞒"],
    )
    closed_original = json.loads(json.dumps(closed_accepted))
    closed_reviews = [plot_review(closed_req, "林澜已在北礁获救", "救援队确认林澜已在北礁获救")]
    closed_review_copy = json.loads(json.dumps(closed_reviews))
    closed_item = {
        "progress_type": "thread_closed", "target_key": "林澜失踪",
        "before_state": "林澜失踪案尚未定位", "after_state": "林澜已在北礁获救",
        "evidence_text": "救援队确认林澜已在北礁获救",
    }
    first_sync, first_records = sync_verified_progression_state(closed_accepted, [closed_item])
    assert closed_accepted == closed_original
    assert first_records[0]["state"] == "林澜已在北礁获救"
    assert first_records[0]["source"] == "verified_progression"
    assert "林澜失踪案尚未定位" not in first_sync["unresolved_threads"]
    assert "管理员仍在隐瞒" in first_sync["unresolved_threads"]
    assert any(isinstance(item, dict) and item.get("source") == "verified_progression"
               and item.get("state") == "林澜已在北礁获救" for item in first_sync["events"])
    second_sync, second_records = sync_verified_progression_state(first_sync, [closed_item])
    assert second_records == []
    assert sum(1 for item in second_sync["events"]
               if isinstance(item, dict) and item.get("source") == "verified_progression"
               and item.get("state") == "林澜已在北礁获救") == 1
    assert second_sync["unresolved_threads"] == first_sync["unresolved_threads"]

    structured_before = {"thread": "林澜失踪案尚未定位"}
    structured_accepted = state(
        events=["无关事件"],
        threads=[structured_before, "管理员仍在隐瞒"],
    )
    structured_sync, _ = sync_verified_progression_state(structured_accepted, [{
        **closed_item, "before_state": structured_before,
    }])
    assert structured_before not in structured_sync["unresolved_threads"]
    assert "管理员仍在隐瞒" in structured_sync["unresolved_threads"]

    closed_result = verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id="case_thread_closed_plan", draft_id="case_thread_closed_draft",
        report_id="case_thread_closed_report", requirements=[closed_req], reviews=closed_reviews,
        text="正文证据：救援队确认林澜已在北礁获救。", previous_scene_id=book + "_scene_1",
        previous_state=BASE_PREVIOUS, accepted_scene_state=closed_accepted,
    )
    replay = verify_progression(
        db, book_id=book, chapter_id=book + "_chapter_1", scene_id=book + "_scene_2",
        plan_id="case_thread_closed_plan", draft_id="case_thread_closed_draft",
        report_id="case_thread_closed_report", requirements=[closed_req], reviews=closed_reviews,
        text="正文证据：救援队确认林澜已在北礁获救。", previous_scene_id=book + "_scene_1",
        previous_state=BASE_PREVIOUS, accepted_scene_state=closed_accepted,
    )
    assert closed_accepted == closed_original
    assert closed_reviews == closed_review_copy
    assert closed_result["progression_status"] == "passed"
    assert replay["progression_status"] == "passed"
    assert "林澜失踪案尚未定位" not in closed_result["accepted_scene_state"]["unresolved_threads"]
    assert "管理员仍在隐瞒" in closed_result["accepted_scene_state"]["unresolved_threads"]
    assert sum(1 for item in closed_result["accepted_scene_state"]["events"]
               if isinstance(item, dict) and item.get("source") == "verified_progression"
               and item.get("state") == "林澜已在北礁获救") == 1
    assert sum(1 for item in replay["accepted_scene_state"]["events"]
               if isinstance(item, dict) and item.get("source") == "verified_progression"
               and item.get("state") == "林澜已在北礁获救") == 1
    db.close()


def plan(number, requirements=None):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"第{number}场找到新编号", "entrance_state": {"clue": "未知"},
        "exit_state": {"clue": f"A-{number}"}, "characters": ["林照"], "location": "灯塔档案室",
        "time_context": "夜晚", "conflict": "管理员阻挠", "action_beats": ["核对航海日志"],
        "must_happen": ["发现编号"], "must_not_happen": ["直接结案"],
        "knowledge_boundary": "林照只知道旧线索", "target_word_count": 1250,
        "acceptance_criteria": ["正文出现新编号"], "validation_result": {"complete": True},
        "ready_for_writing": True,
        "progression_requirements": [BASE_REQUIREMENT] if requirements is None else requirements,
    }}


def draft(attempt):
    evidence = f"林照第{attempt}次核对日志，却没有获得新结果。"
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": evidence + ("潮声掠过档案室。" * 140), "word_count": 1250,
        "target_word_count": 1250, "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, *, achieved=False):
    accepted = state(events=["已知线索A"], threads=["林澜失踪案尚未定位"])
    assessment = plot_review(BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17")["payload"]["progression_assessment"]
    if achieved:
        accepted = state(events=["潮痕编号A-17"])
    else:
        assessment = {
            "status": "not_achieved",
            "achieved_items": [],
            "missing_items": [{
                "progress_type": BASE_REQUIREMENT["progress_type"],
                "target_key": BASE_REQUIREMENT["target_key"],
                "before_state": BASE_REQUIREMENT["before_state"],
            }],
        }
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": accepted, "progression_assessment": assessment,
    }}


class InvalidPlanAdapter:
    def __init__(self, requirements):
        self.requirements, self.calls = requirements, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        assert request["task_type"] == "planning"
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        return plan(number, self.requirements)


for requirements in ([], [{**BASE_REQUIREMENT, "progress_type": "illegal"}]):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "invalid-plan.db"
        adapter = InvalidPlanAdapter(requirements)
        first = run(db_path=path, adapter=adapter, execution_mode="sequential")
        db = sqlite3.connect(path)
        scene = "realtest_tide_archive_scene_1"
        assert first["scenes"][0]["final_status"] == "reworking_planning"
        assert [call["task_type"] for call in adapter.calls] == ["planning"]
        assert adapter.calls[0]["input"]["checkpoint"]["plan_version"] == 1
        assert db.execute(
            "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
            (scene,)).fetchone() == (1, 0, 0, "reworking_planning")
        assert [row[0] for row in db.execute(
            "select status from task_states where scene_id!=? order by scene_id", (scene,))] == ["queued"] * 4
        db.close()
        second = run(db_path=path, adapter=adapter, execution_mode="sequential")
        db = sqlite3.connect(path)
        assert second["scenes"][0]["final_status"] == "blocked"
        assert [call["task_type"] for call in adapter.calls] == ["planning", "planning"]
        assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
        assert [row[0] for row in db.execute(
            "select plan_version from scene_plans where scene_id=? order by plan_version", (scene,))] == [1, 2]
        assert db.execute("select count(*) from prose_drafts where scene_id=?", (scene,)).fetchone()[0] == 0
        assert db.execute(
            "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
            (scene,)).fetchone() == (1, 0, 0, "blocked")
        assert not any(call["task_type"].startswith("review_") or call["task_type"] == "memory_extraction" for call in adapter.calls)
        db.close()


class ProgressionFailureAdapter:
    def __init__(self):
        self.calls, self.attempt = [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            self.attempt += 1
            return draft(self.attempt)
        if role == "memory_extraction":
            raise AssertionError("20. progression failure must not call Memory Agent")
        return reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                         "review_style": "language_experience"}[role])


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "runner-failure.db"
    adapter = ProgressionFailureAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene = "realtest_tide_archive_scene_1"
    # 20/21. No Memory call; all later scenes remain queued.
    assert not any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    assert [row[0] for row in db.execute(
        "select status from task_states where scene_id!=? order by scene_id", (scene,))] == ["queued"] * 4
    # 22. First two content failures rewrite; the third returns to Planning.
    events = [json.loads(row[0]) for row in db.execute(
        "select payload_json from task_events where task_id=? and event_type='rework_requested' order by created_at",
        (scene + "_task",))]
    event_plan_versions = [event["plan_version"] for event in events]
    assert event_plan_versions == [1, 1, 2], event_plan_versions
    assert result["scenes"][0]["final_status"] == "blocked"
    # 23. Multiple progression defects in one draft count as one content failure.
    assert len(events) == 3
    assert db.execute("select plan_attempt,content_attempt_in_plan,content_attempt_total from task_states where scene_id=?", (scene,)).fetchone() == (2, 1, 4)
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (scene,)).fetchone()[0] == 4
    assert db.execute("select count(*) from quality_reports where scene_id=?", (scene,)).fetchone()[0] == 4
    review_calls = [call for call in adapter.calls if call["task_type"].startswith("review_")]
    writing_calls = [call for call in adapter.calls if call["task_type"] == "writing"]
    assert {call["task_type"] for call in review_calls} == {"review_world", "review_plot", "review_style"}
    for call in review_calls:
        assert call["input"]["plan_id"] == scene + "_plan_v1" or call["input"]["plan_version"] in (1, 2)
        assert "scene_plan" in call["input"]
        assert call["input"]["scene_plan"]["payload"]["progression_requirements"] == [BASE_REQUIREMENT]
        assert call["input"]["plan_id"].endswith(f"_plan_v{call['input']['plan_version']}")
        assert call["prompt_version"] == REVIEWER_PROMPT_VERSION
    plot_calls = [call for call in review_calls if call["task_type"] == "review_plot"]
    assert plot_calls[0]["input"]["scene_plan"]["payload"]["progression_requirements"][0]["target_key"] == "潮痕编号"
    assert "quality_revision_feedback" not in writing_calls[0]["input"]
    feedback = writing_calls[1]["input"]["quality_revision_feedback"]
    assert feedback["failure_type"] == "quality_report"
    assert feedback["previous_draft_id"].endswith("draft_v1")
    assert "林照第1次核对日志" in feedback["previous_text"]
    assert feedback["planned_progression_requirements"] == [BASE_REQUIREMENT]
    assert feedback["missing_progression_items"]
    assert feedback["instruction"]
    assert {item["reviewer_role"] for item in feedback["reviewer_findings"]} == {
        "world_consistency", "character_plot", "language_experience"}
    assert writing_calls[1]["input"] != writing_calls[0]["input"]
    assert writing_calls[1]["prompt_version"] == WRITING_PROMPT_VERSION
    assert "quality_revision_feedback" not in writing_calls[3]["input"]
    db.close()


# 24. A world rule remains a proposal until explicit human confirmation.
with tempfile.TemporaryDirectory() as directory:
    db, book = seed(Path(directory) / "world-rule.db")
    scene, chapter = book + "_scene_1", book + "_chapter_1"
    plan_id = save_plan(db, book, chapter, scene, plan(1), "plan_call")
    draft_id, draft_hash = save_draft(db, book, chapter, scene, draft(1), "draft_call")
    quality = {"contract_type": "QualityReport", "contract_version": "v1", "payload": {
        "review_completion_status": "completed", "reviewer_results": [], "deduped_issue_count": 0,
        "ordinary_issue_count": 0, "serious_issue_count": 0, "has_true_conflict": False,
        "needs_arbiter": False, "routing_recommendation": "complete",
        "accepted_scene_state": state(events=["发现规则"]), "status": "passed",
        "progression_status": "passed", "planned_progression_count": 1,
        "achieved_progression_count": 1, "verified_progression_items": [],
        "missing_progression_items": [], "progression_failure_reason": None,
    }}
    report_id = save_report(db, book, chapter, scene, draft_id, draft_hash, [quality])[0]
    proposal = {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "world_rule", "target_scope": "book_memory", "target_key": "灯塔规则",
        "action": "create", "before_value": None, "after_value": "灯塔会改写记忆",
        "evidence": "发现规则", "evidence_location": "draft.text", "change_reason": "正文提出新规则",
        "conflict_status": "none", "write_policy": "human_confirmation", "status": "pending",
    }}
    _, written = save_proposal(db, book, chapter, scene, draft_id, report_id, proposal)
    assert not written and db.execute("select count(*) from memory_records").fetchone()[0] == 0
    db.close()


class PassingAdapter:
    def __init__(self):
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": "林照发现潮痕编号A-17。" + ("档案纸页在灯光下翻动。" * 120),
                "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "潮痕编号",
                "action": "create", "before_value": None, "after_value": "潮痕编号A-17",
                "evidence": "林照发现潮痕编号A-17", "evidence_location": "draft.text",
                "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        accepted = state(events=["潮痕编号A-17"])
        response = reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                             "review_style": "language_experience"}[role], achieved=True)
        response["payload"]["scene_state"] = accepted
        return response


# 26. Recovery/re-entry reuses the immutable check and never overwrites it.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "recovery.db"
    passing = PassingAdapter()
    first = run(db_path=path, adapter=passing, execution_mode="sequential")
    assert first["scenes"][0]["final_status"] == "waiting_confirmation"
    assert first["scenes"][0]["arbiter_called"] is False
    assert first["scenes"][0]["arbiter_succeeded"] is False
    assert not any(call["task_type"] == "arbiter" for call in passing.calls)
    db = sqlite3.connect(path)
    before = db.execute("select * from scene_progression_checks order by check_id").fetchall()
    db.close()
    run(db_path=path, adapter=PassingAdapter(), execution_mode="sequential")
    db = sqlite3.connect(path)
    assert db.execute("select * from scene_progression_checks order by check_id").fetchall() == before
    db.close()


reviewer_messages = build_chat_messages({"contract_type": "ReviewerResult", "task_type": "review_plot", "input": {
    "scene_plan": plan(1), "plan_id": "p1", "plan_version": 1, "draft": {"payload": {"text": "正文"}},
}})
assert [item["role"] for item in reviewer_messages] == ["system", "user", "user"]
assert "character_development" in reviewer_messages[0]["content"]
assert "progression_requirements" in reviewer_messages[1]["content"]
assert reviewer_messages[2]["content"] == reviewer_plot_instruction()
assert reviewer_progression_instruction() in reviewer_messages[2]["content"]
assert "不得创造" in reviewer_messages[2]["content"]
assert "character_plot" in reviewer_messages[2]["content"]
assert "after_state 必须同步进入 scene_state" in reviewer_messages[2]["content"]
arbiter_messages = build_chat_messages({"contract_type": "QualityReport", "task_type": "arbiter", "input": {
    "scene_plan": plan(1), "draft": {"payload": {"text": "正文"}},
}})
assert arbiter_messages[2]["content"] == arbiter_quality_instruction()
quality_fb = quality_revision_feedback(
    previous_draft_id="d1", previous_text="上一稿正文", plan_id="p1", plan_version=1,
    progression_failure_reason="planned_progression_not_achieved",
    planned_progression_requirements=[BASE_REQUIREMENT],
    missing_progression_items=[{"target_key": "潮痕编号", "failure_reason": "planned_progression_not_achieved"}],
    progression_status="failed", routing_recommendation="rewrite",
    reviewer_findings=[
        {"reviewer_role": "world_consistency", "result": "failed", "issue_count": 1,
         "severity": "ordinary", "impact_scope": "local", "findings": "时间线前后矛盾"},
        {"reviewer_role": "character_plot", "result": "failed", "issue_count": 1,
         "severity": "ordinary", "impact_scope": "local", "findings": "人物反应不成立"},
        {"reviewer_role": "language_experience", "result": "failed", "issue_count": 2,
         "severity": "ordinary", "impact_scope": "local", "findings": "重复句式"},
    ],
)
quality_messages = build_chat_messages({"contract_type": "ProseDraft", "input": {
    "scene_plan": plan(1), "quality_revision_feedback": quality_fb,
}})
assert quality_messages[2]["content"] == writing_quality_edit_instruction(quality_fb)
assert "上一稿正文" in quality_messages[1]["content"]
assert "上一稿正文" not in quality_messages[2]["content"]
assert "禁止只改结构化字段或word_count" in quality_messages[2]["content"]
assert "时间线前后矛盾" in quality_messages[2]["content"]
assert "人物反应不成立" in quality_messages[2]["content"]
assert "重复句式" in quality_messages[2]["content"]
assert "推进目标未完成" in quality_messages[2]["content"]
assert WRITING_PROMPT_VERSION == "prose_quality_v5"


class ConflictAdapter(PassingAdapter):
    def complete(self, request, timeout_seconds):
        role = request["task_type"]
        if role == "arbiter":
            self.calls.append(request)
            accepted = state(events=["潮痕编号A-17", "仲裁确认"])
            return {"contract_type": "QualityReport", "contract_version": "v1", "payload": {
                "review_completion_status": "completed", "reviewer_results": [], "deduped_issue_count": 0,
                "ordinary_issue_count": 0, "serious_issue_count": 0, "has_true_conflict": True,
                "needs_arbiter": False, "routing_recommendation": "complete",
                "accepted_scene_state": accepted, "status": "passed",
            }}
        response = super().complete(request, timeout_seconds)
        if role == "review_world":
            response["payload"]["true_conflict_candidate"] = True
            response["payload"]["severity"] = "serious"
        return response


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "arbiter.db"
    adapter = ConflictAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["arbiter_called"] is True
    assert result["scenes"][0]["arbiter_succeeded"] is True
    accepted = json.loads(db.execute("select accepted_scene_state_json from quality_reports where scene_id=?",
                                    ("realtest_tide_archive_scene_1",)).fetchone()[0])
    assert "仲裁确认" in accepted["events"]
    arbiter_calls = [call for call in adapter.calls if call["task_type"] == "arbiter"]
    assert len(arbiter_calls) == 1
    assert arbiter_calls[0]["prompt_version"] == ARBITER_PROMPT_VERSION
    arbiter_input = arbiter_calls[0]["input"]
    assert "scene_plan" in arbiter_input
    assert arbiter_input["plan_id"].endswith("_plan_v1")
    assert arbiter_input["plan_version"] == 1
    assert "draft" in arbiter_input
    assert arbiter_input["reviewer_results"]
    assert "preliminary_quality" in arbiter_input
    assert arbiter_input["progression_requirements"] == [BASE_REQUIREMENT]
    assert "progression_status" not in arbiter_input["preliminary_quality"]["payload"]
    assert db.execute("select count(*) from scene_progression_checks where scene_id=?",
                      ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    db.close()


MEMORY_AFTER = "林照明白灯塔可以保存并展示记忆"
MEMORY_REQUIREMENT = {
    "progress_type": "new_clue", "target_key": "灯塔记忆规则", "before_state": "未知",
    "expected_after_state": "灯塔可以保存并展示记忆",
    "acceptance_criterion": "正文写明灯塔只能保存和展示记忆",
}


def memory_draft():
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": "林照明白灯塔可以保存并展示记忆。" + ("档案纸页在灯光下翻动。" * 120),
        "word_count": 1250, "target_word_count": 1250, "complete": True,
        "writer_self_check": {"complete": True},
    }}


def memory_reviewer(role, *, include_after=False, evidence=MEMORY_AFTER, after_state=MEMORY_AFTER, status="achieved"):
    accepted = state(events=["林照进入档案室"])
    if include_after:
        accepted = state(events=[MEMORY_AFTER])
    assessment = plot_review(MEMORY_REQUIREMENT, after_state, evidence, status=status)["payload"]["progression_assessment"]
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "cross_scene", "true_conflict_candidate": True,
        "scene_state": accepted, "progression_assessment": assessment,
    }}


def arbiter_report(accepted):
    return {"contract_type": "QualityReport", "contract_version": "v1", "payload": {
        "review_completion_status": "completed", "reviewer_results": [], "deduped_issue_count": 0,
        "ordinary_issue_count": 0, "serious_issue_count": 0, "has_true_conflict": False,
        "needs_arbiter": False, "routing_recommendation": "complete",
        "accepted_scene_state": accepted, "status": "passed",
        "progression_status": "passed", "planned_progression_count": 1, "achieved_progression_count": 1,
        "verified_progression_items": [{"target_key": "灯塔记忆规则"}], "missing_progression_items": [],
        "progression_failure_reason": None,
    }}


class MemoryPlanAdapter:
    def __init__(self, *, arbiter_accepted, arbiter_response=None, timeout_arbiter=False, empty_evidence=False):
        self.arbiter_accepted = arbiter_accepted
        self.arbiter_response = arbiter_response
        self.timeout_arbiter = timeout_arbiter
        self.empty_evidence = empty_evidence
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        if role == "planning":
            return plan(1, [MEMORY_REQUIREMENT])
        if role == "writing":
            return memory_draft()
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "灯塔记忆规则",
                "action": "create", "before_value": None, "after_value": MEMORY_AFTER,
                "evidence": MEMORY_AFTER, "evidence_location": "draft.text",
                "change_reason": "审查通过", "conflict_status": "none",
                "write_policy": "human_confirmation", "status": "pending",
            }}
        if role == "arbiter":
            if self.timeout_arbiter:
                raise TimeoutError("The read operation timed out")
            if self.arbiter_response is not None:
                return self.arbiter_response
            return arbiter_report(self.arbiter_accepted)
        return memory_reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                                "review_style": "language_experience"}[role],
                               after_state=MEMORY_AFTER,
                               status="not_achieved" if self.empty_evidence else "achieved")


# 9. Arbiter passed cannot override a backend progression failure.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "arbiter-cannot-bypass.db"
    adapter = MemoryPlanAdapter(arbiter_accepted=state(events=[MEMORY_AFTER]), empty_evidence=True)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["arbiter_called"] is True
    assert result["scenes"][0]["arbiter_succeeded"] is True
    row = db.execute("select status,routing_recommendation from quality_reports where scene_id=?",
                     ("realtest_tide_archive_scene_1",)).fetchone()
    assert row == ("failed", "rewrite")
    checks = db.execute("select result,failure_reason from scene_progression_checks where scene_id=?",
                        ("realtest_tide_archive_scene_1",)).fetchall()
    assert checks == [("failed", "planned_progression_not_achieved")]
    db.close()


# 10. Arbiter can supply the missing after_state; backend then verifies once and may pass.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "arbiter-fills-state.db"
    adapter = MemoryPlanAdapter(arbiter_accepted=state(events=[MEMORY_AFTER]))
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["arbiter_called"] is True
    assert result["scenes"][0]["arbiter_succeeded"] is True
    assert result["scenes"][0]["progression_status"] == "passed"
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert db.execute("select count(*) from scene_progression_checks where scene_id=?",
                      ("realtest_tide_archive_scene_1",)).fetchone()[0] == 1
    db.close()


# 14 / 15. Arbiter contract failure is technical: no report, no content count, call recorded.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "arbiter-contract.db"
    illegal = arbiter_report(state(events=[MEMORY_AFTER]))
    illegal["payload"]["review_completion_status"] = "complete"
    adapter = MemoryPlanAdapter(arbiter_accepted=state(events=[MEMORY_AFTER]), arbiter_response=illegal)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert result["scenes"][0]["arbiter_called"] is True
    assert result["scenes"][0]["arbiter_succeeded"] is False
    assert "invalid review_completion_status" in (result["scenes"][0].get("technical_error") or "")
    assert db.execute("select count(*) from quality_reports where scene_id=?",
                      ("realtest_tide_archive_scene_1",)).fetchone()[0] == 0
    assert db.execute("select count(*) from scene_progression_checks where scene_id=?",
                      ("realtest_tide_archive_scene_1",)).fetchone()[0] == 0
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        ("realtest_tide_archive_scene_1",)).fetchone() == (0, 0, "exception_pending")
    assert db.execute("select status from harness_calls where agent_type='arbiter'").fetchone()[0] == "contract_invalid"
    db.close()


# 16. Old v1 Arbiter successes cannot be reused after the prompt upgrade.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "no-v1-arbiter-reuse.db"
    first_adapter = MemoryPlanAdapter(arbiter_accepted=state(events=[MEMORY_AFTER]), timeout_arbiter=True)
    first = run(db_path=path, adapter=first_adapter, execution_mode="sequential")
    arbiter_request = next(call for call in first_adapter.calls if call["task_type"] == "arbiter")
    planted = dict(arbiter_request)
    planted["prompt_version"] = "v1"
    db = sqlite3.connect(path)
    db.execute(
        "insert into harness_calls(harness_call_id,task_id,agent_type,provider,model,request_json,response_json,status,started_at,completed_at) values (?,?,?,?,?,?,?,?,?,?)",
        ("hc_planted_arbiter_v1", "realtest_tide_archive_scene_1_task", "arbiter", "mock", "mock",
         json.dumps(planted, ensure_ascii=False), json.dumps(arbiter_report(state(events=[MEMORY_AFTER])), ensure_ascii=False),
         "success", "2026", "2026"))
    db.commit(); db.close()
    second_adapter = MemoryPlanAdapter(arbiter_accepted=state(events=[MEMORY_AFTER]))
    second = run(db_path=path, adapter=second_adapter, execution_mode="sequential")
    arbiter_calls = [call for call in second_adapter.calls if call["task_type"] == "arbiter"]
    assert first["scenes"][0]["arbiter_called"] is True
    assert first["scenes"][0]["arbiter_succeeded"] is False
    assert arbiter_calls
    assert all(call["prompt_version"] == ARBITER_PROMPT_VERSION for call in arbiter_calls)
    assert "hc_planted_arbiter_v1" not in (second["scenes"][0].get("reused_calls") or [])


FINDINGS = {
    "world_consistency": ["灯塔夜间规则前后不一致"],
    "character_plot": ["林照对管理员的态度跳变"],
    "language_experience": ["后半段句式重复", "明显影响阅读的表达错误"],
}


def findings_reviewer(role, *, after_in_state=False):
    accepted = state(events=["Lin Zhao found a similar archive mark"])
    if after_in_state:
        accepted = state(events=["潮痕编号A-17"])
    assessment = plot_review(BASE_REQUIREMENT, "潮痕编号A-17", "林照发现潮痕编号A-17")["payload"]["progression_assessment"]
    items = FINDINGS[role]
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "failed", "findings": items, "suggestions": [], "issue_count": len(items),
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": accepted, "progression_assessment": assessment,
    }}


class FindingsReworkAdapter:
    def __init__(self, *, same_text=False):
        self.same_text, self.calls, self.writes = same_text, [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        if role == "planning":
            return plan(1)
        if role == "writing":
            self.writes += 1
            suffix = "" if self.same_text else f"第{self.writes}稿改动。"
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": "林照发现潮痕编号A-17。" + ("档案纸页在灯光下翻动。" * 120) + suffix,
                "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "status": "skipped", "reason": "本场没有长期记忆变化",
            }}
        return findings_reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                                 "review_style": "language_experience"}[role])


# 10/12-16. Synced progression is saved; Writing gets reviewer findings, not a fake progression miss.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "quality-findings.db"
    adapter = FindingsReworkAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    accepted = json.loads(db.execute("select accepted_scene_state_json from quality_reports where scene_id=? order by created_at",
                                    ("realtest_tide_archive_scene_1",)).fetchone()[0])
    assert any(isinstance(item, dict) and item.get("state") == "潮痕编号A-17" and item.get("source") == "verified_progression"
               for item in accepted["events"])
    plot_response = json.loads(db.execute(
        "select response_json from harness_calls where agent_type='review_plot' order by started_at").fetchone()[0])
    assert plot_response["payload"]["scene_state"]["events"] == ["Lin Zhao found a similar archive mark"]
    writing_calls = [call for call in adapter.calls if call["task_type"] == "writing"]
    assert len(writing_calls) >= 2
    feedback = writing_calls[1]["input"]["quality_revision_feedback"]
    assert feedback["failure_type"] == "quality_report"
    assert feedback["progression_status"] == "passed"
    assert not feedback["missing_progression_items"]
    assert feedback["progression_failure_reason"] is None
    assert {item["reviewer_role"]: item["issue_count"] for item in feedback["reviewer_findings"]} == {
        "world_consistency": 1, "character_plot": 1, "language_experience": 2}
    assert {item["reviewer_role"]: item["severity"] for item in feedback["reviewer_findings"]} == {
        "world_consistency": "ordinary", "character_plot": "ordinary", "language_experience": "ordinary"}
    instruction = writing_quality_edit_instruction(feedback)
    assert "灯塔夜间规则前后不一致" in instruction
    assert "林照对管理员的态度跳变" in instruction
    assert "后半段句式重复" in instruction
    assert "推进目标未完成" not in instruction
    assert writing_calls[1]["input"] != writing_calls[0]["input"]
    assert writing_calls[1]["prompt_version"] == "prose_quality_v5"
    assert db.execute("select count(*) from memory_records").fetchone()[0] == 0
    db.close()


# 17. An unchanged rewrite is still an exact-duplicate block.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "quality-same-text.db"
    adapter = FindingsReworkAdapter(same_text=True)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "blocked"
    assert "duplicate_draft_content" in (result["scenes"][0].get("block_reason") or "")
    assert db.execute(
        "select content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        ("realtest_tide_archive_scene_1",)).fetchone()[0] >= 1
    db.close()


class NextSceneReadsSyncedAdapter:
    def __init__(self):
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            clue = "林照发现潮痕编号A-17。" if number == 1 else "林照在北礁找到新的潮汐航线。"
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": clue + (f"第{number}场独有的档案叙述在灯下展开。" * 80),
                "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "status": "skipped", "reason": "本场没有长期记忆变化",
            }}
        if number == 1:
            response = reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                                 "review_style": "language_experience"}[role], achieved=True)
            response["payload"]["scene_state"] = state(events=["a nearby English paraphrase"])
            return response
        return reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                         "review_style": "language_experience"}[role], achieved=True)


# 11. The next scene ContextPack reads the synced accepted state.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "next-pack.db"
    adapter = NextSceneReadsSyncedAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["final_status"] == "completed"
    scene2_planning = next(call for call in adapter.calls
                           if call["task_type"] == "planning" and call["input"]["checkpoint"]["scene_id"].endswith("_2"))
    previous_state = scene2_planning["input"]["context_pack"]["previous_scene_state"]
    assert any(isinstance(item, dict) and item.get("state") == "潮痕编号A-17"
               and item.get("source") == "verified_progression" for item in previous_state.get("events", []))


THREAD_CLOSED_REQUIREMENT = requirement(
    "thread_closed", "林澜失踪", "林澜失踪案尚未定位", "林澜已在北礁获救",
)


class ThreadClosedNextSceneAdapter:
    def __init__(self):
        self.calls = []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number, [THREAD_CLOSED_REQUIREMENT] if number == 1 else None)
        if role == "writing":
            clue = "救援队确认林澜已在北礁获救。" if number == 1 else "林照发现潮痕编号A-17。"
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": clue + (f"第{number}场独有的档案叙述在灯下展开。" * 80),
                "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "status": "skipped", "reason": "本场没有长期记忆变化",
            }}
        scene_state = state(
            events=["a nearby English paraphrase"],
            threads=["林澜失踪案尚未定位", "管理员仍在隐瞒"],
        )
        if number == 1:
            response = reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                                 "review_style": "language_experience"}[role], achieved=True)
            if role == "review_plot":
                response["payload"]["progression_assessment"] = plot_review(
                    THREAD_CLOSED_REQUIREMENT, "林澜已在北礁获救", "救援队确认林澜已在北礁获救",
                )["payload"]["progression_assessment"]
            response["payload"]["scene_state"] = scene_state
            return response
        return reviewer({"review_world": "world_consistency", "review_plot": "character_plot",
                         "review_style": "language_experience"}[role], achieved=True)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "thread-closed-next-pack.db"
    adapter = ThreadClosedNextSceneAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    assert result["scenes"][0]["final_status"] == "completed"
    scene2_planning = next(call for call in adapter.calls
                           if call["task_type"] == "planning" and call["input"]["checkpoint"]["scene_id"].endswith("_2"))
    previous_state = scene2_planning["input"]["context_pack"]["previous_scene_state"]
    assert "林澜失踪案尚未定位" not in previous_state.get("unresolved_threads", [])
    assert "管理员仍在隐瞒" in previous_state.get("unresolved_threads", [])
    assert any(isinstance(item, dict) and item.get("state") == "林澜已在北礁获救"
               and item.get("source") == "verified_progression" for item in previous_state.get("events", []))


class ResidualAfterProgressionAdapter(ProgressionFailureAdapter):
    def complete(self, request, timeout_seconds):
        if request["task_type"] == "writing" and self.attempt >= 3:
            self.calls.append(request)
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": "短" * 673, "word_count": 1250, "target_word_count": 1250,
                "complete": True, "writer_self_check": {"complete": True},
            }}
        return super().complete(request, timeout_seconds)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "residual.db"
    adapter = ResidualAfterProgressionAdapter()
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    scene_out = result["scenes"][0]
    db = sqlite3.connect(path)
    scene = "realtest_tide_archive_scene_1"
    assert scene_out["final_status"] == "blocked"
    assert scene_out["length_validation_status"] == "failed"
    assert scene_out["block_reason"] == "length_attempts_exhausted"
    assert scene_out.get("report_id") is None
    assert scene_out.get("progression_status") is None
    assert scene_out.get("accepted_scene_state") is None
    assert db.execute("select count(*) from quality_reports where scene_id=?", (scene,)).fetchone()[0] == 3
    assert db.execute("select count(*) from scene_progression_checks where scene_id=?", (scene,)).fetchone()[0] >= 3
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (scene,)).fetchone()[0] == 7
    db.close()

print("progression gate: 26 cases ok")

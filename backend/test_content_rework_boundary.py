"""Fixed coverage for per-plan draft counts and the post-replan block boundary."""
import json
import sqlite3
import tempfile
from pathlib import Path
from backend.test_english_fixtures import words

from integration.recovery import apply_content_failure, apply_length_failure
from integration.run_real_test import run, save_draft
from integration.seed_real_test import seed


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


def reviewer(role, *, result="passed", issue_count=0):
    findings = ["记录"] * issue_count
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": result, "findings": findings, "suggestions": [], "issue_count": issue_count,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": ["发现线索"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": "word", "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": "word"},
    }}


def memory():
    return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
        "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": "林照-灯塔调查",
        "action": "create", "before_value": None, "after_value": "林照完成本场调查", "evidence": "word",
        "evidence_location": "draft.payload.text", "change_reason": "审查通过", "conflict_status": "none",
        "write_policy": "human_confirmation", "status": "pending",
    }}


ROLES = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}


class SequenceAdapter:
    def __init__(self, sizes, *, review="passed", review_from_plan=1, timeout_after=None, timeout_first=False):
        self.sizes, self.review, self.review_from_plan = list(sizes), review, review_from_plan
        self.timeout_after, self.timeout_first = timeout_after, timeout_first
        self.calls, self.writes = [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        checkpoint = request["input"]["checkpoint"]
        number = int(checkpoint["scene_id"].rsplit("_", 1)[-1])
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
        plan_version = checkpoint["plan_version"]
        failed = self.review == "failed" and plan_version >= self.review_from_plan
        return reviewer(ROLES[role], result="failed" if failed else "passed", issue_count=1 if failed else 0)


def later_queued(db):
    return [row[0] for row in db.execute(
        "select status from task_states where scene_id!=? order by scene_id", (SCENE,))]


def draft_rows(db):
    return db.execute(
        "select draft_version,plan_version,content_attempt_in_plan,content_attempt_total from prose_drafts where scene_id=? order by draft_version",
        (SCENE,)).fetchall()


def task_counts(db):
    return db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where task_id=?",
        (TASK,)).fetchone()


# Direct save_draft counting does not use global draft_version for both fields.
with tempfile.TemporaryDirectory() as directory:
    db, book = seed(Path(directory) / "counts.db")
    chapter = book + "_chapter_1"
    save_draft(db, book, chapter, SCENE, prose(346), "hc1", version=1, plan_version=1)
    save_draft(db, book, chapter, SCENE, prose(400), "hc2", version=2, plan_version=1)
    save_draft(db, book, chapter, SCENE, prose(500), "hc3", version=3, plan_version=1)
    save_draft(db, book, chapter, SCENE, prose(600), "hc4", version=4, plan_version=2)
    assert draft_rows(db) == [(1, 1, 1, 1), (2, 1, 2, 2), (3, 1, 3, 3), (4, 2, 1, 4)]
    db.close()


# 1/2. Initial plan: first two length failures rewrite, then a passing draft continues.
with tempfile.TemporaryDirectory() as directory:
    adapter = SequenceAdapter([346, 999, 1000])
    result = run(db_path=Path(directory) / "two-fails.db", adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(Path(directory) / "two-fails.db")
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert [call["task_type"] for call in adapter.calls].count("planning") == 1
    assert draft_rows(db) == [(1, 1, 1, 1), (2, 1, 2, 2), (3, 1, 3, 3)]
    assert task_counts(db) == (1, 0, 0, "waiting_confirmation")
    assert result["scenes"][0]["length_failure_count_in_plan"] == 2
    assert result["scenes"][0]["semantic_failure_count_in_plan"] == 0
    db.close()


# 3/4. Third and fourth length drafts stay on the same plan; the fourth may pass.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "fourth-length-passes.db"
    adapter = SequenceAdapter([346, 999, 1501, 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert draft_rows(db) == [(1, 1, 1, 1), (2, 1, 2, 2), (3, 1, 3, 3), (4, 1, 4, 4)]
    assert task_counts(db)[:3] == (1, 0, 0)
    assert [call["task_type"] for call in adapter.calls].count("planning") == 1
    assert any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    db.close()


# 5. Fourth length failure blocks on the same plan and does not create Plan v2.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "fourth-length-block.db"
    adapter = SequenceAdapter([346, 400, 500, 600, 700])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "blocked"
    assert result["scenes"][0]["block_reason"] == "length_attempts_exhausted"
    assert result["scenes"][0]["current_node"] != "exception_handling"
    assert draft_rows(db) == [(1, 1, 1, 1), (2, 1, 2, 2), (3, 1, 3, 3), (4, 1, 4, 4)]
    assert task_counts(db) == (1, 0, 0, "blocked")
    assert db.execute("select count(*) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0] == 1
    roles = [call["task_type"] for call in adapter.calls]
    assert roles.count("planning") == 1 and roles.count("writing") == 4
    assert not any(role.startswith("review_") or role == "memory_extraction" for role in roles)
    assert later_queued(db) == ["queued"] * 4
    db.close()


# 7 / 18 / 19. Three semantic review failures still replan; the next cycle blocks.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "replan-review-block.db"
    adapter = SequenceAdapter([1000, 1000, 1000, 1000], review="failed", review_from_plan=1)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "blocked"
    assert result["scenes"][0]["block_reason"] == "content_attempts_exhausted"
    assert task_counts(db) == (2, 1, 4, "blocked")
    assert [call["task_type"] for call in adapter.calls].count("planning") == 2
    assert not any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    assert later_queued(db) == ["queued"] * 4
    db.close()


# 8. New plan first progression failure blocks.
class ProgressionThenBlockAdapter(SequenceAdapter):
    def complete(self, request, timeout_seconds):
        if request["task_type"] == "review_plot":
            self.calls.append(request)
            payload = reviewer("character_plot")["payload"]
            payload["result"] = "failed"
            payload["findings"] = ["剧情没有完成有效推进"]
            payload["issue_count"] = 1
            payload["progression_assessment"] = {"status": "not_achieved", "achieved_items": [], "missing_items": [{
                "progress_type": "new_clue", "target_key": "灯塔线索", "before_state": "未知",
            }]}
            return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}
        return super().complete(request, timeout_seconds)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "replan-progression-block.db"
    adapter = ProgressionThenBlockAdapter([1000, 1000, 1000, 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    observed = (result["scenes"][0]["final_status"], task_counts(db),
                db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0],
                [call["task_type"] for call in adapter.calls])
    assert result["scenes"][0]["final_status"] == "blocked"
    assert task_counts(db) == (2, 1, 4, "blocked"), observed
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 4
    assert not any(call["task_type"] == "memory_extraction" for call in adapter.calls)
    db.close()


# 6. New plan first semantic-repetition failure blocks.
def unique_plan(goal, action):
    payload = plan(2)["payload"]
    payload = {**payload, "scene_goal": goal, "action_beats": [action]}
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": payload}


class Scene2RepetitionAdapter:
    def __init__(self, prefix):
        self.prefix, self.calls, self.writes = prefix, [], 0

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return unique_plan(f"第{number}场新目标", f"第{number}场新动作")
        if role == "writing":
            self.writes += 1
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": self.prefix + (f"第{self.writes}次不同尾段" * 150),
                "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        raise AssertionError("semantic repetition must not call reviewers or memory")


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "replan-repeat-block.db"
    from integration.run_real_test import save_plan
    db, book = seed(path)
    prefix = "档案室开头高度一致" * 14
    prior = unique_plan("第一场独特目标", "第一场独特动作")
    save_plan(db, book, book + "_chapter_1", book + "_scene_1", prior, "hc_p1")
    save_draft(db, book, book + "_chapter_1", book + "_scene_1", {
        "contract_type": "ProseDraft", "contract_version": "v1",
        "payload": {"text": prefix + "旧场尾段" * 180, "word_count": 1250, "target_word_count": 1250,
                    "complete": True, "writer_self_check": {"complete": True}},
    }, "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        book + "_scene_1_report_v1", book, book + "_chapter_1", book + "_scene_1",
        book + "_scene_1_draft_v1", "h", 1, "completed", "[]", 0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []}),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?",
               (book + "_scene_1",))
    db.commit(); db.close()
    adapter = Scene2RepetitionAdapter(prefix)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene2 = book + "_scene_2"
    assert result["scenes"][1]["final_status"] == "blocked"
    assert db.execute("select status from task_states where scene_id=?", (scene2,)).fetchone()[0] == "blocked"
    assert [row[0] for row in db.execute(
        "select status from task_states where scene_id in (?,?) order by scene_id",
        (book + "_scene_3", book + "_scene_4"))] == ["queued", "queued"]
    assert not any(call["task_type"].startswith("review_") or call["task_type"] == "memory_extraction" for call in adapter.calls)
    db.close()


# 11. Technical timeout does not consume content attempts.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "timeout.db"
    adapter = SequenceAdapter([1000], timeout_first=True)
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert task_counts(db) == (1, 0, 0, "exception_pending")
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    db.close()


# 15. Resume must not recount the same failed draft_version.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "resume-count.db"
    adapter = SequenceAdapter([346, 1000], timeout_after=1)
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "exception_pending"
    assert draft_rows(db) == [(1, 1, 1, 1)]
    assert task_counts(db)[:3] == (1, 0, 0)
    first_events = db.execute(
        "select count(*) from task_events where task_id=? and event_type='length_rework_requested'",
        (TASK,)).fetchone()[0]
    assert first_events == 1
    apply_length_failure(db, TASK, "length_validation_failed:under_length:346", SCENE + "_draft_v1")
    assert db.execute(
        "select count(*) from task_events where task_id=? and event_type='length_rework_requested'",
        (TASK,)).fetchone()[0] == 1
    assert task_counts(db)[:3] == (1, 0, 0)
    db.close()
    adapter.timeout_after = None
    adapter.sizes = [1000]
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][0]["final_status"] == "waiting_confirmation"
    assert draft_rows(db) == [(1, 1, 1, 1), (2, 1, 2, 2)]
    assert task_counts(db)[:3] == (1, 0, 0)
    assert db.execute(
        "select count(*) from task_events where task_id=? and event_type='length_rework_requested'",
        (TASK,)).fetchone()[0] == 1
    db.close()


class InvalidPlanAdapter:
    def __init__(self, requirements=None, *, drop_field=False):
        self.requirements, self.drop_field, self.calls = requirements, drop_field, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        assert request["task_type"] == "planning"
        payload = plan(int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1]))
        if self.drop_field:
            del payload["payload"]["progression_requirements"]
        else:
            payload["payload"]["progression_requirements"] = self.requirements
        return payload


def planning_roles(adapter):
    return [call["task_type"] for call in adapter.calls]


def assert_planning_rework(db, adapter, *, plan_version):
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    assert later_queued(db) == ["queued"] * 4
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert max((row[0] for row in db.execute("select plan_version from scene_plans where scene_id=?", (SCENE,))), default=0) < 3
    assert planning_roles(adapter) == ["planning"]
    assert adapter.calls[0]["input"]["checkpoint"]["plan_version"] == 1
    assert not any(role.startswith("review_") or role == "memory_extraction" for role in planning_roles(adapter))


def assert_planning_blocked(db, adapter, second):
    assert second["scenes"][0]["final_status"] == "blocked"
    assert second["scenes"][0]["current_node"] == "planning"
    assert task_counts(db) == (1, 0, 0, "blocked")
    assert later_queued(db) == ["queued"] * 4
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert max((row[0] for row in db.execute("select plan_version from scene_plans where scene_id=?", (SCENE,))), default=0) < 3
    assert planning_roles(adapter) == ["planning", "planning"]
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    assert not second["scenes"][0]["reused_calls"]
    assert not any(role.startswith("review_") or role == "memory_extraction" for role in planning_roles(adapter))


# 1/2/6/9. Missing progression_requirements: v1 replans, v2 blocks, no content count.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "plan-missing.db"
    adapter = InvalidPlanAdapter(drop_field=True)
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "reworking_planning"
    assert_planning_rework(db, adapter, plan_version=2)
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_blocked(db, adapter, second)
    db.close()


# 3/6/9. Illegal progress_type uses the same planning boundary.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "plan-illegal.db"
    adapter = InvalidPlanAdapter([{
        "progress_type": "illegal", "target_key": "灯塔线索", "before_state": "未知",
        "expected_after_state": "发现线索", "acceptance_criterion": "正文出现线索",
    }])
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "reworking_planning"
    assert_planning_rework(db, adapter, plan_version=2)
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert_planning_blocked(db, adapter, second)
    db.close()


class PlanRepeatAdapter:
    def __init__(self, repeated):
        self.repeated, self.calls = repeated, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        if request["task_type"] == "planning":
            return self.repeated
        raise AssertionError("plan repetition must prevent writing")


# 4/5/6/9. Repeated ScenePlan: v1 replans, v2 blocks, still no content count.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "plan-repeat-cap.db"
    from integration.run_real_test import save_plan
    db, book = seed(path)
    repeated = unique_plan("解读潮痕档案", "逐页比对潮汐记录")
    save_plan(db, book, book + "_chapter_1", book + "_scene_1", unique_plan("解读潮痕档案", "逐页比对潮汐记录"), "hc_p1")
    save_draft(db, book, book + "_chapter_1", book + "_scene_1", {
        "contract_type": "ProseDraft", "contract_version": "v1",
        "payload": {"text": "第一场不同正文" * 200, "word_count": 1250, "target_word_count": 1250,
                    "complete": True, "writer_self_check": {"complete": True}},
    }, "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        book + "_scene_1_report_v1", book, book + "_chapter_1", book + "_scene_1",
        book + "_scene_1_draft_v1", "h", 1, "completed", "[]", 0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []}),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?",
               (book + "_scene_1",))
    db.commit(); db.close()
    adapter = PlanRepeatAdapter(repeated)
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene2 = book + "_scene_2"
    assert first["scenes"][1]["final_status"] == "reworking_planning"
    assert db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene2,)).fetchone() == (1, 0, 0, "reworking_planning")
    assert [row[0] for row in db.execute(
        "select status from task_states where scene_id in (?,?) order by scene_id",
        (book + "_scene_3", book + "_scene_4"))] == ["queued", "queued"]
    assert planning_roles(adapter) == ["planning"]
    assert adapter.calls[0]["input"]["checkpoint"]["plan_version"] == 1
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][1]["final_status"] == "blocked"
    assert second["scenes"][1]["current_node"] == "planning"
    assert db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene2,)).fetchone() == (1, 0, 0, "blocked")
    assert db.execute("select coalesce(max(plan_version),0) from scene_plans where scene_id=?", (scene2,)).fetchone()[0] == 2
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (scene2,)).fetchone()[0] == 0
    assert planning_roles(adapter) == ["planning", "planning"]
    assert adapter.calls[1]["input"]["checkpoint"]["plan_version"] == 2
    assert not second["scenes"][1]["reused_calls"]
    assert not any(role.startswith("review_") or role == "memory_extraction" for role in planning_roles(adapter))
    db.close()


class ExactAdapter:
    def __init__(self, text):
        self.text, self.calls = text, []

    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        role = request["task_type"]
        if role == "planning":
            return unique_plan("第二场独特目标", "第二场独特动作")
        if role == "writing":
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": self.text, "word_count": 1250, "target_word_count": 1250,
                "complete": True, "writer_self_check": {"complete": True},
            }}
        raise AssertionError("exact repetition must prevent reviewers and memory")


# 7/8/9. Exact duplicate blocks immediately, counts once, and resume is idempotent.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "exact-count.db"
    from integration.run_real_test import save_plan
    db, book = seed(path)
    text = words(1000, token="samebody")
    save_plan(db, book, book + "_chapter_1", book + "_scene_1", unique_plan("第一场独特目标", "第一场独特动作"), "hc_p1")
    save_draft(db, book, book + "_chapter_1", book + "_scene_1", {
        "contract_type": "ProseDraft", "contract_version": "v1",
        "payload": {"text": text, "word_count": 1250, "target_word_count": 1250,
                    "complete": True, "writer_self_check": {"complete": True}},
    }, "hc_d1")
    db.execute("insert into quality_reports values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        book + "_scene_1_report_v1", book, book + "_chapter_1", book + "_scene_1",
        book + "_scene_1_draft_v1", "h", 1, "completed", "[]", 0, 0, 0, 0, 0, "complete",
        json.dumps({"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                    "events": ["调查"], "relationship_changes": [], "unresolved_threads": []}),
        "passed", "2026"))
    db.execute("update task_states set status='completed',current_node='memory_processing' where scene_id=?",
               (book + "_scene_1",))
    db.commit(); db.close()
    adapter = ExactAdapter(text)
    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    scene2, task2 = book + "_scene_2", book + "_scene_2_task"
    draft_id = scene2 + "_draft_v1"
    assert first["scenes"][1]["final_status"] == "blocked"
    assert first["scenes"][1]["block_reason"] == "duplicate_draft_content"
    assert db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene2,)).fetchone() == (1, 1, 1, "blocked")
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (scene2,)).fetchone()[0] == 1
    assert db.execute(
        "select count(*) from task_events where task_id=? and event_type='content_failure_blocked'",
        (task2,)).fetchone()[0] == 1
    assert [row[0] for row in db.execute(
        "select status from task_states where scene_id in (?,?) order by scene_id",
        (book + "_scene_3", book + "_scene_4"))] == ["queued", "queued"]
    assert planning_roles(adapter) == ["planning", "writing"]
    second_status = apply_content_failure(db, task2, "duplicate_draft_content", draft_id=draft_id, force_block=True)
    assert second_status == "blocked"
    assert db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene2,)).fetchone() == (1, 1, 1, "blocked")
    assert db.execute(
        "select count(*) from task_events where task_id=? and event_type='content_failure_blocked'",
        (task2,)).fetchone()[0] == 1
    db.close()
    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][1]["final_status"] == "blocked"
    assert db.execute(
        "select plan_attempt,content_attempt_in_plan,content_attempt_total,status from task_states where scene_id=?",
        (scene2,)).fetchone() == (1, 1, 1, "blocked")
    assert planning_roles(adapter) == ["planning", "writing"]
    db.close()

class QualityThenContentAdapter(SequenceAdapter):
    """Plan v1 is an illegal official target; later plans are valid."""

    def complete(self, request, timeout_seconds):
        if request["task_type"] == "planning" and request["input"]["checkpoint"]["plan_version"] == 1:
            self.calls.append(request)
            payload = plan(int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1]))
            payload["payload"]["target_word_count"] = 2000
            return payload
        return super().complete(request, timeout_seconds)


def rework_events(db):
    rows = db.execute(
        "select event_type,payload_json from task_events where task_id=? "
        "and event_type in ('rework_requested','content_failure_blocked','planning_failure_blocked',"
        "'length_rework_requested','length_failure_blocked') "
        "order by created_at",
        (TASK,)).fetchall()
    events = []
    for event_type, payload_json in rows:
        payload = json.loads(payload_json or "{}")
        events.append((event_type, payload.get("content_failure"), payload.get("plan_version"),
                       payload.get("failed_plan_version")))
    return events


# Planning-quality rework must not inflate plan_attempt. After Plan v2 the first
# three content failures follow the original Writing/Writing/Planning cycle;
# only the next content-planning cycle blocks. gates_15-style: 2000 then over-length.
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "quality-then-content.db"
    adapter = QualityThenContentAdapter([2000, 2000, 2000, 2000])

    first = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert first["scenes"][0]["final_status"] == "reworking_planning"
    assert task_counts(db) == (1, 0, 0, "reworking_planning")
    assert db.execute("select coalesce(max(plan_version),0) from scene_plans where scene_id=?", (SCENE,)).fetchone()[0] == 1
    assert db.execute("select count(*) from prose_drafts where scene_id=?", (SCENE,)).fetchone()[0] == 0
    assert [call["task_type"] for call in adapter.calls] == ["planning"]
    assert rework_events(db) == [("rework_requested", False, 2, 1)]
    db.close()

    second = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert second["scenes"][0]["final_status"] == "blocked"
    assert second["scenes"][0]["current_node"] == "writing"
    assert second["scenes"][0]["block_reason"] == "length_attempts_exhausted"
    assert task_counts(db) == (1, 0, 0, "blocked")
    assert [row[0] for row in db.execute(
        "select plan_version from scene_plans where scene_id=? order by plan_version", (SCENE,))] == [1, 2]
    assert draft_rows(db) == [(1, 2, 1, 1), (2, 2, 2, 2), (3, 2, 3, 3), (4, 2, 4, 4)]
    assert [call["input"]["checkpoint"]["plan_version"] for call in adapter.calls if call["task_type"] == "planning"] == [1, 2]
    assert [call["task_type"] for call in adapter.calls].count("writing") == 4
    assert rework_events(db) == [
        ("rework_requested", False, 2, 1),
        ("length_rework_requested", False, 2, None),
        ("length_rework_requested", False, 2, None),
        ("length_rework_requested", False, 2, None),
        ("length_failure_blocked", False, 2, None),
    ]
    assert second["scenes"][0]["length_failure_count_in_plan"] == 4
    assert second["scenes"][0]["semantic_failure_count_total"] == 0
    assert '"target_word_count": 2000' in db.execute(
        "select payload_json from scene_plans where scene_id=? and plan_version=1", (SCENE,)).fetchone()[0]
    db.close()


# 12 / 13. A new content-planning cycle gets four fresh length drafts.
class SemanticThenLengthAdapter(SequenceAdapter):
    def complete(self, request, timeout_seconds):
        if request["task_type"] == "review_world" and request["input"]["checkpoint"]["plan_version"] == 1:
            self.calls.append(request)
            return reviewer("world_consistency", result="failed", issue_count=1)
        return super().complete(request, timeout_seconds)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "new-plan-length-reset.db"
    adapter = SemanticThenLengthAdapter([1000, 1000, 1000, 346, 400, 500, 1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert task_counts(db)[:3] == (2, 0, 3)
    assert draft_rows(db) == [
        (1, 1, 1, 1), (2, 1, 2, 2), (3, 1, 3, 3),
        (4, 2, 1, 4), (5, 2, 2, 5), (6, 2, 3, 6), (7, 2, 4, 7),
    ]
    assert [call["task_type"] for call in adapter.calls].count("planning") == 2
    assert [call["task_type"] for call in adapter.calls].count("writing") == 7
    assert result["scenes"][0]["length_failure_count_in_plan"] == 3
    assert result["scenes"][0]["length_failure_count_total"] == 3
    assert result["scenes"][0]["semantic_failure_count_in_plan"] == 0
    assert result["scenes"][0]["semantic_failure_count_total"] == 3
    db.close()


# 17. suggestions-only reviews do not consume length or semantic attempts.
class SuggestionsOnlyAdapter(SequenceAdapter):
    def complete(self, request, timeout_seconds):
        if request["task_type"].startswith("review_"):
            self.calls.append(request)
            role = {"review_world": "world_consistency", "review_plot": "character_plot",
                    "review_style": "language_experience"}[request["task_type"]]
            payload = reviewer(role)["payload"]
            payload["suggestions"] = ["可保留档案室气味"]
            return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": payload}
        return super().complete(request, timeout_seconds)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "suggestions-only.db"
    adapter = SuggestionsOnlyAdapter([1000])
    result = run(db_path=path, adapter=adapter, execution_mode="sequential")
    db = sqlite3.connect(path)
    assert result["scenes"][0]["final_status"] == "waiting_confirmation"
    assert task_counts(db)[:3] == (1, 0, 0)
    assert result["scenes"][0]["length_failure_count_total"] == 0
    assert result["scenes"][0]["semantic_failure_count_total"] == 0
    db.close()


print("content rework boundary ok")

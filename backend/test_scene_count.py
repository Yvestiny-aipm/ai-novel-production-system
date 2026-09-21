import sqlite3, tempfile
from pathlib import Path

from integration.run_real_test import run
from integration.seed_real_test import seed


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"场次{number}推进", "entrance_state": {"before": number}, "exit_state": {"after": number},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "调查",
        "action_beats": [f"第{number}场查阅档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
        "progression_requirements": [{"progress_type": "new_clue", "target_key": f"灯塔线索{number}",
                                      "before_state": "未知", "expected_after_state": "发现线索",
                                      "acceptance_criterion": "正文出现线索"}],
    }}


def reviewer(role, number):
    evidence = f"第{number}场线索"
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": [], "suggestions": [], "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": [evidence], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
        "progression_assessment": {"status": "achieved", "achieved_items": [{
            "progress_type": "new_clue", "target_key": f"灯塔线索{number}", "before_state": "未知",
            "after_state": "发现线索", "evidence_text": evidence, "evidence_location": "draft.text",
        }], "missing_items": [], "evidence": evidence},
    }}


class Boom:
    def complete(self, request, timeout_seconds):
        raise RuntimeError("boom")


class OneSceneAdapter:
    def complete(self, request, timeout_seconds):
        role = request["task_type"]
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        if role == "planning":
            return plan(number)
        if role == "writing":
            marker = f"第{number}场线索"
            text = ("潮" * (1200 - len(marker))) + marker
            return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
                "text": text, "word_count": 1250, "target_word_count": 1250, "complete": True,
                "writer_self_check": {"complete": True},
            }}
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory",
                "target_key": f"林照-灯塔调查{number}", "action": "create", "before_value": None,
                "after_value": "林照完成本场调查", "evidence": f"第{number}场线索",
                "evidence_location": "draft.payload.text", "change_reason": "审查通过",
                "conflict_status": "none", "write_policy": "human_confirmation", "status": "pending",
            }}
        return reviewer({
            "review_world": "world_consistency",
            "review_plot": "character_plot",
            "review_style": "language_experience",
        }[role], number)


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "twenty.db"
    result = run(
        db_path=path,
        adapter=Boom(),
        execution_mode="sequential",
        model_environ={"REAL_TEST_SCENE_COUNT": "20"},
    )
    assert len(result["scenes"]) == 20
    assert result["scenes"][0]["final_status"] == "exception_pending"
    assert result["scenes"][1].get("skipped_due_to_dependency") is True
    db = sqlite3.connect(path)
    assert db.execute("select count(*) from scenes").fetchone()[0] == 20
    assert db.execute("select count(*) from chapters").fetchone()[0] == 10
    assert db.execute(
        "select chapter_id from scenes where scene_number=3"
    ).fetchone()[0].endswith("_chapter_2")
    db.close()


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "confirm.db"
    seed(path)
    blocked = run(db_path=path, adapter=OneSceneAdapter(), execution_mode="sequential")
    assert blocked["scenes"][0]["final_status"] == "waiting_confirmation"
    assert blocked["scenes"][0].get("auto_confirmed") is None

    path2 = Path(directory) / "auto.db"
    confirmed = run(
        db_path=path2,
        adapter=OneSceneAdapter(),
        execution_mode="sequential",
        model_environ={"REAL_TEST_AUTO_CONFIRM": "1"},
    )
    assert confirmed["scenes"][0]["final_status"] == "completed"
    assert confirmed["scenes"][0].get("auto_confirmed") is True
    db = sqlite3.connect(path2)
    assert db.execute(
        "select status from memory_proposals where scene_id=?",
        ("realtest_tide_archive_scene_1",),
    ).fetchone()[0] == "approved"
    db.close()

print("ok")

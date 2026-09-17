"""Phase 13 isolated backup/restore acceptance using the frozen Phase 12 fixture."""
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

from backend.backup_restore import create_full_backup, restore_full_backup, restore_scene_scope, restore_single_record, verify_backup
from integration.run_real_test import run


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "data/real_test_resume_33_prepared.db"
MIGRATION = ROOT / "db/migrations/001_initial.sql"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def count_rows(db, table):
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def plan(number):
    return {"contract_type": "ScenePlan", "contract_version": "v1", "payload": {
        "scene_goal": f"第{number}场推进调查", "entrance_state": {"scene": number}, "exit_state": {"scene": number + 1},
        "characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚", "conflict": "寻找林澜",
        "action_beats": ["调查档案"], "must_happen": ["发现线索"], "must_not_happen": ["谜团不能解决"],
        "knowledge_boundary": "灯塔只能保存记忆", "target_word_count": 1250,
        "acceptance_criteria": ["推进调查"], "validation_result": {"complete": True}, "ready_for_writing": True,
    }}


def draft(number):
    return {"contract_type": "ProseDraft", "contract_version": "v1", "payload": {
        "text": f"第{number}场：林照在灯塔档案室继续调查林澜的失踪。", "word_count": 1250,
        "target_word_count": 1250, "complete": True, "writer_self_check": {"complete": True},
    }}


def reviewer(role, number):
    return {"contract_type": "ReviewerResult", "contract_version": "v1", "payload": {
        "reviewer_role": role, "result": "passed", "findings": "通过", "issue_count": 0,
        "severity": "ordinary", "impact_scope": "local", "true_conflict_candidate": False,
        "scene_state": {"characters": ["林照"], "location": "灯塔档案室", "time_context": "夜晚",
                        "events": [f"第{number}场调查"], "relationship_changes": [], "unresolved_threads": ["林澜失踪"]},
    }}


class MockResumeAdapter:
    def complete(self, request, timeout_seconds):
        number = int(request["input"]["checkpoint"]["scene_id"].rsplit("_", 1)[-1])
        role = request["task_type"]
        if role == "planning": return plan(number)
        if role == "writing": return draft(number)
        if role == "memory_extraction":
            return {"contract_type": "MemoryProposal", "contract_version": "v1", "payload": {
                "memory_type": "narrative_event", "target_scope": "book_memory", "target_key": f"event-{number}",
                "action": "create", "before_value": None, "after_value": f"第{number}场调查推进",
                "evidence": "正文", "evidence_location": "draft.payload.text", "change_reason": "审查通过",
                "conflict_status": "none", "write_policy": "human_confirmation", "status": "pending",
            }}
        roles = {"review_world": "world_consistency", "review_plot": "character_plot", "review_style": "language_experience"}
        return reviewer(roles[role], number)


assert SOURCE.is_file(), "Phase 12 prepared fixture is required"
source_hash = sha256(SOURCE)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    backup = create_full_backup(SOURCE, root / "backups", "phase13-test")
    manifest = verify_backup(backup)
    assert manifest["status"] == "backup_success"
    assert sha256(SOURCE) == source_hash

    full = restore_full_backup(backup, root / "restore" / "full.db")
    source_db = sqlite3.connect(SOURCE)
    restored_db = sqlite3.connect(full)
    for table in ("scene_plans", "prose_drafts", "quality_reports", "memory_proposals", "memory_records", "task_states", "harness_calls"):
        assert count_rows(source_db, table) == count_rows(restored_db, table)
    source_db.close(); restored_db.close()

    # A single approved memory record can be restored without replacing any other history.
    target = sqlite3.connect(full)
    record_id = "mem_realtest_tide_archive_scene_2_proposal_v1"
    target.execute("DELETE FROM memory_records WHERE memory_record_id=?", (record_id,)); target.commit(); target.close()
    assert restore_single_record(backup, full, "memory_records", record_id)
    target = sqlite3.connect(full)
    assert target.execute("SELECT approval_status FROM memory_records WHERE memory_record_id=?", (record_id,)).fetchone()[0] == "approved"
    target.close()

    # A historical ProseDraft version can also be restored after its dependent
    # rows are removed from an isolated copy; the source hash remains exact.
    history = restore_full_backup(backup, root / "restore" / "history.db")
    draft_id = "realtest_tide_archive_scene_2_draft_v1"
    source_db = sqlite3.connect(SOURCE)
    source_hash_value = source_db.execute("SELECT draft_hash FROM prose_drafts WHERE draft_id=?", (draft_id,)).fetchone()[0]
    source_db.close()
    target = sqlite3.connect(history)
    target.execute("PRAGMA foreign_keys=ON")
    target.execute("DELETE FROM memory_records WHERE scene_id='realtest_tide_archive_scene_2'")
    target.execute("DELETE FROM memory_proposals WHERE scene_id='realtest_tide_archive_scene_2'")
    target.execute("DELETE FROM quality_reports WHERE scene_id='realtest_tide_archive_scene_2'")
    target.execute("DELETE FROM prose_drafts WHERE draft_id=?", (draft_id,))
    target.commit(); target.close()
    assert restore_single_record(backup, history, "prose_drafts", draft_id)
    target = sqlite3.connect(history)
    assert target.execute("SELECT draft_hash FROM prose_drafts WHERE draft_id=?", (draft_id,)).fetchone()[0] == source_hash_value
    assert not target.execute("PRAGMA foreign_key_check").fetchall()
    target.close()

    # A single scene can be rebuilt, with its task, calls and Contracts, into an isolated empty schema.
    scene_target = root / "restore" / "scene2.db"
    db = sqlite3.connect(scene_target); db.executescript(MIGRATION.read_text()); db.close()
    restored = restore_scene_scope(backup, scene_target, "realtest_tide_archive_scene_2")
    assert restored["task_states"] == 1 and restored["prose_drafts"] == 1 and restored["quality_reports"] == 1
    db = sqlite3.connect(scene_target)
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert db.execute("SELECT count(*) FROM harness_calls").fetchone()[0] == 7
    db.close()

    # A full isolated restore resumes from scene 3; completed scenes remain untouched and make zero calls.
    resume = restore_full_backup(backup, root / "restore" / "resume.db")
    db = sqlite3.connect(resume)
    before = {scene: db.execute("SELECT count(*) FROM harness_calls h JOIN task_states t ON t.task_id=h.task_id WHERE t.scene_id=?", (scene,)).fetchone()[0]
              for scene in ("realtest_tide_archive_scene_1", "realtest_tide_archive_scene_2")}
    db.close()
    result = run(db_path=resume, adapter=MockResumeAdapter(), execution_mode="sequential")
    assert result["scenes"][0]["skipped_existing"] and not result["scenes"][0]["calls"]
    assert result["scenes"][1]["skipped_existing"] and not result["scenes"][1]["calls"]
    assert result["scenes"][2]["final_status"] == "waiting_confirmation"
    db = sqlite3.connect(resume)
    for scene, value in before.items():
        current = db.execute("SELECT count(*) FROM harness_calls h JOIN task_states t ON t.task_id=h.task_id WHERE t.scene_id=?", (scene,)).fetchone()[0]
        assert current == value
    assert [row[0] for row in db.execute("SELECT status FROM task_states WHERE scene_id IN (?,?) ORDER BY scene_id", ("realtest_tide_archive_scene_4", "realtest_tide_archive_scene_5"))] == ["queued", "queued"]
    db.close()

assert sha256(SOURCE) == source_hash
print("backup restore acceptance ok")

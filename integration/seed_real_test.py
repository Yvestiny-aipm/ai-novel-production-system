"""Create the stage-12 isolated test database. Safe to rerun. Default seed is 5 scenes; scale tests use REAL_TEST_SCENE_COUNT."""
import os
import sqlite3
from pathlib import Path

FIXTURE = Path(__file__).parent / "real-test-fixture-v1.md"
BOOK_ID = "realtest_tide_archive"
DEFAULT_SCENE_COUNT = 5
SCENES_PER_CHAPTER = 2
CHAPTER_TITLES = {1: "Open Tide"}


def resolve_scene_count(environ=None, default=DEFAULT_SCENE_COUNT):
    env = environ if environ is not None else os.environ
    raw = str(env.get("REAL_TEST_SCENE_COUNT") or "").strip()
    if not raw:
        return default
    count = int(raw)
    if count < 1:
        raise ValueError("INVALID_SCENE_COUNT")
    return count


def chapter_number_for_scene(scene_number, scene_count, scenes_per_chapter=SCENES_PER_CHAPTER):
    if scene_count <= DEFAULT_SCENE_COUNT:
        return 1
    return (scene_number - 1) // scenes_per_chapter + 1


def auto_confirm_enabled(environ=None):
    env = environ if environ is not None else os.environ
    return str(env.get("REAL_TEST_AUTO_CONFIRM") or "").strip().lower() in {"1", "true", "yes"}


def seed(db_path, scene_count=None):
    count = DEFAULT_SCENE_COUNT if scene_count is None else scene_count
    root = Path(__file__).parents[1]
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA foreign_keys=ON")
    for path in sorted((root / "db/migrations").glob("*.sql")):
        migration = path.stem
        has_migrations = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        applied = has_migrations and db.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (migration,)
        ).fetchone()
        if not applied:
            db.executescript(path.read_text())
    columns = {row[1] for row in db.execute("PRAGMA table_info(task_states)")}
    if "execution_mode" not in columns:
        db.execute("ALTER TABLE task_states ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'sequential'")
    book = BOOK_ID
    db.execute(
        "INSERT OR IGNORE INTO books VALUES (?,?,?,?,?,?)",
        (book, "Tide-Mark Archive", 1, 1, "2026", "2026"),
    )
    db.execute(
        "INSERT OR IGNORE INTO creative_briefs VALUES (?,?,?,?,?,?,?)",
        ("brief_real_v1", book, 1, "confirmed", FIXTURE.read_text(), "fixture-v1", "2026"),
    )
    chapter_count = chapter_number_for_scene(count, count)
    for chapter_number in range(1, chapter_count + 1):
        chapter_id = f"{book}_chapter_{chapter_number}"
        title = CHAPTER_TITLES.get(chapter_number, f"Chapter {chapter_number}")
        db.execute(
            "INSERT OR IGNORE INTO chapters VALUES (?,?,?,?,?,?)",
            (chapter_id, book, chapter_number, title, "2026", "2026"),
        )
    for n in range(1, count + 1):
        chapter_id = f"{book}_chapter_{chapter_number_for_scene(n, count)}"
        scene = f"{book}_scene_{n}"
        task = f"{scene}_task"
        db.execute(
            "INSERT OR IGNORE INTO scenes VALUES (?,?,?,?,?,?,?,?)",
            (scene, book, chapter_id, n, None, None, "2026", "2026"),
        )
        db.execute(
            "INSERT OR IGNORE INTO task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task, "scene", book, chapter_id, scene, "planning", "queued", "start_planning", "[]", "[]", f"{task}_idempotency", "2026", "2026"),
        )
    db.commit()
    return db, book

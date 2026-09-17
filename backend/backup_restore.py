"""Isolated, checksum-verified SQLite backup and restore primitives.

Backups never contain API keys: only the database and safe, versioned routing
and Contract configuration are copied.  Restore operations refuse to overwrite
an existing database and restore historical rows with insert-only semantics.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
SIDECARS = (
    Path("contracts/contracts.schema.json"),
    Path("contracts/enums.json"),
    Path("backend/model_profiles.json"),
    Path("db/migrations/001_initial.sql"),
)
SCENE_TABLES = (
    "books", "chapters", "creative_briefs", "scenes", "task_states",
    "scene_plans", "context_packs", "prose_drafts", "quality_reports",
    "memory_proposals", "memory_records", "harness_calls", "task_events",
    "exception_queue",
)


class BackupRestoreError(RuntimeError):
    pass


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def integrity_check(path: Path) -> None:
    with readonly_connection(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok":
        raise BackupRestoreError(f"SQLITE_INTEGRITY_FAILED: {integrity}")
    if foreign_keys:
        raise BackupRestoreError("SQLITE_FOREIGN_KEY_CHECK_FAILED")


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _manifest(backup_dir: Path) -> dict:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        raise BackupRestoreError("BACKUP_MANIFEST_MISSING")
    return json.loads(manifest_path.read_text())


def create_full_backup(source_db: Path, backup_root: Path, backup_id: str) -> Path:
    """Create an immutable backup directory using SQLite's online backup API."""
    source_db, backup_root = Path(source_db), Path(backup_root)
    if not source_db.is_file():
        raise BackupRestoreError("SOURCE_DATABASE_MISSING")
    backup_dir = backup_root / backup_id
    if backup_dir.exists():
        raise BackupRestoreError("BACKUP_TARGET_EXISTS")
    backup_dir.mkdir(parents=True, mode=0o700)
    manifest = {
        "schema": "stage13-backup-v1",
        "backup_id": backup_id,
        "status": "backup_running",
        "created_at": utcnow(),
        "source_database_name": source_db.name,
        "artifacts": {},
    }
    _write_json(backup_dir / "manifest.json", manifest)
    try:
        database_copy = backup_dir / "database.sqlite"
        with readonly_connection(source_db) as source, sqlite3.connect(database_copy) as destination:
            source.backup(destination)
        integrity_check(database_copy)
        manifest["artifacts"]["database.sqlite"] = {"sha256": digest(database_copy), "size": database_copy.stat().st_size}
        with readonly_connection(database_copy) as database:
            manifest["schema_migrations"] = [row[0] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")]
        for relative in SIDECARS:
            source = ROOT / relative
            if not source.is_file():
                raise BackupRestoreError(f"BACKUP_SIDECAR_MISSING: {relative}")
            destination = backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            manifest["artifacts"][str(relative)] = {"sha256": digest(destination), "size": destination.stat().st_size}
        manifest.update(status="backup_success", completed_at=utcnow())
    except Exception as error:
        manifest.update(status="backup_failed", completed_at=utcnow(), error=str(error))
        _write_json(backup_dir / "manifest.json", manifest)
        raise
    _write_json(backup_dir / "manifest.json", manifest)
    return backup_dir


def verify_backup(backup_dir: Path) -> dict:
    backup_dir = Path(backup_dir)
    manifest = _manifest(backup_dir)
    if manifest.get("status") != "backup_success":
        raise BackupRestoreError("BACKUP_NOT_SUCCESSFUL")
    for relative, expected in manifest.get("artifacts", {}).items():
        artifact = backup_dir / relative
        if not artifact.is_file() or digest(artifact) != expected.get("sha256"):
            raise BackupRestoreError(f"BACKUP_CHECKSUM_MISMATCH: {relative}")
    integrity_check(backup_dir / "database.sqlite")
    return manifest


def restore_full_backup(backup_dir: Path, target_db: Path) -> Path:
    """Restore into a new isolated path; no existing target is ever replaced."""
    backup_dir, target_db = Path(backup_dir), Path(target_db)
    manifest = verify_backup(backup_dir)
    if target_db.exists():
        raise BackupRestoreError("RESTORE_TARGET_EXISTS")
    target_db.parent.mkdir(parents=True, exist_ok=True)
    restore_manifest = target_db.with_suffix(target_db.suffix + ".restore.json")
    status = {"schema": "stage13-restore-v1", "status": "restore_testing", "backup_id": manifest["backup_id"], "started_at": utcnow()}
    _write_json(restore_manifest, status)
    try:
        with readonly_connection(backup_dir / "database.sqlite") as source, sqlite3.connect(target_db) as destination:
            source.backup(destination)
        integrity_check(target_db)
        status.update(status="restore_success", completed_at=utcnow(), database_sha256=digest(target_db))
    except Exception as error:
        status.update(status="restore_failed", completed_at=utcnow(), error=str(error))
        _write_json(restore_manifest, status)
        raise
    _write_json(restore_manifest, status)
    return target_db


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    if table not in SCENE_TABLES:
        raise BackupRestoreError("RESTORE_TABLE_FORBIDDEN")
    values = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
    if not values:
        raise BackupRestoreError(f"RESTORE_TABLE_MISSING: {table}")
    return values


def _insert_unchanged(target: sqlite3.Connection, table: str, row: sqlite3.Row | tuple, columns: list[str]) -> bool:
    value = tuple(row[column] for column in columns) if isinstance(row, sqlite3.Row) else tuple(row)
    primary_key, primary_value = columns[0], value[0]
    saved = target.execute(f"SELECT * FROM {table} WHERE {primary_key}=?", (primary_value,)).fetchone()
    if saved is not None:
        saved_tuple = tuple(saved[index] for index in range(len(columns)))
        if saved_tuple != value:
            raise BackupRestoreError(f"RESTORE_HISTORY_CONFLICT: {table}:{primary_value}")
        return False
    target.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", value)
    return True


def restore_single_record(backup_dir: Path, target_db: Path, table: str, record_id: str) -> bool:
    """Restore one missing historical row; a differing row is never overwritten."""
    verify_backup(backup_dir)
    with readonly_connection(Path(backup_dir) / "database.sqlite") as source, sqlite3.connect(target_db) as target:
        source.row_factory = sqlite3.Row
        columns = _columns(source, table)
        row = source.execute(f"SELECT * FROM {table} WHERE {columns[0]}=?", (record_id,)).fetchone()
        if row is None:
            raise BackupRestoreError("BACKUP_RECORD_NOT_FOUND")
        _columns(target, table)
        restored = _insert_unchanged(target, table, row, columns)
        target.execute("PRAGMA foreign_keys=ON")
        if target.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupRestoreError("RESTORE_FOREIGN_KEY_CHECK_FAILED")
    return restored


def _scene_rows(source: sqlite3.Connection, table: str, book_id: str, chapter_id: str, scene_id: str, task_id: str):
    clauses = {
        "books": ("book_id=?", (book_id,)),
        "chapters": ("chapter_id=?", (chapter_id,)),
        "creative_briefs": ("book_id=?", (book_id,)),
        "scenes": ("scene_id=?", (scene_id,)),
        "task_states": ("task_id=?", (task_id,)),
        "scene_plans": ("scene_id=?", (scene_id,)),
        "context_packs": ("scene_id=?", (scene_id,)),
        "prose_drafts": ("scene_id=?", (scene_id,)),
        "quality_reports": ("scene_id=?", (scene_id,)),
        "memory_proposals": ("scene_id=?", (scene_id,)),
        "memory_records": ("scene_id=?", (scene_id,)),
        "harness_calls": ("task_id=?", (task_id,)),
        "task_events": ("task_id=?", (task_id,)),
        "exception_queue": ("task_id=?", (task_id,)),
    }[table]
    return source.execute(f"SELECT * FROM {table} WHERE {clauses[0]} ORDER BY { _columns(source, table)[0] }", clauses[1]).fetchall()


def restore_scene_scope(backup_dir: Path, target_db: Path, scene_id: str) -> dict[str, int]:
    """Restore one scene and all of its durable dependencies into an empty/compatible DB."""
    verify_backup(backup_dir)
    with readonly_connection(Path(backup_dir) / "database.sqlite") as source, sqlite3.connect(target_db) as target:
        source.row_factory = sqlite3.Row
        target.execute("PRAGMA foreign_keys=ON")
        scene = source.execute("SELECT book_id,chapter_id FROM scenes WHERE scene_id=?", (scene_id,)).fetchone()
        task = source.execute("SELECT task_id FROM task_states WHERE scene_id=?", (scene_id,)).fetchone()
        if scene is None or task is None:
            raise BackupRestoreError("BACKUP_SCENE_NOT_FOUND")
        restored = {}
        for table in SCENE_TABLES:
            columns = _columns(source, table)
            _columns(target, table)
            restored[table] = sum(_insert_unchanged(target, table, row, columns)
                                  for row in _scene_rows(source, table, scene[0], scene[1], scene_id, task[0]))
        if target.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupRestoreError("RESTORE_FOREIGN_KEY_CHECK_FAILED")
    return restored

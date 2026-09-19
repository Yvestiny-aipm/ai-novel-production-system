"""创建阶段12独立测试数据库；重复执行安全。"""
import sqlite3
from pathlib import Path
FIXTURE=Path(__file__).parent/'real-test-fixture-v1.md'
def seed(db_path):
    root=Path(__file__).parents[1]; db=sqlite3.connect(db_path); db.execute('PRAGMA foreign_keys=ON')
    # Migrations are append-only and may be safely applied to an existing
    # test database; never rerun an already recorded migration.
    for path in sorted((root/'db/migrations').glob('*.sql')):
        migration=path.stem
        has_migrations=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
        applied=has_migrations and db.execute('SELECT 1 FROM schema_migrations WHERE version=?',(migration,)).fetchone()
        if not applied:
            db.executescript(path.read_text())
    columns={row[1] for row in db.execute('PRAGMA table_info(task_states)')}
    if 'execution_mode' not in columns: db.execute("ALTER TABLE task_states ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'sequential'")
    book='realtest_tide_archive'; db.execute("INSERT OR IGNORE INTO books VALUES (?,?,?,?,?,?)",(book,'潮痕档案',1,1,'2026','2026'))
    db.execute("INSERT OR IGNORE INTO creative_briefs VALUES (?,?,?,?,?,?,?)",('brief_real_v1',book,1,'confirmed',FIXTURE.read_text(), 'fixture-v1','2026'))
    ch=f'{book}_chapter_1'; db.execute("INSERT OR IGNORE INTO chapters VALUES (?,?,?,?,?,?)",(ch,book,1,'公开潮汐','2026','2026'))
    for n in range(1,6):
        sc=f'{book}_scene_{n}'; task=f'{sc}_task'; db.execute("INSERT OR IGNORE INTO scenes VALUES (?,?,?,?,?,?,?,?)",(sc,book,ch,n,None,None,'2026','2026')); db.execute("INSERT OR IGNORE INTO task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",(task,'scene',book,ch,sc,'planning','queued','start_planning','[]','[]',f'{task}_idempotency','2026','2026'))
    db.commit(); return db,book

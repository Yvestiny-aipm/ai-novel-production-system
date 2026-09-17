import sqlite3, tempfile
from pathlib import Path
from seed_real_test import seed

with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'real_test.db'
    db, book=seed(path); db.close()
    db, book2=seed(path)
    assert book == book2
    assert db.execute("select count(*) from books").fetchone()[0] == 1
    assert db.execute("select count(*) from scenes").fetchone()[0] == 5
    assert db.execute("select count(*) from task_states").fetchone()[0] == 5
    assert db.execute("select count(*) from schema_migrations where version='001_initial'").fetchone()[0] == 1
    db.close()
print('seed idempotency ok')

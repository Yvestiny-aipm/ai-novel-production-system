import sqlite3, tempfile
from pathlib import Path
from seed_real_test import chapter_number_for_scene, resolve_scene_count, seed


assert resolve_scene_count({}) == 5
assert resolve_scene_count({"REAL_TEST_SCENE_COUNT": "20"}) == 20
assert chapter_number_for_scene(1, 5) == 1
assert chapter_number_for_scene(5, 5) == 1
assert chapter_number_for_scene(1, 20) == 1
assert chapter_number_for_scene(2, 20) == 1
assert chapter_number_for_scene(3, 20) == 2
assert chapter_number_for_scene(20, 20) == 10


with tempfile.TemporaryDirectory() as d:
    path=Path(d)/'real_test.db'
    db, book=seed(path); db.close()
    db, book2=seed(path)
    assert book == book2
    assert db.execute("select count(*) from books").fetchone()[0] == 1
    assert db.execute("select count(*) from scenes").fetchone()[0] == 5
    assert db.execute("select count(*) from chapters").fetchone()[0] == 1
    assert db.execute("select count(*) from task_states").fetchone()[0] == 5
    assert db.execute("select count(*) from schema_migrations where version='001_initial'").fetchone()[0] == 1
    db.close()

    path20=Path(d)/'real_test_20.db'
    db, book=seed(path20, scene_count=20)
    assert db.execute("select count(*) from scenes").fetchone()[0] == 20
    assert db.execute("select count(*) from chapters").fetchone()[0] == 10
    assert db.execute("select count(*) from task_states").fetchone()[0] == 20
    pairs=db.execute("select scene_number, chapter_id from scenes order by scene_number").fetchall()
    assert pairs[0] == (1, f"{book}_chapter_1")
    assert pairs[1] == (2, f"{book}_chapter_1")
    assert pairs[2] == (3, f"{book}_chapter_2")
    assert pairs[19] == (20, f"{book}_chapter_10")
    db.close()
    db, _=seed(path20, scene_count=20)
    assert db.execute("select count(*) from scenes").fetchone()[0] == 20
    db.close()
print('seed idempotency ok')

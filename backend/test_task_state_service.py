import sqlite3
import tempfile
from pathlib import Path
from backend.task_state_service import TaskStateService, VersionConflict

def test_state_flow_and_idempotency():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "x.db"
        schema = Path(__file__).parents[1] / "db/migrations/001_initial.sql"
        con = sqlite3.connect(db); con.executescript(schema.read_text()); con.execute("INSERT INTO books VALUES ('b1','x',NULL,1,'2026','2026')"); con.execute("INSERT INTO chapters VALUES ('c1','b1',1,NULL,'2026','2026')"); con.execute("INSERT INTO scenes VALUES ('s1','b1','c1',1,NULL,NULL,'2026','2026')"); con.commit(); con.close()
        s = TaskStateService(db)
        a = s.create(task_id="t1", task_scope="scene", book_id="b1", scene_id="s1", idempotency_key="k1")
        assert s.create(task_id="t2", task_scope="scene", book_id="b1", scene_id="s1", idempotency_key="k1")["task_id"] == "t1"
        a = s.transition("t1", expected_state_version=1, status="running", next_action="start_planning")
        a = s.transition("t1", expected_state_version=a["state_version"], node="writing", status="reworking_writing", next_action="rewrite", increment_content=True)
        assert (a["content_attempt_in_plan"], a["content_attempt_total"]) == (1, 1)
        try: s.transition("t1", expected_state_version=1, status="paused", next_action="resume")
        except VersionConflict: pass
        else: raise AssertionError("stale version accepted")
        assert s.get("t1")["state_version"] == 3
        s.close()

if __name__ == "__main__": test_state_flow_and_idempotency(); print("ok")

"""TaskState 的唯一写入口。

Agent 只提交结果；状态、次数和事件由本服务在同一事务中更新。
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

NODES = {"planning", "writing", "reviewing", "arbiter", "memory_processing", "human_confirmation", "exception_handling"}
STATUSES = {"queued", "running", "reworking_writing", "reworking_planning", "waiting_confirmation", "paused", "exception_pending", "blocked", "completed", "skipped", "cancelled"}
ACTIVE = {"queued", "running", "reworking_writing", "reworking_planning", "exception_pending"}

class StateError(ValueError): pass
class VersionConflict(StateError): pass

def now(): return datetime.now(timezone.utc).isoformat()

class TaskStateService:
    def __init__(self, db_path: str | Path):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")

    def create(self, *, task_id, task_scope, book_id, idempotency_key, scene_id=None, chapter_id=None):
        stamp = now()
        try:
            with self.db:
                self.db.execute("""INSERT INTO task_states
                    (task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,
                     active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id,task_scope,book_id,chapter_id,scene_id,"planning","queued","start_planning","[]","[]",idempotency_key,stamp,stamp))
                self._event(task_id, "created", None, None, "planning", "queued", "system", None)
        except sqlite3.IntegrityError as exc:
            row = self.db.execute("SELECT * FROM task_states WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row:
                return dict(row)
            raise
        return self.get(task_id)

    def get(self, task_id):
        row = self.db.execute("SELECT * FROM task_states WHERE task_id=?", (task_id,)).fetchone()
        if not row: raise StateError("TASK_NOT_FOUND")
        return dict(row)

    def transition(self, task_id, *, expected_state_version, node=None, status=None, next_action=None, reason=None, actor_id="system", event_type="transition", increment_content=False, increment_technical=False):
        with self.db:
            row = self.db.execute("SELECT * FROM task_states WHERE task_id=?", (task_id,)).fetchone()
            if not row: raise StateError("TASK_NOT_FOUND")
            if row["state_version"] != expected_state_version: raise VersionConflict("VERSION_CONFLICT")
            node = node or row["current_node"]; status = status or row["status"]; next_action = next_action or row["next_action"]
            if node not in NODES or status not in STATUSES: raise StateError("INVALID_STATE")
            if status == "completed" and node not in {"memory_processing", "human_confirmation"}: raise StateError("INVALID_COMPLETION_NODE")
            content_plan = row["content_attempt_in_plan"] + int(increment_content)
            content_total = row["content_attempt_total"] + int(increment_content)
            technical = row["technical_retry_count"] + int(increment_technical)
            version = row["state_version"] + 1
            history = json.loads(row["state_history_json"])
            history.append({"version": version, "from": {"node": row["current_node"], "status": row["status"]}, "to": {"node": node, "status": status}, "reason": reason, "at": now(), "actor_id": actor_id})
            self.db.execute("""UPDATE task_states SET current_node=?,status=?,next_action=?,content_attempt_in_plan=?,content_attempt_total=?,technical_retry_count=?,state_version=?,state_history_json=?,updated_at=? WHERE task_id=?""", (node,status,next_action,content_plan,content_total,technical,version,json.dumps(history),now(),task_id))
            self._event(task_id,event_type,row["current_node"],row["status"],node,status,actor_id,reason)
        return self.get(task_id)

    def _event(self, task_id, event_type, from_node, from_status, to_node, to_status, actor_id, reason):
        self.db.execute("INSERT INTO task_events(event_id,task_id,event_type,from_node,from_status,to_node,to_status,payload_json,actor_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"evt_{task_id}_{self.db.total_changes}",task_id,event_type,from_node,from_status,to_node,to_status,"{}",actor_id,reason,now()))

    def close(self): self.db.close()

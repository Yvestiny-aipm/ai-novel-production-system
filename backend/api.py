"""阶段 4 最小 REST API（Python 标准库，无额外运行依赖）。"""
import json, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
try:
    from .task_state_service import TaskStateService, StateError, VersionConflict
except ImportError:
    from task_state_service import TaskStateService, StateError, VersionConflict

ERRORS = {"VERSION_CONFLICT": "任务状态已变化，请刷新后重试", "TASK_NOT_FOUND": "任务不存在", "INVALID_INPUT": "请求参数无效", "INVALID_STATE": "非法状态", "INVALID_ACTION": "非法任务动作"}
ACTION = {"pause": (None, "paused", "resume"), "resume": (None, "running", "start_planning"), "cancel": (None, "cancelled", "none"), "skip_scene": ("human_confirmation", "skipped", "none"), "retry_planning": ("planning", "reworking_planning", "start_planning"), "retry_writing": ("writing", "reworking_writing", "rewrite"), "retry_technical_call": ("exception_handling", "exception_pending", "retry_technical")}

class Handler(BaseHTTPRequestHandler):
    service = None
    def _send(self, code, data=None, error=None):
        body = {"request_id": self.headers.get("X-Request-ID", "req_" + uuid.uuid4().hex)}
        if error: body["error"] = {"code": error, "message": ERRORS.get(error, error), "details": {}}
        else: body["data"] = data
        raw = json.dumps(body).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _json(self):
        try: return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except Exception: raise StateError("INVALID_INPUT")
    def do_GET(self):
        if self.path.startswith("/api/v1/tasks/"):
            try: return self._send(200, self.service.get(self.path.rsplit("/", 1)[-1]))
            except StateError as e: return self._send(404, error=str(e))
        return self._send(404, error="INVALID_INPUT")
    def do_POST(self):
        try:
            payload = self._json()
            if self.path == "/api/v1/tasks":
                required = ["task_id", "task_scope", "book_id", "idempotency_key"]
                if any(k not in payload for k in required): raise StateError("INVALID_INPUT")
                return self._send(202, self.service.create(**payload))
            marker = "/api/v1/tasks/"
            if marker in self.path and self.path.endswith("/actions"):
                task_id = self.path[len(marker):-len("/actions")]
                action = payload.get("action"); expected = payload.get("expected_state_version")
                if action not in ACTION or not isinstance(expected, int): raise StateError("INVALID_INPUT")
                node, status, next_action = ACTION[action]; return self._send(200, self.service.transition(task_id, expected_state_version=expected, node=node, status=status, next_action=next_action, reason=payload.get("reason"), actor_id=payload.get("actor_id", "user"), event_type=action))
            return self._send(404, error="INVALID_INPUT")
        except VersionConflict as e: return self._send(409, error=str(e))
        except StateError as e: return self._send(400, error=str(e))
        except Exception: return self._send(500, error="TECHNICAL_ERROR")
    def log_message(self, *_): pass

def serve(db_path="./data/novel.db", host="127.0.0.1", port=8000):
    Handler.service = TaskStateService(db_path); HTTPServer((host, port), Handler).serve_forever()

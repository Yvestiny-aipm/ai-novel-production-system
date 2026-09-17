# REST API（阶段 4）

启动：`PYTHONPATH=backend python3 -c "from api import serve; serve('./data/novel.db')"`

接口：

- `POST /api/v1/tasks`：创建任务。必须携带 `task_id`、`task_scope`、`book_id`、`idempotency_key`，可带章节和场次 ID。
- `GET /api/v1/tasks/{task_id}`：查询 TaskState。
- `POST /api/v1/tasks/{task_id}/actions`：执行 `pause`、`resume`、`cancel`、`skip_scene`、`retry_planning`、`retry_writing`、`retry_technical_call`。

动作请求必须带 `expected_state_version`。过期版本返回 HTTP 409 和 `VERSION_CONFLICT`；所有响应都有 `request_id`，重复幂等键返回原任务。

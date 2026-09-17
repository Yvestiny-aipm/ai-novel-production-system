# 统一后端任务状态控制

`TaskStateService` 是 TaskState 的唯一写入口。它在同一事务中更新状态版本、次数、状态历史和 `task_events`；Agent 不应直接写数据库。

支持创建任务（幂等键重复返回原任务）、读取任务和带 `expected_state_version` 的原子状态流转。阶段 4 再将其接入 REST 接口。

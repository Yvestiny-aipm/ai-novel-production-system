# 业务 Agent（阶段 8）

Agent 只接收已组装的 ContextPack，通过 Harness 提交一次独立任务，并返回对应 Contract。规划返回 `ScenePlan`，生文返回 `ProseDraft`，三位审查员分别返回 `QualityReport`，记忆提取返回 `MemoryProposal`，裁决返回 `QualityReport`。流程编排和写入权限由统一后端负责。

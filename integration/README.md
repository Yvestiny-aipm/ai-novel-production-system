# 阶段 12 真实模型测试

运行前准备：设置当前路由所需密钥（默认 `SILICONFLOW_API_KEY`；结构化任务走 Foundry 时还要 `AZURE_FOUNDRY_CLAUDE_API_KEY` 或 `AZURE_FOUNDRY_AUTH=entra`），准备包含测试作品、场次、TaskState 和 ContextPack 的数据库，再设置 `RUN_REAL_MODEL=1`。入口 `run_real_test.py` 会先检查开关和密钥，真实调用必须沿用 Harness 的独立调用、重试、Contract 校验和 `harness_calls` 记录。

测试计划为 3～5 场，每场约 1250 字，至少包含正常场、返工场和记忆提案场。未满足前置条件时 runner 返回 `not_run`，不把 Mock 结果标记为真实模型结果。

测试资料：[`real-test-fixture-v1.md`](real-test-fixture-v1.md)，包含 CreativeBrief、5个连续场次规划和 ContextPack 检查要求。

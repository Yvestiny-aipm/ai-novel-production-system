# 阶段 6 模型配置

`model_profiles.json` 为规划、生文、三位审查员、记忆提取和裁决保留 DeepSeek 默认路由。运行时还可用环境变量把部分任务切到 Azure Foundry（`STRUCTURED_PROVIDER=azure_foundry`）。运行前设置当前供应商所需密钥：`SILICONFLOW_API_KEY`，以及可选的 `AZURE_FOUNDRY_CLAUDE_API_KEY`。可用 `SILICONFLOW_API_URL` 或 `AZURE_FOUNDRY_CLAUDE_ENDPOINT` 覆盖地址。密钥不写入仓库、Contract 或 `harness_calls`。

实际响应仍必须返回阶段 1 定义的 Contract 包络，由 Harness 校验后才进入业务节点。没有密钥时适配器明确失败，不会伪造模型结果。

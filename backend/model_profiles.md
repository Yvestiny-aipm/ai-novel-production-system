# 阶段 6 模型配置

`model_profiles.json` 为规划、生文、三位审查员、记忆提取和裁决保留默认路由。未设置 `WRITING_PROVIDER` 时生文仍可走硅基流动；二十场脚本默认 `WRITING_PROVIDER=deepseek`，模型 `deepseek-flash`。结构化任务可用 `STRUCTURED_PROVIDER=azure_foundry`。运行前只设置当前路由所需密钥：官网生文用 `DEEPSEEK_API_KEY`，硅基流动用 `SILICONFLOW_API_KEY`，Foundry 用 `AZURE_FOUNDRY_CLAUDE_API_KEY` 或 `AZURE_FOUNDRY_AUTH=entra`。可用 `DEEPSEEK_API_URL`、`SILICONFLOW_API_URL` 或 `AZURE_FOUNDRY_CLAUDE_ENDPOINT` 覆盖地址。密钥不写入仓库、Contract 或 `harness_calls`。

实际响应仍必须返回阶段 1 定义的 Contract 包络，由 Harness 校验后才进入业务节点。没有密钥时适配器明确失败，不会伪造模型结果。

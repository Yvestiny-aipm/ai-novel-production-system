# 阶段 6 模型配置

`model_profiles.json` 为规划、生文、三位审查员、记忆提取和裁决统一配置 DeepSeek 路由。运行前设置 `SILICONFLOW_API_KEY`；可用 `SILICONFLOW_API_URL` 覆盖地址。密钥不写入仓库、Contract 或 `harness_calls`。

实际响应仍必须返回阶段 1 定义的 Contract 包络，由 Harness 校验后才进入业务节点。没有密钥时适配器明确失败，不会伪造模型结果。

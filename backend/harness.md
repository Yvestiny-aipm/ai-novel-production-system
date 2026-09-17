# Harness（阶段 5）

`Harness.run` 接收 Agent 任务类型、输入资料和目标 Contract，依据 `ModelProfile` 选择供应商适配器，隔离每次调用并写入 `harness_calls`。适配器只实现 `complete(request, timeout_seconds)`，替换供应商时只替换路由配置和适配器。

调用失败会按配置进行技术重试，仍失败可切换备用供应商并最终抛出 `TECHNICAL_ERROR`。响应先经过 Contract 包络校验；格式不正确会记录 `contract_invalid`，不会返回给下一个节点。API 密钥不进入数据库，适配器应从环境变量或密钥管理读取。

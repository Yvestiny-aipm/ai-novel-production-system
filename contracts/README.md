# Contracts

第一版固定七类业务交接内容：

- CreativeBrief：作品初始资料
- ScenePlan：场景规划卡
- ContextPack：当前资料包
- ProseDraft：场景正文草稿
- QualityReport：审查报告
- MemoryProposal：记忆变更提案
- TaskState：任务状态记录

各类内容按自身范围绑定必要信息：作品级 CreativeBrief 只绑定作品和资料版本；场次级内容绑定作品、章节、场次和内容版本；TaskState 按任务范围绑定作品、章节或场次。只有会重复生成的内容记录尝试次数，所有记录保留状态、来源任务、时间和内容哈希。

字段职责固定如下：ContextPack 是按 Agent 和节点生成的只读资料快照；ProseDraft 与 QualityReport 通过正文编号和正文哈希绑定；`ProseDraft.word_count` 与 `actual_character_count` 都是后端按“去除空白字符后计数”的真实正文长度，`model_reported_word_count` 仅保留模型自报值供审计；默认长度质量门槛为 1000～1500 字符，未通过时不得进入审查。正文通过长度门槛后，`content_similarity_checks` 以 `char_ngram_jaccard_v1` 仅比较同书最近三场已确认场次的规划、开头和正文，检测记录不可覆盖；人物、地点和时间不作为规划重复依据。ProseDraft 的 `writer_self_check` 只是生文自检；QualityReport 通过 `accepted_scene_state` 确认本场最终状态，并通过 `routing_recommendation` 提出处理建议；MemoryProposal 必须写明目标范围、目标对象、修改前后内容和写入权限，提案的 `target_key` 必须是当前作品中具体人物、地点、事件或场景事实的稳定标识；TaskState 分开记录最后到达的业务节点、生命周期状态和下一步动作，并保存状态版本与状态变更记录。`status=completed` 是终态，`current_node` 保留最后完成的业务节点（例如 `human_confirmation` 或 `memory_processing`），不表示任务仍在该节点运行。

状态边界已经固定：`paused` 表示可恢复，`blocked` 表示必须解决问题或确认跳过；记忆提案等待人工确认时任务保持 `waiting_confirmation`；技术异常先进入异常队列并回到原业务节点；跳过场次必须记录连续性缺口；`plan_version` 是计划版本号，`plan_attempt` 是正文内容规划周期，两者不是同一个数字。字数失败是格式质量问题，只回 Writing，不占用 `content_attempt_in_plan` / `content_attempt_total`，也不增加 `plan_attempt`；同一 `plan_version` 最多 4 份仅因字数返工的 Draft，第 4 份仍不在 1000～1500 时以 `length_attempts_exhausted` 阻塞。TaskState 的这两项内容计数只统计剧情内容失败（实质重复、世界观/人物剧情/明显语言硬问题、剧情推进失败）。`ProseDraft.content_attempt_in_plan` / `content_attempt_total` 只表示该场 Draft 生成顺序，不能当成 TaskState 失败计数。

数据库边界已经固定：QualityReport 保存历史确认状态，scenes 保存当前状态入口；正式记忆统一写入 `memory_records`；三位审查员结果先放在 QualityReport 的结构化字段中；ContextPack 的资料来源先放在固定快照中；所有版本、状态、幂等和任务唯一性约束由数据库和统一后端共同保证。

接口边界已经固定：第一版使用 REST 和异步任务，前端只调用统一后端；任务动作通过 `action` 明确暂停、恢复、取消、跳过、重新规划、重新生文或技术重试；状态修改必须携带 `expected_state_version`，生成任务必须携带 `idempotency_key`；结果查询支持分页和版本指定；人工确认和异常处理必须记录操作者与原因。

检索边界已经固定：检索由上下文与数据管理执行，不新增 Retrieval Agent；第一版使用结构化筛选、关键词检索和向量检索组装按 Agent 和节点固定的 ContextPack；待定提案不进入生文资料包；每个资料包保留来源版本、排除项、缺失项、冲突标记和快照哈希。

模型路由边界已经固定：第一版使用硅基流动 DeepSeek 完成全链路测试，每场按约 1250 字测试；正式长文测试时切换公司中转站，切换只改 Harness 配置；Agent 不直接指定模型或供应商；每次调用独立隔离，失败按技术重试和备用模型规则处理。

前端边界已经固定：同一个前端项目分为创作工作台和管理后台；创作区域处理作品生产和人工确认，管理区域处理用户、模型配置、Harness 路由、日志、异常和备份；权限由统一后端校验，管理员不直接编辑正文和正式世界规则。

运行保障边界已经固定：业务数据库和 Harness 调用记录每日备份，关键操作前手动备份；支持单条、单场或单章、整库恢复；备份失败进入异常队列；每月在隔离环境进行真实恢复测试。

验收边界已经固定：第一版使用固定模拟响应验收正常、返工、裁决、阻塞、异常、记忆权限、重复任务、跳过和版本冲突等 12 个系统分支；使用硅基流动 DeepSeek 连续测试 3～5 场，每场约 1250 字；正式长文测试时再切换公司中转站。

模型请求与响应属于 Harness 的内部技术记录，不增加第八类业务交接内容。

## 机器可读规范

- [`contracts.schema.json`](contracts.schema.json) 固定七类业务 Contract 的字段、类型和必填项。
- [`enums.json`](enums.json) 集中固定流程节点、任务状态、版本状态、审查、记忆提案和备份状态枚举。

每个业务对象通过 `contract_type`、`contract_version` 和 `payload` 包络传输；`payload` 的具体结构引用同一文件 `$defs` 中对应的 Contract 定义。新增字段或枚举值应提升 `contract_version`，并同步更新数据库迁移和接口文档。

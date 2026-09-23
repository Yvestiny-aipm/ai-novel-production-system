# AI 长文生产系统 · 系统架构 README

对照文档：[系统架构README-竞品](./系统架构README-竞品.md)  
两份文档标题一一对应，可并排阅读。

仓库：<https://github.com/solve-context/ai-novel-production-system>  
本地目录：`/Users/czy/AI长文系统/新系统开发`  
基线：`v0.1.0`（提交 `7ac9fbe`）  
更新日期：2026-09-22

---

## 1. 项目定位

公司内部使用的长篇小说生产系统。目标不是给新手一个创作工作台，而是按场稳定生成、检查、保存和恢复长篇正文，保证前后设定一致、可审计、可恢复。

核心判断：

- AI 只提出规划、正文、审查意见和记忆提案。
- 统一后端是唯一流程控制中心。
- 正式世界规则和公共资料必须人审，Agent 不能自己改正史。
- 第一版不接入 n8n，不引入第二套编排器。

## 2. 目标用户与成功标准

| 项 | 内容 |
|---|---|
| 用户 | 内部生产团队，不是大众作者 |
| 成功标准 | 一场正文过字数、重复、推进和三位审查员；正式设定不漂移；断点可恢复 |
| 当前验收 | 5 场公司 API 已通过；`20_n` 二十场、`40_e` 四十场机器关卡已过；尚未声称稳定产出 20 万字 |
| 非目标 | 面向大众的自动导演、漫画 / 短剧、复杂多租户、自动学习路由 |

## 3. 生产粒度与规模

| 项 | 规定 |
|---|---|
| 生产单位 | 场 |
| 单场目标 | 约 1250 字（去空白字符） |
| 单场硬范围 | 1000～2300 字通过；目标仍建议 1200～1350 |
| 章结构 | 每章两场 |
| 全书目标 | 约 80 章、160 场、20 万字 |
| 测试阶梯 | 5 场 → 20～40 场 → 160 场 |

没有「全书最多 N 万字」的产品上限。规模由场次计划决定。

## 4. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | 静态工作台 + 管理页原型（`frontend/`） |
| 后端 | Python 3.11+，标准库 HTTP，统一后端 |
| 编排 | 统一后端 + `TaskStateService`，无 LangGraph / n8n |
| 模型调用 | `Harness` + 供应商适配器 |
| 数据库 | SQLite，一份业务库 |
| 检索 | 第一版结构化筛选 + 关键词；向量检索留了原则，未作为主依赖 |
| 工程形态 | 单仓库，按目录分工，不是 pnpm monorepo |

模型路由：写作默认硅基流动 DeepSeek 或 DeepSeek 官网；规划 / 审查等结构化任务可走 Azure Foundry Claude。2026-09-23 暂定：生文和记忆走 Foundry Opus 5.5，规划、三审、裁决走 OpenAI GPT-6 Sol。空环境仍默认硅基流动。

## 5. 仓库结构

```text
backend/       统一后端、Harness、Agent 薄适配、ContextPack、关卡、测试
contracts/      七类业务 Contract Schema 与枚举
db/             SQLite 迁移
integration/    真实模型测试、备份恢复
acceptance/     固定 Mock 验收
frontend/       创作工作台和管理后台原型
systems/        编排 / 生成 / 审查 / 一致性的目录说明（逻辑边界，不是独立服务）
docs/           方案、交接、验收
scripts/        一键启动与规模测试
data/           运行库和备份（不入库）
```

关键代码：

| 职责 | 文件 |
|---|---|
| Agent 薄适配 | `backend/agents.py` |
| 模型调用 | `backend/harness.py` |
| 任务状态 | `backend/task_state_service.py` |
| 资料包 | `backend/context_pack.py` |
| 字数 / 重复 / 推进 | `backend/prose_length.py`、`content_similarity.py`、`progression.py` |
| 记忆确认 | `backend/memory_confirmation.py` |
| 角色 / 设定 Canon | `backend/character_canon.py`、`setting_canon.py` |
| 已成立事实 | `backend/established_facts.py` |
| REST | `backend/api.py`、`backend/local_server.py` |

## 6. 系统架构

```text
创作工作台 / 管理后台
        ↓  REST /api/v1
统一后端（唯一流程控制中心）
  ├─ TaskStateService          状态、次数、事件的唯一写入口
  ├─ ContextPackService        按 Agent / 节点组装只读快照
  ├─ 质量关卡                  字数、重复、人物/场地、已成立事实、推进（确定性代码）
  ├─ 记忆权限                  自动保存 or 人工确认
  └─ Harness
       ├─ 模型路由
       ├─ 超时 / 重试 / 预算 / 调用记录
       └─ 适配器：SiliconFlow / DeepSeek / Azure Foundry / OpenAI
            ↓
       Agent（只交任务类型和 ContextPack）
            planning / writing / review_* / arbiter / memory_extraction
```

总原则：

> Harness 管模型调用；适配器只管供应商格式；Agent 只提出任务；统一后端控制流程；上下文与数据管理控制资料和写入权限。

硬边界：

- Agent 不访问数据库、不调其他 Agent、不改 `TaskState`、不改正式世界规则。
- 前端不直接访问 Agent、Harness 或数据库。
- 所有状态只能由统一后端写。

`systems/` 是逻辑切分，不是四套可独立部署的服务：

| 目录 | 职责 | 不负责 |
|---|---|---|
| `systems/orchestrator` | 组织三个系统运行 | Canon 真值判断 |
| `systems/generation` | 规划、写作、重写 | 审查裁决、正式写入 |
| `systems/quality-review` | 剧情、人物、节奏、文风评价 | 改任务状态 |
| `systems/consistency` | Canon、状态、上下文、一致性检查 | 生成正文 |

## 7. 模块边界

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| 前端 | 发起任务、看简化状态、确认提案、处理异常 | 改正式设定、直接调模型 |
| 统一后端 | 调用顺序、返工、暂停、阻塞、异常队列、幂等 | 自己生成小说文本 |
| 规划 Agent | 产出 `ScenePlan` | 写正文、改资料 |
| 生文 Agent | 产出 `ProseDraft` | 改规划、改资料 |
| 三位审查员 | 各出一份审查结果 | 决定任务下一步 |
| 裁决 Agent | 严重 / 跨场 / 真冲突时仲裁 | 日常每场都跑 |
| 记忆 Agent | 出 `MemoryProposal` | 直接写 `memory_records` |
| 上下文与数据管理 | 资料、检索、ContextPack、版本、权限 | 替 Agent 编故事 |
| 公共图书馆 | 方案已预留跨书模板范围 | 第一版尚未做成可勾选的角色库界面 |

## 8. 主链路与 Agent 编排

编排者是统一后端，不是 Agent 自己组队。每次模型调用都是独立请求，不共享隐含聊天窗口。

```text
确认 CreativeBrief
 → 组装 Planning ContextPack
 → planning Agent → ScenePlan
 → ScenePlan 质量门槛（字段、就绪、字数目标、推进项、上场 before_state）
 → 组装 Writing ContextPack
 → writing Agent → ProseDraft
 → 真实字数校验
 → 实质重复检测
 → 人物 / 场地 / 已成立事实门栏
 → review_world / review_plot / review_style（隔离并行或顺序，互不看见对方意见）
 → 剧情推进核验
 → 后端汇总 QualityReport
 → 严重 / 普通问题>10 / 跨场 / 真冲突 → arbiter
 → 通过后 memory_extraction → MemoryProposal
 → 权限检查：场景事实自动写；其余人审
 → 本场 completed
 → 下一场读取上场此刻（确认状态去掉未发生表述）+ 已成立事实账本
```

Agent 注册表（`backend/agents.py`）：

| Agent 任务类型 | 产出 Contract | 何时调用 |
|---|---|---|
| `planning` | `ScenePlan` | 每场开始，或内容失败回规划 |
| `writing` | `ProseDraft` | 规划通过后；字数失败只回这里 |
| `review_world` | `QualityReport`（角色 `world_consistency`） | 字数和重复关卡通过后 |
| `review_plot` | `QualityReport`（角色 `character_plot`） | 同上 |
| `review_style` | `QualityReport`（角色 `language_experience`） | 同上 |
| `arbiter` | `QualityReport` | 按需 |
| `memory_extraction` | `MemoryProposal` | 审查和推进都通过后 |

`current_node` 只有：`planning`、`writing`、`reviewing`、`arbiter`、`memory_processing`、`human_confirmation`、`exception_handling`。

前端动作只转成命令：`pause`、`resume`、`cancel`、`skip_scene`、`retry_planning`、`retry_writing`、`retry_technical_call`。Agent 不能自己改状态。

## 9. 业务交接物

固定七类 Contract，不增加第八类。模型请求明细只记在 `harness_calls`。

| Contract | 范围 | 作用 |
|---|---|---|
| `CreativeBrief` | 作品级 | 确认后只读。书名、类型、主题、篇幅、人物、关系、世界、冲突、风格、结局、特别要求 |
| `ScenePlan` | 场级 | 本场目标、进出状态、人物、地点、冲突、必须 / 禁止、知识边界、推进项 |
| `ContextPack` | 场 + Agent + 节点 | 本次实际使用的资料快照，生成后不可改 |
| `ProseDraft` | 场级，每版一份 | 正文；正式字数以后端去空白计数为准 |
| `QualityReport` | 绑定准确 `draft_id` / `draft_hash` | 三审汇总、路由建议、`accepted_scene_state` |
| `MemoryProposal` | 一条一个变化 | 只提案，不写正史 |
| `TaskState` | 按 `task_scope` | `current_node`、`status`、`next_action` 分开 |

`ContextPack` 必须记录：目标 Agent / 节点、brief / plan / story_state / canon 版本、规划快照哈希、已确认 / 排除 / 缺失 / 冲突资料、内容哈希。

上场状态只能来自上场 `QualityReport.accepted_scene_state`，不能从正文或待定提案推断。

## 10. 上下文与记忆

资料四层：

1. 作品固定资料（已确认 Brief、正式规则）
2. 作品动态资料（已确认记忆）
3. 章节 / 场次资料（本场规划、上场确认状态）
4. 参考资料（低优先级，不能盖过正式规则）

组装优先级：`brief` > `world_rule` > `book_memory` > `scene_memory` > `chapter` > `reference`。`status=pending` 的来源直接跳过。

记忆写入权限：

```text
scene_fact       + scene_memory      → auto_save
narrative_event  + book_memory       → human_confirmation
world_rule       + book_memory       → human_confirmation
character_detail + character_memory  → human_confirmation
public_library   + 公共图书馆        → human_confirmation（方案已留，界面未做成库）
```

`memory_records` 一张表存场景记忆、作品资料、公共图书馆和正式规则，靠范围、类型、审批状态区分。

当前缺口：`character_canon` / `setting_canon` 仍是灯塔故事硬编码。换书要换 snapshot，还没有「从公共库勾选 → 复制到本书 → 确认后进 ContextPack」。

## 11. 质量与返工

确定性关卡在审查员之前或之后拦截，不靠模型自报。

| 关卡 | 规则 | 失败路由 |
|---|---|---|
| 真实字数 | 去空白后计 `actual_character_count` | 只回 Writing，不占剧情次数 |
| 实质重复 | 同书最近 3 个已确认场；完全相同立即阻塞 | 正文重复回 Writing；规划重复回 Planning |
| 剧情推进 | 至少一项正文可证实的推进 | 内容失败计数 |
| 三审 | 世界 / 人物剧情 / 语言，隔离后由后端汇总 | 普通问题回 Writing；严重或真冲突走裁决 |
| 上场 before_state | Planning 必须复制上场确认状态 | 回 Planning，不进 Writing |
| 已成立事实 | 账本非空时，正文不得写全书否定（从未进入 / 一层也没进等）。流水 120（头 30 + 尾 90）；kind=canon 的进入/见到/死亡类不裁 | 内容失败回 Writing |
| 确认状态拆读 | 下场 previous / baseline 只用此刻，账本不收未发生句 | 不打回本场，只影响下场读取 |

计数分开：

- 字数失败：同一 `plan_version` 最多 4 份长度 Draft，第 4 份仍失败则 `length_attempts_exhausted` 阻塞。
- 剧情内容失败：第 1、2 次回 Writing，第 3 次回 Planning 并增加 `plan_attempt`，再失败则阻塞整书。
- 技术故障：进异常队列，不占内容次数。

没有「正文可读就记质量债并继续下一场」。审查未通过不能标 `completed`，也不能开始下一场。

## 12. 状态、恢复与权限

`TaskState` 三字段：

- `current_node`：当前或最后完成的业务节点
- `status`：`queued` / `running` / `reworking_*` / `waiting_confirmation` / `paused` / `blocked` / `exception_pending` / `completed` / `skipped` / `cancelled`
- `next_action`：后端下一步动作

含义：

- `paused`：可继续，只是暂等
- `blocked`：必须解题或确认跳过
- `waiting_confirmation`：记忆等人审，不能提前完成
- `completed`：审查通过且记忆处理结束

恢复原则：历史记录只追加。同编号同内容可复用，不同内容拒绝覆盖。支持整库、单场、单条恢复。跳过必须留下连续性缺口，缺口进入下一场 ContextPack。

权限：普通人发起和查看任务；确认正式规则、写公共图书馆、跳过场次、取消任务要更高权限。管理员不直接编辑正文和正式世界规则。

## 13. 模型调用

`Harness` 按任务类型选 `ModelProfile`，适配器只做格式转换。每次调用记录作品、场次、Agent、资料包版本、模型、提示词版本、耗时、用量、结果。

Agent 不指定模型。切换供应商只改路由配置。结果未知时先查原任务，不直接重打。

## 14. 资料复用

方案已预留公共图书馆，第一版未做成可运营的角色库 / 世界库。

当前复用方式：

- 同书：上场确认状态 + 已确认 `memory_records` 进入下场 ContextPack
- 跨书：`public_library` 范围和人审权限已在枚举里，没有模板勾选和绑定副本流程
- Canon：按书换硬编码 snapshot，不是从库里挑

设计意图（尚未落地）：公共库是模板；绑定到本书时复制一份；本书运行态不回写公共库。

## 15. 当前能力与未做事项

已完成：阶段 1～13 代码闭环、七类 Contract、Harness、三审、记忆权限、三项关卡、五场真实链路、备份恢复、本地一键启动。

未完成：20～40 场连续稳定、160 场 / 20 万字验收、通用角色 / 设定库、书级卷场清单、伏笔账本、RAG 主路径、完整生产界面、部署环境每日备份和告警。

明确不做（第一版）：n8n、大众自动导演、漫画 / 短剧、多组织、图数据库、Agent 自主无限检索。

## 16. 文档入口

- [方案基线 V1](./方案基线-v1.md)
- [Cursor 项目交接说明 V2](./CURSOR项目交接说明-v2.md)
- [Contract 说明](../contracts/README.md)
- [根 README（安装与运行）](../README.md)
- [竞品同结构 README](./系统架构README-竞品.md)

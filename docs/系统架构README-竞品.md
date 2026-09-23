# Biz Novel Studio · 系统架构 README（竞品对照）

对照文档：[系统架构README-本项目](./系统架构README-本项目.md)  
两份文档标题一一对应，可并排阅读。

仓库：<https://github.com/ExplosiveCoderflome/AI-Novel-Writing-Assistant>  
公开名：AI 小说创作工作台 / Biz Novel Studio  
读库日期：2026-09-21  
当时状态：约 3.0k star、564 fork、1,244 commits，桌面版 0.4.27  
许可：AGPL-3.0 + 商用双许可（可学设计，不要搬源码和提示词）

漫画工作台、短剧工坊不纳入本对照。

---

## 1. 项目定位

面向长篇小说完成度的 AI Native 开源创作工作台。目标不是单段补全，而是从一句灵感走到完整小说。

核心判断：

- 目标用户优先是完全不懂写作的新手。
- 先把整本书写完，再优化写得多精巧。
- AI 当导演：规划、判断、调度、执行、追踪。
- 世界、角色、写法、拆书都是可召回的长期资产。

英文名从 AI Novel Production Engine 改成 Biz Novel Studio，仓库地址未改。

## 2. 目标用户与成功标准

| 项 | 内容 |
|---|---|
| 用户 | 写作新手；也给研究 Agent / LangGraph / RAG 的开发者看 |
| 成功标准 | 用户能挂机把书写完；方向、角色、卷章、正文都有检查点可恢复 |
| 当前验收 | 公开产品持续迭代，没有「已稳定产出 N 万字」的对内验收口径 |
| 非目标（本对照） | 漫画、短剧；也不追求公司交付级三审关卡 |

和本项目的根本差别：他们优化「新手完成率」，我们优化「场级一致性与可追责生产」。

## 3. 生产粒度与规模

| 项 | 规定 |
|---|---|
| 生产单位 | 章（整章一次生成，不按场多轮拼接） |
| 单章目标 | 每章自带 `targetWordCount`；常见示例 800～1200 字 |
| 单章带宽 | 软下限 85%、软上限 115%、硬上限 125% 目标字数 |
| 章结构 | 规划侧可拆 3～8 个场景卡，热路径仍整章一次写 |
| 全书目标 | 用户可调目标字数和作品形态；规划按章数分档 |
| 规划档位 | 最少 12 章；30 章以下短篇；30～59 紧凑全书；60 章以上连载；规划器能想到 1500+ 章、最多 24 卷 |

完成合同：

- 目标 ≤ 60 章：`compact_book`，最多再加 5 章收尾。
- 目标 > 60 章：`serial_book`，使用「前 30 章承诺」。

公开文档没有「全书最长 N 万字」。真正会停机的是额度、单章 token 熔断、无可用正文或必须重规划。

## 4. 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19、Vite、React Router、TanStack Query、Plate |
| 桌面 | Electron（Windows 安装包 / portable） |
| 后端 | Express 5、Prisma、Zod |
| 编排 | 自研 Director Pipeline + Worker 租约；README 提到 LangChain / LangGraph，主链不靠现成图硬跑 |
| 模型调用 | Prompt Registry + 结构化输出 + 多供应商路由 |
| 数据库 | 默认 SQLite，可上 PostgreSQL |
| 检索 | Qdrant RAG，可关 |
| 工程形态 | pnpm workspace monorepo：`client/` `server/` `shared/` `desktop/` `site/` |

供应商：OpenAI、DeepSeek、SiliconFlow、xAI 等。规划、正文、审阅、拆书可走不同模型。

## 5. 仓库结构

```text
client/     React 创作工作台
server/     Express + Prisma + Agent Runtime + Creative Hub
shared/     前后端共享类型
desktop/    Electron 壳
site/       GitHub Pages 介绍站
docs/       设计、Wiki、公开文档、检查点
infra/      部署
scripts/    启动辅助
```

和本项目对照时，真正对得上的是 `server/src`：

| 职责 | 竞品位置 | 对本项目 |
|---|---|---|
| 自动导演 | `server/src/services/novel/director/` | 我们没有书级导演层 |
| 章节 runtime | `server/src/services/novel/runtime/` | 对应统一后端场级主链 |
| Prompt | `server/src/prompting/` | 对应 `Harness` 提示词版本 |
| 任务中心 | `server/src/services/task/` | 对应 `TaskState` + 前端状态 |
| Worker | `server/src/workers/directorWorker.ts` | 我们长任务仍更靠近 API / 脚本进程 |
| 时间线 | `server/src/modules/timeline/` | 我们用 `accepted_scene_state`，无独立时间线模块 |
| Creative Hub | `server/src/creativeHub/` | 我们没有对话中枢 |

## 6. 系统架构

```text
创作者（Web / Electron）
        ↓  HTTP /api
Express 控制面
  只收命令、回轻量投影，不 await 长任务
        ↓  写入
DirectorRunCommand（持久化命令 + 租约）
        ↓  Worker 领取
自动导演运行时
  步骤编排 / 策略 / 检查点 / 恢复
        ↓  推进章节时只能走
ChapterRuntimeCoordinator（唯一正文链）
  生成 → 接收闸门 → 局部修复 → 时间线终态
        ↓
Prisma 持久状态 + 任务投影
        ↓
Prompt Registry → 外部模型
```

控制面和执行面隔离是他们最硬的工程决策。Web API 不直接跑全书。运行状态从 `DirectorRun` / `DirectorStepRun` / `DirectorArtifact` / `DirectorEvent` 投影，前端不能自己猜「现在该按哪个按钮」。

另一条硬约束：手动单章、批量、自动导演、修复，改正文必须进同一套 `novelProductionOrchestrator + ChapterRuntimeCoordinator`。导演不能自己写一套 writer。

Creative Hub 是查询、诊断、导航，不是生产器。只读工具白名单，禁止从对话里写正文或恢复任务。

## 7. 模块边界

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| 自动导演 | 从灵感到书契约、世界、角色、卷、章节任务 | 直接改正文 |
| 章节 runtime | 唯一正文生成 / 修复 / 终态提交 | 各自入口复制一套 writer |
| 时间线模块 | 锚点、事件、钩子、约束 | 决定正文是否可接收 |
| 角色资源账本 | 跨章影响行动的关键资源 | 普通道具清单 |
| 写法引擎 | 可保存、绑定、试写的写法资产 | 只在提示词里写一句「文风」 |
| 知识库 / RAG | 拆书和文档召回 | 覆盖本书已发生事实 |
| 基础角色库 / 世界样本 | 跨书模板 | 直接当本书正史 |
| 任务中心 | 排队、失败、来源页 | 判断故事好不好 |
| Creative Hub | 问进度、给入口 | 创建小说、写正文、修文 |
| 导出 | 读已有数据出 TXT / MD / JSON | 回写生产状态 |

本对照不展开漫画、短剧。他们自己也规定：主链没跑通前不打开衍生工坊。

## 8. 主链路与 Agent 编排

他们不是「五类 Agent 各出一份 Contract」，而是「导演步骤 + 唯一章节 runtime」。自然语言意图先被路由到导演阶段或章节任务。

### 8.1 三层生产链

```text
灵感层
  一句灵感 / 题材 / 推进模式
  → 多套书级方向 + 书名组
  → 用户确认方向（服务端快照为事实源）

自动导演层
  创建小说
  → 故事宏观 / 书契约 / 写作约束
  → 开篇世界切片 / 核心角色
  → 卷战略 / 卷骨架 / 节奏板 / 章节清单
  → 章节任务单（JIT，真正写该章前才补齐）
  → checkpoint：章节批次就绪

章节执行层
  轻量预检
  → 整章 writer
  → 一次接收闸门
  → 最多一次局部 patch
  → 时间线终态（stable 或 degraded）
  → 异步 artifact_delta 回灌
  → 下一章
```

快路径只等首章必需资产：精简故事基础、开篇世界切片、核心角色、3～5 章路线、第 1 章执行合同。完整世界手册、非开篇角色、远期卷规划后置。

### 8.2 控制面命令

用户动作先变成 `DirectorRunCommand`：继续、恢复、重试、接管、审批、取消。Worker 租约执行 `StepModule`。Pipeline 只编排，不直接知道业务表和 Prompt 细节。

### 8.3 章节热路径里的「Agent」

没有本项目这种 `planning / writing / review_* / memory` 注册表。章节侧更接近一条流水线角色：

| 角色 | 作用 | 对应本项目 |
|---|---|---|
| writer | 整章一次生成 | `writing` |
| acceptance gate | 一次结构化接收判断 | 三审 + 推进关卡的合并版 |
| patch repair | 最多一次局部替换 | 生文返工，但他们默认不整章重写 |
| heavy repair | 仅明确选择时整章重写 | 我们内容失败第 1、2 次就回 Writing |
| artifact_delta | 章后一次抽取事实 / 角色 / 伏笔 | `memory_extraction`，但他们常自动回灌 |
| 问题治理 | `auto_retry` / `continue_with_warning` / `pause_for_manual` / `fail_task` | 我们的返工次数和 `blocked` |

AI 返回的 `continuePolicy` 只是诊断，不能越过任务启动时冻结的问题策略。

### 8.4 和本项目编排的差异

- 他们有书级导演，我们确认 Brief 后直接下场规划。
- 他们正文链唯一，入口可以很多；我们入口少，场级链也唯一。
- 他们局部质量问题可以记质量债后写下一章；我们审查不过就不能下场。
- 他们自动修复每章最多一次；我们字数和内容失败分开计数，内容可回规划。

## 9. 业务交接物

没有本项目这七个固定 Contract 名称，但有对等资产。对照：

| 本项目 | 竞品 | 差别 |
|---|---|---|
| `CreativeBrief` | 书契约 + 故事宏观 + 前 30 章承诺 + 读者体验合同 | 他们把书级契约拆得更细，并有卷 / 章任务单 |
| `ScenePlan` | 章节任务单 + 场景卡 + 义务合同 | 他们按章；场景卡不强制进热路径 |
| `ContextPack` | `GenerationContextPackage` 运行时组装 | 他们不是不可变业务快照；用 content hash 做检查点 |
| `ProseDraft` | `Chapter.content` + 工作版本 | 他们终稿前候选稿不能覆盖正史 |
| `QualityReport` | 接收闸门结果 + `riskFlags.qualityLoop` | 一次闸门，不是三位隔离审查员 |
| `MemoryProposal` | `StateChangeProposal` / artifact_delta | 场景类常自动入账；角色候选可确认 |
| `TaskState` | `novelWorkflowTask` + Director 命令 / 步骤 / 事件 | 控制面命令不代表业务完成 |

章节义务合同（热路径共用）：`mustHitNow`、`mustPreserve`、`requiredPayoffTouches`、`requiredCharacterAppearances`、`requiredGoalChanges`、`canDefer`、`forbiddenCrossings`。

## 10. 上下文与记忆

写作必带块（不能被摘要挤掉）：

1. 章节任务单
2. 读者体验合同（回报、主动性、钩子责任）
3. 上一章实际正文尾段
4. 角色硬事实（按本章参与者筛选）
5. 续写约束（如有）

软信息（简介、行为提示）可压缩。知识库 / 拆书是补充，冲突时本书已发生事实优先。

记忆分账本，不是一张 `memory_records`：

| 账本 | 记什么 |
|---|---|
| Novel Fact Ledger | 已发生硬事实 |
| Payoff Ledger | 伏笔窗口与兑现 |
| Character Resource Ledger | 影响行动的关键资源 |
| 角色信息边界 | 谁知道 / 谁还不知道 |
| Timeline | 时间锚点与钩子，不决定正文是否可接收 |

待确认提案不能写成既成事实。高风险已入账资源可以当约束，不能据此再写不可逆变化。

回灌在正文稳定之后。`artifact_delta` 一次低温结构化抽取摘要、硬事实、状态、角色资源、伏笔、关系、信息边界。同一章同一正文 hash 不重复抽。

### 10.1 对我们「后半忘前半」能参考什么

他们吃过同类问题：章任务单如果在开书时一次排完，后面写出来的事实进不去规划，义务会和前文打架。对策不是加一句书专属禁令，而是单独开一张 **Novel Fact Ledger**：

- 只记已验收或正文观测确认的不可逆事实，不记写前计划。
- 分类：`completed` / `revealed` 全书保留；`state_changed` 只留近 15 章。
- 下一章 JIT 规划时整本账本进任务单（「避免重复或矛盾」）；写作时进 `completedMilestones`（「不得重复追求或重新触发」）。
- 上一章正文尾段、角色硬事实是必带块，不能被摘要挤掉。
- 待确认提案不能写成既成事实。

他们**没有**确定性「后文不得否定账本」门栏，主要靠注入 + 模型。路线图仍写：世界 / 角色 / 伏笔 / 时间线要稳定进后续上下文。所以这是可抄的骨架，不是已经做完的答案。

我们这边缺的正是这条第二通道：下场 ContextPack 现在只有 brief + 上一场快照，库里的 `memory_records` 没有累计灌回去。可学：账本与上场快照分开、确认后才写入、规划/写作都看见。不要学：质量债后继续下场、整章一次过、只用提示词当门栏。

## 11. 质量与返工

默认哲学：先出可读正文，局部问题不拦全书。

| 情况 | 动作 |
|---|---|
| 局部质量 / 自然度 / 未到期伏笔 | 登记质量债，继续下一章 |
| 局部修复失败但正文可读 | `defer_and_continue` |
| 接收闸门暂时不可用 | 保留正文，记复查债 |
| 无可用正文 / 明确重规划 / 用量熔断 | 停在已保存章节边界 |
| 受保护人工内容 / 数据完整性 | 安全规则强制暂停，用户偏好不能覆盖 |

自动修复每章最多一次，与运行异常重试共享预算。`heavy_repair` 不能因为轻修失败自动升级。

重规划带作用域：默认 `local_window`，只刷新当前章之后没有正文的计划；`global_book` 才整书停。已有正文和用户保护内容不能被局部重规划覆盖。

确定性本地检测（不调 LLM）会抓 AI 自述、占位符、截断、复读等，作为 `prose_*` 问题。略超目标字数不能直接失败或截断。

和本项目相反的一点：他们允许「正文可用 + 质量债 + 下一章」；我们不允许审查未通过就下场。

## 12. 状态、恢复与权限

控制面：`DirectorRunCommand` 排队、租约、幂等。  
执行面：`DirectorRun` / `DirectorStepRun` / 产物 / 事件。  
展示面：`DirectorDashboardView` 统一裁决主按钮，材料层不能各自判状态。

恢复：

- 服务重启不静默续跑长任务，从产物断点判断可恢复范围。
- `pendingManualRecovery` 只有用户明确继续才能解开。
- 有正文的失败任务从最早未完成章续，不重写已完成或已降级收束的章。
- 候选确认以服务端快照为准，前端回传正文不能覆盖中文候选。

界面分简易书架和专业工作台，只是显示偏好，不是写权限。两种界面背后仍是同一条全书生产链。

## 13. 模型调用

统一走 Prompt Registry 和结构化输出。任务类型可拆路由。输出上限按子任务分开：writer 按目标长度；验收 / 修复 / 抽取用更小上限。

单章累计 token 超过硬预算会 `usage_anomaly` 熔断，暂停后续自动执行。这是费用保护，不是文学字数墙。

DeepSeek Flash / Pro 做结构化开书任务时，系统会先关思考再出结构，减少空转空白。

## 14. 资料复用

这是他们比我们落地得更完整的部分。分层如下：

| 层 | 内容 | 与本书关系 |
|---|---|---|
| 公共模板 | 基础角色库、世界样本、题材基底、推进模式、写法资产 | 只读模板；绑定后复制到本书 |
| 本书正史 | 本书角色、本书世界、事实、伏笔、资源账本 | 写作和审查只读这一层 |
| 参考资料 | 拆书角色、知识库文档 | 帮助理解或召回；不能当正史 |

关键规则：

- 同名角色不自动视为同一角色，跨书记忆按主体隔离。
- 世界样本导入会在本书建副本；同步必须人点，不能后台静默覆盖。
- 基础角色库对话只帮助理解人格，不改模板、不改任何小说。
- 拆书角色访谈必须带章节锚点，不能泄露锚点之后的情节，不能写回原文或新书。
- 章节写作按参与者筛选角色硬事实和资源，不把整库塞进 prompt。

本项目方案里的 `public_library` 就是这一层的预留位；竞品已经做成可运营的库和绑定流程。

## 15. 当前能力与未做事项

已能做：自动导演开书、方向候选、书契约、世界 / 角色、卷章规划、整本或按范围自动写章、质量债、检查点恢复、写法引擎、拆书、知识库 RAG、角色库、世界样本、任务中心、模型路由、Windows 桌面版、介绍站。

路线图仍强调：稳定自动导演连续执行、降低误停和重复审校、让世界 / 角色 / 伏笔 / 时间线稳定进后续上下文。

本对照不纳入：漫画、短剧、角色形象生图、标题工坊的产品细节。

## 16. 文档入口

竞品仓库内：

- 根 `README.md`：产品入口
- `docs/public/flow/end-to-end-production.md`：三层生产链
- `docs/wiki/workflows/auto-director-runtime.md`：导演控制面 / 执行面
- `docs/wiki/workflows/chapter-production-chain.md`：章节热路径
- `docs/wiki/architecture/module-boundaries.md`：模块边界
- `docs/wiki/workflows/character-resource-ledger.md`：角色资源账本
- `shared/types/volumePlanning.ts`：章数分档与卷上限
- `shared/types/chapterLengthControl.ts`：单章 85% / 115% / 125% 带宽

对照本项目：

- [系统架构README-本项目](./系统架构README-本项目.md)
- [方案基线 V1](./方案基线-v1.md)

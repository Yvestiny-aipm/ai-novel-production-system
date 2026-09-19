# AI长文小说生产系统：Cursor 项目交接说明 V2

更新日期：2026-09-19

仓库目录：`/Users/czy/AI长文系统/新系统开发`

GitHub：<https://github.com/solve-context/ai-novel-production-system>

这份文档用于把项目交给 Cursor 继续开发。请先阅读本文件、`docs/方案基线-v1.md`、`README.md`，再修改代码。

## 当前目标

做出一个公司内部使用的长篇小说生产系统，能够按“场”稳定生成、检查、保存和恢复长篇小说。

第一版的生产参数是：每场目标约 1250 字，允许范围 1000～1500 字；每章两场；完整作品约 80 章、20 万字。

当前还不能声称已经稳定产出 20 万字。三项质量关卡和公司 API 五场验证已经完成；下一阶段先配置一键启动，再做 20～40 场连续测试，最后再做 160 场完整作品测试。

## 已完成

### 基础系统和方案

- 已完成阶段 1～13 的代码和本地验收闭环。
- 已确定不接入 n8n，采用独立统一后端。
- 已确定七类业务 Contract：`CreativeBrief`、`ScenePlan`、`ContextPack`、`ProseDraft`、`QualityReport`、`MemoryProposal`、`TaskState`。
- 已确定 Harness 统一管理模型调用，供应商适配器只负责格式转换。
- Agent 不直接调用模型、数据库或其他 Agent，也不能直接修改正式世界规则。
- 三位审查员分别检查世界规则、人物和剧情结构、语言体验；后端统一汇总结果。

### 第一版真实链路

阶段 12 已完成过 5 场真实模型链路测试，代表性数据库为：

`data/real_test_rerun_25.db`

已验证的内容包括：

- 规划→生文→三位审查员→记忆提取链路可以运行。
- 场次按顺序执行，版本号可以递进。
- 前一场确认状态可以进入下一场 ContextPack。
- 同书数据隔离，当前抽查没有发现跨作品污染。
- 人工确认、断点恢复、已完成场次跳过和历史记录不可覆盖已经有测试。
- 阶段 13 已完成备份、恢复、单场恢复和恢复后续跑验收。

### 第一项质量关卡：真实字数

已完成代码：

- `backend/prose_length.py`
- `db/migrations/002_prose_draft_length_validation.sql`
- `backend/test_prose_length_gate.py`
- `backend/test_rerun25_length_regression.py`

规则：后端去除空白字符后重新计算实际字符数，模型自报的 `word_count` 只保留审计用途。实际字数低于 1000 或高于 1500 时，在审查前拦截并只回 Writing。字数失败不占用剧情内容返工次数，也不触发 Planning。

对旧样本 `rerun_25` 的只读结果为：346、676、583、358、519，五场均为 `under_length`。这证明旧样本的“1250 字”是模型自报值，不能作为真实长度。

### 第二项质量关卡：实质重复

已完成代码：

- `backend/content_similarity.py`
- `db/migrations/003_content_similarity_checks.sql`
- `backend/test_content_similarity_gate.py`
- `backend/test_rerun25_similarity_regression.py`

当前采用同书最近 3 个已确认场次的本地字符 n-gram 相似度检测：

- 正文完全相同：沿用 `duplicate_draft_content` 阻塞。
- 正文整体相似度达到 0.55：正文返工。
- 规划目标和行动节拍高度相似：重新规划。

开头句式相似暂不作为第一版硬性阻断条件，因为当前项目优先解决事实和剧情一致性。

### 第三项质量关卡：剧情推进

已完成代码和主链路接入：

- `backend/progression.py`
- `db/migrations/004_scene_progression_checks.sql`
- `backend/test_progression_gate.py`
- `backend/test_rerun25_progression_regression.py`
- `contracts/contracts.schema.json` 已增加 `progression_requirements` 和推进结果字段。

每场至少完成一项可由正文证实的推进。证据必须是当前 Draft 的连续原文；规划质量失败回 Planning，正文未推进按内容返工计数。

### 公司 API 与五场验证

结构化任务可走 Azure Foundry Claude Opus 5，写作默认仍走硅基流动 DeepSeek。代表性数据库：

`data/real_test_foundry_1.db`

五场均已 `completed`：字数、重复、推进和审查通过，第 4、5 场全书记忆已人工确认。真实数据库不入库。

## 当前分支和 Git 状态

- 当前分支：`main`
- 基线标签：`v0.1.0`（提交 `7ac9fbe`），不要改写。
- 本次冻结：三项质量关卡、Foundry 适配器和五场公司 API 验证。
- 禁止修改或覆盖历史测试数据库。

## 主链路

```text
ProseDraft 格式校验
→ 后端真实字数校验
→ 实质重复检测
→ 三位审查员
→ 剧情推进核验
→ QualityReport
→ Memory Agent
→ 下一场
```

## 下一步

1. 配置一键启动和测试环境。
2. 先跑 20 场，再跑 40 场连续测试。
3. 修复规模测试暴露的问题。
4. 再进入 160 场、20 万字完整作品测试。
5. 配置部署环境的备份和告警。

## 质量判断标准

### 字数

- 正式字数以 `actual_character_count` 为准。
- 1000～1500 字通过。
- 少于 1000 或高于 1500 字返回 Writing 返工。
- 第三次仍失败返回 Planning。

### 重复

- 完全相同正文直接 `blocked`。
- 正文实质重复返回 Writing 返工，第三次仍失败返回 Planning。
- 规划实质重复返回 Planning。
- 开头相似暂时只记录，不阻断。

### 剧情推进

- 每场至少有一项推进目标。
- 推进目标必须有正文中的证据。
- 证据必须能在当前正文中找到，不能只来自 ContextPack 或模型自报字段。
- 推进前状态要和上一场确认状态一致。
- 推进后状态要进入本场 `accepted_scene_state`。
- 推进失败是内容问题，不是技术异常；不能写入正式记忆，也不能开始下一场。

## 关键决策

- 采用统一后端和 Harness，避免每个 Agent 各自维护模型调用和状态。
- 采用 SQLite、追加式记录和版本号，保证能够审计、恢复且不覆盖历史。
- 采用同书、按场次顺序的 ContextPack，避免跨作品污染。
- 正式世界规则必须人工确认，Agent 无权自动修改。
- 第一版不接入 n8n，减少外部编排依赖和排错范围。
- 第一版先使用确定性本地校验，不急着加入向量数据库或复杂多 Agent 编排；等基本质量关卡稳定后再扩展 RAG、混合检索和更复杂的 Agent 协作。

## 常用命令

所有命令先进入项目目录：

```sh
cd "/Users/czy/AI长文系统/新系统开发"
```

初始化数据库：

```sh
./db/init.sh ./data/novel.db
```

运行固定验收：

```sh
PYTHONPATH=. python3 acceptance/run_cases.py
```

运行全部后端测试：

```sh
for f in backend/test_*.py; do PYTHONPATH=. python3 "$f"; done
```

检查 Python 语法和差异格式：

```sh
python3 -m py_compile backend/*.py integration/*.py
git diff --check
```

启动最小后端 API：

```sh
PYTHONPATH=. python3 -c 'from backend.api import serve; serve()'
```

预览静态前端：

```sh
python3 -m http.server 8124 --directory frontend
```

真实模型测试必须使用新数据库，并在新开的终端设置密钥：

```sh
export RUN_REAL_MODEL=1
export SILICONFLOW_API_KEY="你的api-key"
export EXECUTION_MODE=sequential
export REAL_TEST_DB="$PWD/data/real_test_new.db"
python3 integration/run_real_test.py
```

不要把 API Key 写入代码、文档、数据库或 Git。

## 已知问题

1. `rerun_25` 的旧正文实际严重不足；新代码已按真实字数拦截，并已用 `real_test_foundry_1.db` 重新验证五场。
2. 三项关卡和公司 API 五场验证已完成，仍不等于 20 万字稳定产出，还需 20～40 场和 160 场测试。
3. 记忆提取可能返回“无新增记忆”，该分支已有固定测试。
4. 每日备份、保留策略、失败告警和生产部署仍需要在部署环境配置。
5. 前端目前是静态工作台和管理后台原型，完整生产界面和后端部署配置尚未完成。
6. 开发时要保留历史，不要使用强制回退、force push 或覆盖式写入；不要改写 `v0.1.0`。

## 交付要求

每完成一个质量关卡，都要输出：修改文件、规则、测试结果、历史数据库只读结果、是否调用真实 API、是否修改历史数据库、是否提交 Git。

三项关卡和五场公司 API 验证已通过。后续规模测试的新改动单独提交，不要改写 `v0.1.0`。

---

# 完整方案补充与协作规则

下面内容是前期方案讨论中已经确认的细节。开发时如果与当前代码不一致，以本文件的边界为准，先修正代码或提出冲突，不要默默改变方案。更早、更长的阶段记录仍保留在 `docs/开发交接说明-v1.md`，本节用于把 Cursor 最需要的协作和产品约束集中到一起。

## 一、项目来源和目录关系

这是一个重新开发的新系统，不是在旧系统上打补丁。

- 旧系统只作为参考，借鉴一致性处理、参数传递、失败样本和字段经验。
- 不迁移旧系统的 n8n 编排、旧数据库、故事专属硬编码或旧系统边界。
- 新项目目录是：`/Users/czy/AI长文系统/新系统开发`。
- 新项目使用 GitHub 仓库：`https://github.com/solve-context/ai-novel-production-system`。
- 仓库：`https://github.com/solve-context/ai-novel-production-system`。`v0.1.0` 指向基线提交 `7ac9fbe`，不要改写。
- `docs/` 保存方案和交接资料；`backend/` 保存统一后端和测试；`contracts/` 保存业务交接规范；`db/` 保存迁移；`integration/` 保存真实测试和恢复脚本；`frontend/` 保存两个前端区域原型。
- `data/` 下的运行数据库、真实模型数据库、备份和恢复副本不能提交 Git。

## 二、多个窗口如何协作

多个窗口共享同一项目文件夹，但不会自动共享各自的对话上下文。文件能同步，聊天记忆不能同步。

固定分工如下：

### 1. 方案研讨 / 总协调窗口

- 负责产品目标、系统边界、字段职责、流程规则、异常规则和取舍决策。
- 负责从第三视角检查是否有冗余、缺漏、冲突和过度设计。
- 负责决定每一项是否确认进入方案。
- 只在明确要求时改代码；通常输出决策和交接资料。

### 2. Cursor / 开发窗口

- 负责阅读交接文档、检查现有代码、实现已确认方案、补测试和报告结果。
- 每次只做一个明确开发步骤，不擅自扩展产品范围。
- 代码完成后必须说明修改文件、测试结果、数据库是否修改、是否调用真实 API、是否提交 Git。
- 规模测试开始前先阅读当前冻结代码，不要重置到 `v0.1.0`。

### 3. 用户终端窗口

- 由用户在本机终端运行真实模型测试、设置 API Key 和查看输出。
- 每次真实测试优先使用新开的终端窗口，避免旧窗口残留环境变量、错误数据库路径或旧状态。
- 所有终端都进入同一个项目目录，但每次真实测试使用新的数据库文件。
- API Key 只放在当前终端环境变量中，不能复制到聊天、代码、文档或 Git。

### 4. Git 协作

- 开发窗口和方案窗口共享本地工作区，不能同时对同一文件做互相覆盖的编辑。
- 先查看 `git status` 和 `git diff`，保留其他窗口已经完成的改动。
- 不要使用 force push，不要改写 `v0.1.0`。

## 三、产品目标和非目标

目标是为公司内部团队提供一套稳定、自动化、可追溯、可恢复、可规模化生产长篇小说的系统。

生产单位固定为“场”：

- 每场目标约 1250 字；第一版允许 1000～1500 个去空白字符。
- 每章两场。
- 目标作品约 80 章、20 万字，约 160 场。
- 第一版先跑通 5 场，再跑 20～40 场，最后才验收 160 场。

第一版不做：n8n 编排、面向大众的复杂产品、多组织权限、实时多机容灾、自动学习模型路由、Agent 自主无限检索、图数据库推理和复杂数据大屏。

## 四、最终产品架构

产品上是一个完整系统，前端分为两个区域，后端只有一个统一流程控制中心：

```text
创作工作台 / 管理后台
          ↓
统一后端（唯一流程控制中心）
  ├─ 规划 Agent
  ├─ 生文 Agent
  ├─ 审查 Agent
  │    ├─ 世界规则和前后设定审查员
  │    ├─ 人物行为和剧情结构审查员
  │    └─ 语言表达和阅读体验审查员
  ├─ 按需裁决 Agent
  ├─ 记忆 Agent
  ├─ Harness（模型调用、重试、预算、隔离和记录）
  ├─ 模型接口适配器（供应商格式转换）
  └─ 上下文与数据管理
       ├─ 资料库
       ├─ 检索
       ├─ ContextPack 组装
       ├─ 版本管理
       └─ 写入权限控制
```

必须遵守的总原则：

> Harness 负责模型调用管理，模型接口适配器负责供应商差异转换；Agent 只提出任务请求，统一后端控制流程，上下文与数据管理控制资料和写入权限。

边界如下：

- Agent 不直接调用其他 Agent。
- Agent 不直接调用具体模型 API。
- Agent 不直接访问数据库。
- Agent 不直接修改 TaskState。
- Agent 不直接修改正式世界规则。
- 前端不直接访问 Agent、Harness 或数据库。
- 所有状态流转、版本创建、记忆写入和异常处理由统一后端控制。

## 五、五类 Agent 的职责

规划 Agent 根据 CreativeBrief、正式资料和当前 ContextPack 生成 ScenePlan，说明本场要写什么。

生文 Agent 只读取当前场已固定的 ContextPack 和 ScenePlan，生成一版 ProseDraft。它不能自行改变规划或资料。

审查 Agent 由三位隔离的审查员组成：

- 世界规则和前后设定：查设定、时间、地点、知识边界和前后矛盾。
- 人物行为和剧情结构：查人物是否按已知信息行动、剧情是否合理、场次是否推进。
- 语言表达和阅读体验：查表达、节奏、可读性和明显重复。

三位审查员先分别返回 ReviewerResult，统一后端再汇总 QualityReport。审查员不直接决定任务状态。

裁决 Agent 只按需调用：

- 严重问题；
- 普通问题超过 10 个；
- 问题影响其他场或章节；
- 三位审查员对同一事实或行动给出相反结论。

记忆 Agent 只在正文通过审查和质量关卡后运行，从合格正文中提取一条或多条候选变化。它只提出 MemoryProposal，不能直接写正式资料。

## 六、上下文与记忆的关系

上下文与数据管理是资料的保存、检索、版本、权限和快照系统；记忆 Agent 是一个提出记忆变化的工作角色。两者不是两个互相竞争的记忆库。

正确关系是：

```text
记忆 Agent 从合格正文提取 MemoryProposal
→ 上下文与数据管理检查证据、冲突和权限
→ 场景事实自动保存，作品级内容等待人工确认
→ 形成下一场可读取的正式资料
→ 组装新的 ContextPack
```

RAG、关键词检索、结构化筛选、版本管理和 ContextPack 组装都属于上下文与数据管理，不新增一个“记忆 Agent”来代替检索系统。

待定提案绝不能进入生文 ContextPack；只有确认或自动保存成功的内容才能进入作品专属资料。

## 七、七类固定 Contract

### CreativeBrief

作品级、版本化、确认后只读。第一版必须填写：作品名称、作品类型、故事主题、目标篇幅、主要人物、人物关系、世界背景、核心规则、主要冲突、风格要求、结局方向、用户特别要求。

确认后不能原地修改；任何变化都产生新的 `brief_version`，暂停受影响任务，Agent 无权修改。

### ScenePlan

场次规划卡，必须包含：场景目标、进入状态、退出状态、人物、地点、时间、冲突、行动节拍、必须发生、禁止发生、知识边界、目标字数、验收标准、验证结果、是否可进入生文，以及第三项质量关卡要求的 `progression_requirements`。

第二场及后续场 Planning 输入带 `progression_baseline`（上一场确认状态的 characters、events、relationship_changes、unresolved_threads、location、time_context）。`before_state` 必须直接复制该基线中的现有状态，不得总结或改写；新增线索或悬念可用“未知”。该检查在 Planning 完成后立即执行，失败原因是 `plan_before_state_conflicts_previous_scene`，返回 Planning，不进入 Writing。

规划返工必须产生新的 `plan_version`，旧版本不可覆盖。

### ContextPack

按 Agent 和流程节点组装的只读资料快照。必须记录 `book_id`、`scene_id`、`fixture_id`、资料版本、`story_state_version`、`canon_version`、目标 Agent、目标节点、来源、排除资料、缺失资料、冲突和快照 hash。

上一场状态只能使用上一场 QualityReport 的 `accepted_scene_state`，不能从正文或待定提案自行推断。

### ProseDraft

每次生成产生新 `draft_version`，绑定准确的 `plan_version`、`context_pack_version`、正文 hash 和尝试次数。模型上报的字数只做审计，正式字数由后端重新计算。

### QualityReport

绑定准确的 `draft_id` 和 `draft_hash`，记录三位审查员结果、去重问题数、普通问题数、严重问题数、影响范围、冲突、路由建议和最终 `accepted_scene_state`。

### MemoryProposal

一条提案只描述一个变化，必须写清类型、范围、对象、修改前后内容、证据、证据位置、变化原因、冲突状态、写入策略和状态。

第一版合法映射固定为：

```text
scene_fact       + scene_memory      → auto_save
narrative_event  + book_memory       → human_confirmation
world_rule       + book_memory       → human_confirmation
character_detail + character_memory  → human_confirmation
```

正式世界规则和作品级资料不允许 Agent 自动写入。错误的类型、范围、action 或 write_policy 必须拒绝，不能自动猜测或转换。

### TaskState

严格分开 `current_node`、`status` 和 `next_action`：

- `current_node`：当前或最近完成的业务节点；完成后保留最后节点，不代表仍在处理。
- `status`：queued、running、reworking_writing、reworking_planning、waiting_confirmation、paused、blocked、exception_pending、completed 等生命周期状态。
- `next_action`：统一后端下一步要执行的动作。

`plan_version` 与 `plan_attempt` 不是同一个数字：

- `plan_version`：计划版本号。每生成一份新计划就递增，包括规划自身修错，只用于版本历史。
- `plan_attempt`：正文内容规划周期。初始为 1；只有正文累计三次剧情内容失败、正式返回 Planning 时才变成 2。字数失败和规划质量返工都不增加 `plan_attempt`。

每次状态变化都保存版本、触发人、原因、时间和历史事件。所有状态只能由统一后端写入。

## 八、正式主链路和返工规则

```text
确认 CreativeBrief
→ 组装 Planning ContextPack
→ Planning / ScenePlan
→ ScenePlan质量门槛
→ 组装 Writing ContextPack
→ Writing / ProseDraft
→ 真实字数校验
→ 实质重复检测
→ 三位审查员
→ 剧情推进核验
→ QualityReport
→ 记忆提取
→ 记忆权限与冲突检查
→ 自动保存或人工确认
→ 当前场完成
→ 下一场读取已确认状态
```

两类失败必须分开计数、分开路由。字数失败（`empty_text` / `under_length` / `over_length`）只回 Writing，不增加 `content_attempt_*` 或 `plan_attempt`；同一 `plan_version` 最多 4 份长度 Draft，第 4 份仍失败则 `length_attempts_exhausted` 阻塞。剧情内容失败（实质重复、世界观/人物剧情/明显语言硬问题、剧情推进失败）仍按原规则：第 1、2 次回 Writing，第 3 次回 Planning 并增加 `plan_attempt`，新内容规划周期再失败则 `content_attempts_exhausted` 阻塞。完全相同正文仍立即 `duplicate_draft_content` 阻塞。`suggestions` 不计失败。新 Plan 重新获得 4 次长度机会。规划质量返工只增加 `plan_version`。技术故障不占用任一类次数。

记忆等待人工确认时，任务是 `waiting_confirmation`，不能提前标记 `completed`；前置场未完成时，后续场保持 `queued`。

用户允许跳过时，必须记录跳过原因、确认人、被跳过场次原本承担的剧情功能和连续性缺口，缺口进入下一场 ContextPack。

## 九、三项质量关卡

### 1. 真实字数

后端去除空白字符后计算 `actual_character_count`，范围 1000～1500。少于1000、超过1500或正文为空，都在审查前拦截；不调用审查员、QualityReport 或记忆 Agent。这是格式质量问题：只回 Writing，由 `apply_length_failure` 单独计数，不与剧情内容失败共用路由。

### 2. 实质重复

只比较同书最近3个已确认场次。完全相同正文立即阻塞；正文实质重复返工；规划目标和行动节拍实质重复重新规划。人物、地点、时间相同不能单独构成重复。开头句式相似目前只记录，不作为硬阻断。

### 3. 剧情推进

每场至少有一项可验证推进：新线索、人物状态变化、关系变化、冲突变化、决定或后果、悬念新增/推进/关闭或目标里程碑。必须有当前正文中的证据，且证据对应前后状态并进入 `accepted_scene_state`。只有模型声称推进、但正文找不到依据时，判定失败。

## 十、数据库、接口和备份

第一版采用一个 SQLite 业务库，不拆多个数据库。核心表包括作品、章节、场次、七类 Contract、任务状态、任务事件、异常队列、Harness 调用、记忆记录和三项质量关卡审计表。

所有业务记录采用追加式和版本化写入。同编号同内容可以复用，同编号不同内容必须拒绝；禁止 `INSERT OR REPLACE` 覆盖历史正文、计划、报告、提案或记忆。

前端通过 `/api/v1` 访问统一后端。创建任务使用幂等键；状态变更必须带 `expected_state_version`，版本不一致返回 `VERSION_CONFLICT`。创建生成任务后返回 `task_id`，前端每2～5秒查询状态，显示“生成中、审查中、等待确认、已完成、已阻塞”等简化状态。

管理后台负责用户角色、作品访问、模型路由、Harness调用、异常队列、任务强制控制和备份状态；管理员没有正文和正式世界规则的直接编辑入口。

备份必须包含业务库、Harness调用、Contract、枚举、迁移和模型配置引用，不包含API Key。支持整库、单场和单条历史记录恢复；恢复目标使用新路径；同编号不同内容拒绝恢复。生产环境还要配置每日备份、保留策略、失败告警和定期隔离恢复演练。

## 十一、13个开发阶段的定位

1. 固定 Contract 和状态枚举。
2. 创建数据库表和迁移。
3. 统一后端任务状态控制。
4. REST 接口和统一错误格式。
5. Harness 和模型接口适配器。
6. 接入硅基流动 DeepSeek。
7. 资料筛选、混合检索和 ContextPack。
8. 实现规划、生文、审查、记忆等 Agent 薄适配。
9. 创作工作台。
10. 管理后台。
11. 固定 Mock 响应和12个验收样例。
12. 真实模型3～5场测试、人工确认、断点恢复和跨作品隔离。
13. 备份、恢复、历史不可覆盖和恢复后续跑。

阶段1～13的基础代码级闭环已经完成并冻结为 `v0.1.0`。现在是在冻结基线上补充三项质量关卡，属于下一轮质量增强，不要把它们误写成已经完成的20万字生产验收。

## 十二、Cursor工作方式

每次开发必须遵循：先读文档和现有代码 → 明确本次只解决一个问题 → 先补或更新固定测试 → 实现代码 → 运行相关测试和全量回归 → 只读检查历史数据库 → 输出结果并停止。

禁止：

- 为了让测试通过而放宽 Contract 校验；
- 凭空补造模型缺失的字段；
- 把内容问题当技术异常；
- 把待定提案写进生文资料；
- 覆盖历史数据库或历史版本；
- 在没有真实证据时声称质量或一致性通过；
- 未经方案窗口确认就增加 Agent、数据库、外部编排或新的自动写入权限。

每轮交付报告必须回答：改了什么、为什么改、如何验证、是否调用真实 API、是否修改历史库、是否改变状态语义、是否提交 Git、下一步是什么。

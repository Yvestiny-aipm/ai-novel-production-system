# AI Novel Production System

面向内部团队的长篇小说生产系统。第一版按“场”生产：规划、正文、确定性关卡、三审、记忆、人工确认、断点恢复和版本历史都可追溯、可校验、可恢复。不接入 n8n。

仓库：<https://github.com/solve-context/ai-novel-production-system>

## 当前状态

`v0.1.0` 是第一版本地验收基线（五场真实模型链路 + 隔离备份恢复）。在此之上已经完成连续四十场规模测试；160 场全书生产和生产环境的每日备份、保留策略、告警尚未开始。密钥和真实测试库不入库。

生产单位是场，不是章。单场目标约 1250 字（去空白），硬关卡 800～2300 字；每章两场；全书目标约 80 章 / 160 场 / 20 万字。当前没有独立的全书大纲层，规划是当场、逐场生成的。

模型路由（2026-09-23 暂定）：生文和记忆走 Azure Foundry Claude Opus 5.5；规划、三审、裁决走 GPT-6 Sol。空环境仍默认硅基流动。

## 整场工作流

每场走同一条主链路：只读 `CreativeBrief` 注入作品规则，组装当场 `ContextPack`，规划出 `ScenePlan`，写出 `ProseDraft`，先过确定性关卡，再由互相隔离的三位审查员出 `QualityReport`，记忆 Agent 提出 `MemoryProposal`，正式设定必须人审，本场 `completed` 后下场再读账本和此刻状态。

关卡或审查失败回返工（字数失败只回 Writing；内容失败计数，第三次回 Planning）。次数用尽或技术异常阻断，不自动救内容。

![长篇生产主链路](docs/archify/scene-production-workflow.png)

可交互图：[长篇生产主链路](docs/archify/scene-production-workflow.html)（源文件 `docs/archify/scene-production.workflow.json`）。

Agent 只能读取当前任务的 ContextPack，并通过 Harness 发出独立模型请求；Agent 不直接访问模型、数据库或其他 Agent。Harness 负责模型路由、调用隔离、重试、Contract 校验与 `harness_calls` 审计。三位审查员互相隔离，后端才会汇总 QualityReport。场景事实可自动写入；叙事事件、世界规则和人物细节必须按权限进入人工确认。裁决只在严重、跨场或真实冲突时调用。

## 项目结构

- `backend/`：Harness、Agent 适配、ContextPack、关卡、任务状态、记忆确认、备份恢复和测试。
- `contracts/`：七类业务 Contract Schema 与枚举。
- `db/migrations/`：SQLite 结构迁移。
- `integration/`：真实测试、夹具、恢复和备份命令。
- `acceptance/`：固定 Mock 验收分支。
- `frontend/`：创作工作台和管理页面原型。
- `docs/`：方案、交接说明、验收报告、架构说明和工作流成图。

## 安装与本地运行

需要 Python 3.11+。不要把密钥写入代码、文档或 Git。一键启动会创建 `.venv`、安装依赖、初始化本地库，并在同一端口提供前端和 API：

```sh
cp -n .env.example .env
./scripts/dev_up.sh
```

浏览器打开 `http://127.0.0.1:8124/`（工作台）或 `http://127.0.0.1:8124/admin.html`（管理后台）。健康检查：`http://127.0.0.1:8124/healthz`。

```sh
./scripts/dev_check.sh
./scripts/dev_down.sh
```

密钥和公司 Foundry 地址只放在本机 `.env` 或当前终端环境变量中；`.env` 已被 Git 忽略。手动安装仍然可用：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
./db/init.sh ./data/novel.db
python -m py_compile backend/*.py integration/*.py
PYTHONPATH=. python acceptance/run_cases.py
```

`data/` 下的运行数据库、真实模型样本、备份和恢复副本均被 Git 忽略。

## 环境变量与真实模型测试

密钥只从环境变量读取。未设置 `WRITING_PROVIDER` 时默认仍走硅基流动。规模测试用新库，不要改已经跑完的库。以下值是占位符：

```sh
export RUN_REAL_MODEL=1
export EXECUTION_MODE=sequential
export REAL_TEST_DB="$PWD/data/real_test.db"
export WRITING_PROVIDER=azure_foundry
export MEMORY_PROVIDER=azure_foundry
export PLANNING_PROVIDER=openai
export REVIEW_PROVIDER=openai
export ARBITER_PROVIDER=openai
export AZURE_FOUNDRY_CLAUDE_ENDPOINT="https://<your-foundry-resource>.services.ai.azure.com/anthropic"
export AZURE_FOUNDRY_CLAUDE_DEPLOYMENT="<your-foundry-deployment>"
export AZURE_FOUNDRY_CLAUDE_API_KEY="<your-foundry-api-key>"
export OPENAI_API_KEY="<your-openai-api-key>"
export OPENAI_DEFAULT_MODEL=gpt-6-sol
python3 integration/run_real_test.py
```

`REAL_TEST_AUTO_CONFIRM=1` 只表示测试操作员代为确认记忆提案，不是 Agent 自行写入正式设定。未设置 `RUN_REAL_MODEL=1` 或当前路由所需密钥时，runner 只返回 `not_run`。

## Mock 与回归测试

```sh
PYTHONPATH=. python3 acceptance/run_cases.py
PYTHONPATH=. python3 backend/test_recovery_preserves_history.py
PYTHONPATH=. python3 backend/test_immutable_business_records.py
PYTHONPATH=. python3 backend/test_backup_restore.py
PYTHONPATH=. python3 backend/test_azure_foundry.py
PYTHONPATH=. python3 backend/test_foundry_routing.py
```

## 备份与恢复

备份不保存 API Key；清单会记录数据库、Contract、枚举、模型配置引用和迁移文件的 SHA-256。

```sh
PYTHONPATH=. python3 integration/manage_backup.py create \
  --source-db data/real_test_resume_33_prepared.db \
  --backup-root data/backups \
  --backup-id local-backup-001

PYTHONPATH=. python3 integration/manage_backup.py verify \
  --backup data/backups/local-backup-001

PYTHONPATH=. python3 integration/manage_backup.py restore \
  --backup data/backups/local-backup-001 \
  --target-db data/restores/local-backup-001.db
```

恢复拒绝覆盖已有目标；单条历史记录或单场恢复时，同编号不同内容会失败，不会替换既有数据。

## 当前限制与下一阶段

- 四十场连续规模测试已跑通；尚未完成 160 场全书生产，不能声称已稳定产出 20 万字。
- 没有独立的全书大纲 / 部卷规划层，当场规划容易在同一处反复微调。
- 每日备份调度、保留清理、失败告警和生产管理后台仍需在部署环境配置。

## 方案文档

- [系统架构 README（本项目）](docs/系统架构README-本项目.md)
- [系统架构 README（竞品对照）](docs/系统架构README-竞品.md)
- [第一版本地验收发布说明](docs/第一版本地验收发布说明-v0.1.0.md)
- [方案基线 V1](docs/方案基线-v1.md)
- [Contract 说明](contracts/README.md)

旧系统只迁移通用规则、字段经验、测试案例和失败样本；不迁移 n8n 编排、旧数据库、故事专属硬编码或旧系统边界。

# AI Novel Production System

面向内部团队的长篇小说生产系统。第一版按“场”生产，目标是让规划、正文、审查、记忆、人工确认、断点恢复和版本历史均可追溯、可校验、可恢复；不接入 n8n。

## v0.1.0 定位

`v0.1.0` 是第一版本地验收基线：阶段 1～13 的开发和本地验收已经完成，包含五场真实模型链路和隔离备份恢复验证。它不是生产稳定性声明；尚未完成 20～40 场规模测试、160 场完整小说生产，以及生产环境的每日备份、保留策略与告警部署。

详见：[第一版本地验收发布说明](docs/第一版本地验收发布说明-v0.1.0.md)、[阶段 12 真实模型验收](docs/阶段12真实模型验收报告-v1.md)、[阶段 13 备份恢复验收](docs/阶段13备份恢复最终验收报告-v1.md)。

## 当前冻结（质量关卡 + 公司 API）

在 `v0.1.0` 之上已接入真实字数、实质重复、剧情推进三项关卡，以及 Azure Foundry Claude Opus 5 结构化任务适配。写作默认仍走硅基流动 DeepSeek。五场公司 API 验证已通过；20～40 场和 160 场尚未开始。密钥和真实测试库不入库。

## 架构与主链路

```text
前端 → 统一后端 → ContextPack
                   ├─ planning → ScenePlan
                   ├─ writing → ProseDraft
                   ├─ review_world / review_plot / review_style → ReviewerResult
                   ├─ 汇总 → QualityReport
                   ├─ 按需 arbiter
                   └─ memory_extraction → MemoryProposal → memory_records / 人工确认
```

Agent 只能读取当前任务的 ContextPack，并通过 Harness 发出独立模型请求；Agent 不直接访问模型、数据库或其他 Agent。Harness 负责模型路由、调用隔离、重试、Contract 校验与 `harness_calls` 审计；供应商适配器只负责将统一请求转换为具体 API 格式。

三位审查员互相隔离，后端才会汇总 QualityReport。审查通过后，场景事实可自动写入；叙事事件、世界规则和人物细节必须按权限进入人工确认。裁决只在严重、跨场或真实冲突条件满足时调用。

## 项目结构

- `backend/`：Harness、Agent 适配、ContextPack、任务状态、记忆确认、备份恢复和测试。
- `contracts/`：七类业务 Contract Schema 与枚举。
- `db/migrations/`：SQLite 结构迁移。
- `integration/`：真实测试、夹具、恢复和备份命令。
- `acceptance/`：固定 Mock 验收分支。
- `frontend/`：创作工作台和管理页面原型。
- `docs/`：方案、交接说明、验收报告和发布说明。

## 安装与本地运行

需要 Python 3.11+ 和 SQLite。无需把密钥写入代码、文档或 Git。

```sh
cd "/Users/czy/AI长文系统/新系统开发"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m py_compile backend/*.py integration/*.py
PYTHONPATH=. python acceptance/run_cases.py
```

数据库初始化示例：

```sh
./db/init.sh ./data/novel.db
```

`data/` 下的运行数据库、真实模型样本、备份和恢复副本均被 Git 忽略。

## 环境变量与真实模型测试

密钥只从环境变量读取。默认仍走硅基流动；要把规划/审查切到 Azure Foundry 的 Opus 5 时，再加上 Foundry 变量。以下值是占位符：

```sh
export RUN_REAL_MODEL=1
export SILICONFLOW_API_KEY="<your-siliconflow-api-key>"
export EXECUTION_MODE=sequential
export REAL_TEST_DB="$PWD/data/real_test.db"
# 可选：结构化任务改走 Claude Opus 5，写作仍走 DeepSeek
export STRUCTURED_PROVIDER=azure_foundry
export AZURE_FOUNDRY_CLAUDE_ENDPOINT="https://ayw-cuizhiyuan-7093-resource.services.ai.azure.com/anthropic"
export AZURE_FOUNDRY_CLAUDE_DEPLOYMENT="claude-opus-5-ay-cuizhiyuan"
export AZURE_FOUNDRY_CLAUDE_API_KEY="<your-foundry-api-key>"
# 若用 Entra 而不用 Key：export AZURE_FOUNDRY_AUTH=entra
python3 integration/run_real_test.py
```

真实运行会保留调用记录和失败现场；不要将 `data/` 中的数据库、备份或 API Key 提交到 Git。未设置 `RUN_REAL_MODEL=1` 或当前路由所需密钥时，runner 只返回 `not_run`。

## Mock 与回归测试

```sh
PYTHONPATH=. python3 acceptance/run_cases.py
PYTHONPATH=. python3 backend/test_recovery_preserves_history.py
PYTHONPATH=. python3 backend/test_immutable_business_records.py
PYTHONPATH=. python3 backend/test_rerun31_memory_target_key_regression.py
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

- 尚未完成 20～40 场连续规模测试。
- 尚未完成 160 场完整小说生产与质量验收，不能声称已稳定产出 20 万字。
- 每日备份调度、保留清理、失败告警和生产管理后台仍需在部署环境配置。
- 下一阶段是 20～40 场规模测试，随后开展 160 场完整作品验证与生产环境运维配置。

## 方案文档

- [方案基线 V1](docs/方案基线-v1.md)
- [开发交接说明 V1](docs/开发交接说明-v1.md)
- [Contract 说明](contracts/README.md)

旧系统只迁移通用规则、字段经验、测试案例和失败样本；不迁移 n8n 编排、旧数据库、故事专属硬编码或旧系统边界。

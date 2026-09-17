# Database

阶段 2 使用 SQLite 初始化业务数据库。初始化命令：

```sh
./db/init.sh ./data/novel.db
```

`migrations/001_initial.sql` 建立业务核心表、七类 Contract 表和运行支撑表。Contract 的完整业务字段保存在 `payload_json`，关系型字段负责索引、外键、版本和状态约束。

约束包括：同一作品同一场仅允许一个运行中任务、同一业务对象版本唯一、生成幂等键唯一、ContextPack 版本唯一、TaskEvent 只增不改（应用层约束），以及正式记忆必须带审批状态。

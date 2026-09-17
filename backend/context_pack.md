# ContextPack（阶段 7）

`ContextPackService.assemble` 按范围和权限筛选来源，排除 `pending` 提案，按资料层级和关键词排序，保留冲突来源并写入冲突标记，最后将固定快照和哈希插入 `context_packs`。同一 `scene_id`、版本、Agent 和节点不可重复插入；服务不提供更新方法，因此生成后不可变。

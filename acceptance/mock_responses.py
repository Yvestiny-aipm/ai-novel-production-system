"""固定模拟响应；供验收测试使用，不进入生产路由。"""
RESPONSES = {
    "planning": {"contract_type":"ScenePlan","contract_version":"v1","payload":{"ready_for_writing":True}},
    "writing": {"contract_type":"ProseDraft","contract_version":"v1","payload":{"complete":True,"word_count":1250}},
    "review_pass": {"contract_type":"QualityReport","contract_version":"v1","payload":{"status":"passed","needs_arbiter":False}},
    "review_fail": {"contract_type":"QualityReport","contract_version":"v1","payload":{"status":"failed","needs_arbiter":False}},
    "memory": {"contract_type":"MemoryProposal","contract_version":"v1","payload":{"status":"pending"}}
}

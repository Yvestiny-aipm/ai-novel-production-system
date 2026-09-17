"""业务 Agent 薄适配层：不访问数据库、不调用供应商，只通过 Harness。"""
try:
    from .harness import required_fields_validator
except ImportError:
    from harness import required_fields_validator

class Agent:
    def __init__(self, harness, task_type, contract_type): self.harness=harness; self.task_type=task_type; self.contract_type=contract_type
    def run(self, task_id, context_pack):
        return self.harness.run(task_id=task_id, agent_task_type=self.task_type, input_payload={"context_pack":context_pack}, contract_type=self.contract_type, contract_validator=required_fields_validator)

def build_agents(harness):
    return {k: Agent(harness,k,v) for k,v in {"planning":"ScenePlan","writing":"ProseDraft","review_world":"QualityReport","review_plot":"QualityReport","review_style":"QualityReport","memory_extraction":"MemoryProposal","arbiter":"QualityReport"}.items()}

from siliconflow import parse_contract_content
from harness import required_fields_validator, ContractFormatError
raw='说明：提案如下\n```json\n{"contract_type":"MemoryProposal","contract_version":"v1","payload":{"memory_type":"fact","target_scope":"story","target_key":"x","action":"create","before_value":null,"after_value":"x","evidence":"e","evidence_location":"s","change_reason":"r","conflict_status":"none","write_policy":"human_confirmation","status":"pending"}}\n```'
parsed=parse_contract_content(raw); assert parsed['payload']['memory_type']=='fact'
try: required_fields_validator(parsed,'MemoryProposal')
except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
else: raise AssertionError('legacy memory type accepted')
print('memory response parsing ok')

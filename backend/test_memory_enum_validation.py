from harness import required_fields_validator, ContractFormatError
payload={'memory_type':'scene_fact','target_scope':'scene_memory','target_key':'x','action':'create','before_value':None,'after_value':{'x':1},'evidence':'e','evidence_location':'s','change_reason':'r','conflict_status':'invalid','write_policy':'auto_save','status':'pending'}
try: required_fields_validator({'contract_type':'MemoryProposal','contract_version':'v1','payload':payload},'MemoryProposal')
except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
else: raise AssertionError('invalid memory enum accepted')
print('memory enum validation ok')
bad={'contract_type':'MemoryProposal','contract_version':'v1','payload':{'memory_type':'narrative_event','target_scope':'story','target_key':'x','action':'create','before_value':None,'after_value':'x','evidence':'e','evidence_location':'s','change_reason':'r','conflict_status':'none','write_policy':'never_auto_write','status':'pending'}}
try: required_fields_validator(bad,'MemoryProposal')
except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
else: raise AssertionError('invalid permission mapping accepted')

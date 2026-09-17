from harness import required_fields_validator, ContractFormatError

base = {'memory_type':'scene_fact','target_scope':'scene_memory','target_key':'k','action':'create','before_value':None,'after_value':'v','evidence':'e','evidence_location':'draft.payload.text','change_reason':'r','conflict_status':'none','write_policy':'auto_save','status':'approved'}
for action in ('create','update','delete'):
    p=dict(base); p['action']=action
    required_fields_validator({'contract_type':'MemoryProposal','contract_version':'v1','payload':p}, 'MemoryProposal')
for action in ('add','modify','remove','append'):
    p=dict(base); p['action']=action
    try:
        required_fields_validator({'contract_type':'MemoryProposal','contract_version':'v1','payload':p}, 'MemoryProposal')
    except ContractFormatError as exc:
        assert exc.code == 'CONTRACT_PAYLOAD_INVALID'
    else:
        raise AssertionError(action)
print('memory action validation ok')

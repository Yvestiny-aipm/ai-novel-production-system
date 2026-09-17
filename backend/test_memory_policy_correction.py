from integration.run_real_test import policy_correction_needed, validate_policy_correction

base = {'memory_type':'narrative_event','target_scope':'book_memory','target_key':'event-1','action':'create','before_value':None,'after_value':'事实','evidence':'事实','evidence_location':'draft.payload.text','change_reason':'提取','conflict_status':'none','write_policy':'never_auto_write','status':'pending'}
original={'contract_type':'MemoryProposal','contract_version':'v1','payload':base}
assert policy_correction_needed(original)
fixed=dict(base); fixed['write_policy']='human_confirmation'
validate_policy_correction(original, {'contract_type':'MemoryProposal','contract_version':'v1','payload':fixed})
bad=dict(fixed); bad['evidence']='被篡改'
try:
    validate_policy_correction(original, {'contract_type':'MemoryProposal','contract_version':'v1','payload':bad})
except ValueError as exc:
    assert str(exc)=='POLICY_CORRECTION_CHANGED_CONTENT'
else:
    raise AssertionError('correction must not change evidence')
print('memory policy correction ok')

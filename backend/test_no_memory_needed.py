from harness import required_fields_validator, ContractFormatError


def envelope(payload):
    return {'contract_type': 'MemoryProposal', 'contract_version': 'v1', 'payload': payload}


required_fields_validator(envelope({'status': 'skipped', 'reason': '本场只有过渡描写，没有新的可长期保存事实。'}), 'MemoryProposal')

try:
    required_fields_validator(envelope({'status': 'skipped', 'reason': ''}), 'MemoryProposal')
except ContractFormatError as exc:
    assert exc.code == 'CONTRACT_PAYLOAD_INVALID'
else:
    raise AssertionError('empty no-memory reason must be rejected')

try:
    # A model claiming a proposal but omitting proposal fields remains invalid;
    # it must not be silently converted to no_memory_needed.
    required_fields_validator(envelope({'status': 'pending', 'reason': '有记忆变化'}), 'MemoryProposal')
except ContractFormatError as exc:
    assert exc.code == 'CONTRACT_PAYLOAD_INVALID'
else:
    raise AssertionError('incomplete proposal must be rejected')

print('no_memory_needed validation ok')

from harness import required_fields_validator, ContractFormatError
base={'contract_type':'ProseDraft','contract_version':'v1','payload':{'text':'','word_count':0,'target_word_count':1250,'complete':False,'writer_self_check':{}}}
try: required_fields_validator(base,'ProseDraft')
except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
else: raise AssertionError('empty draft accepted')
valid={'contract_type':'ProseDraft','contract_version':'v1','payload':{'text':'潮声' * 10,'word_count':10,'target_word_count':1250,'complete':True,'writer_self_check':{}}}; required_fields_validator(valid,'ProseDraft'); print('draft validation ok')

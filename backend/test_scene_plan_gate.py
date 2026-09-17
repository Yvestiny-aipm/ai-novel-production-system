from harness import required_fields_validator, ContractFormatError

base={'scene_goal':'goal','entrance_state':{'x':1},'exit_state':{'x':2},'characters':['林照'],'location':'灯塔','time_context':'夜晚','conflict':'调查','action_beats':['进入'],'must_happen':['发现'],'must_not_happen':['解决'],'knowledge_boundary':'已知','target_word_count':1250,'acceptance_criteria':['有效'],'validation_result':{'ok':True},'ready_for_writing':True}
required_fields_validator({'contract_type':'ScenePlan','contract_version':'v1','payload':base},'ScenePlan')
for update in ({'target_word_count':0},{'ready_for_writing':False},{'scene_goal':''}):
    bad=dict(base); bad.update(update)
    try: required_fields_validator({'contract_type':'ScenePlan','contract_version':'v1','payload':bad},'ScenePlan')
    except ContractFormatError as exc: assert exc.code=='CONTRACT_PAYLOAD_INVALID'
    else: raise AssertionError(update)
print('scene plan gate ok')

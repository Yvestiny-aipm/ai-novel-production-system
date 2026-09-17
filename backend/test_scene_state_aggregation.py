from integration.run_real_test import aggregate_quality
from harness import required_fields_validator, ContractFormatError

state={'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚','events':['发现灯塔只能保存和展示记忆'],'relationship_changes':['林照更坚定调查'],'unresolved_threads':['林澜失踪']}
review={'contract_type':'ReviewerResult','contract_version':'v1','payload':{'reviewer_role':'world_consistency','result':'passed','findings':'ok','issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}}
report=aggregate_quality([review,review,review]); required_fields_validator(report,'QualityReport'); assert report['payload']['accepted_scene_state']==state
bad=dict(review); bad['payload']=dict(review['payload']); bad['payload'].pop('scene_state');
try: required_fields_validator(aggregate_quality([bad,bad,bad]),'QualityReport')
except ContractFormatError as exc: assert exc.code=='CONTRACT_PAYLOAD_INVALID'
else: raise AssertionError('missing scene state must fail')
print('scene state aggregation ok')

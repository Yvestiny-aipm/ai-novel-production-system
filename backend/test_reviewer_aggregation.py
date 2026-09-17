from integration.run_real_test import aggregate_quality
from harness import required_fields_validator
state={'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚','events':['发现线索'],'relationship_changes':[],'unresolved_threads':['林澜失踪']}
reviews=[
 {'payload':{'reviewer_role':'world_consistency','result':'passed','findings':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}},
 {'payload':{'reviewer_role':'character_plot','result':'passed','findings':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}},
 {'payload':{'reviewer_role':'language_experience','result':'passed','findings':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}}
]
q=aggregate_quality(reviews)
required_fields_validator(q,'QualityReport')
assert q['payload']['status']=='passed' and q['payload']['needs_arbiter'] is False
print('reviewer aggregation ok')

from integration.run_real_test import aggregate_quality
from harness import required_fields_validator
from backend.siliconflow import reviewer_plot_instruction, writing_quality_edit_instruction
from backend.progression import quality_revision_feedback
state={'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚','events':['发现线索'],'relationship_changes':[],'unresolved_threads':['林澜失踪']}
reviews=[
 {'payload':{'reviewer_role':'world_consistency','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}},
 {'payload':{'reviewer_role':'character_plot','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}},
 {'payload':{'reviewer_role':'language_experience','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':state}}
]
q=aggregate_quality(reviews)
required_fields_validator(q,'QualityReport')
assert q['payload']['status']=='passed' and q['payload']['needs_arbiter'] is False
world={'characters':['管理员'],'location':'灯塔外','time_context':'清晨','events':['世界审查事件'],'relationship_changes':[],'unresolved_threads':['无关']}
plot={'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚','events':['潮痕编号A-17'],'relationship_changes':['管理员开始协助'],'unresolved_threads':['林澜失踪']}
split=[
 {'payload':{'reviewer_role':'world_consistency','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':world}},
 {'payload':{'reviewer_role':'character_plot','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':plot}},
 {'payload':{'reviewer_role':'language_experience','result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary','impact_scope':'local','true_conflict_candidate':False,'scene_state':world}}
]
assert aggregate_quality(split)['payload']['accepted_scene_state']==plot
conflict=[{**item} for item in reviews]
conflict[0]={'payload':{**reviews[0]['payload'],'true_conflict_candidate':True,'severity':'serious'}}
assert aggregate_quality(conflict)['payload']['needs_arbiter'] is True
assert aggregate_quality(conflict)['payload']['serious_issue_count'] == 0
assert aggregate_quality(conflict)['payload']['ordinary_issue_count'] == 0
suggest=[{**item} for item in reviews]
suggest[2]={'payload':{**reviews[2]['payload'],'suggestions':['记忆只能保存和展示出现多次，可酌情精简一处分句'],'impact_scope':'cross_scene','severity':'serious'}}
soft=aggregate_quality(suggest)
assert soft['payload']['status']=='passed'
assert soft['payload']['ordinary_issue_count']==0
assert soft['payload']['serious_issue_count']==0
assert soft['payload']['needs_arbiter'] is False
assert soft['payload']['routing_recommendation']=='complete'
assert soft['payload']['reviewer_results'][2]['suggestions']==['记忆只能保存和展示出现多次，可酌情精简一处分句']
hard=[{**item} for item in reviews]
hard[0]={'payload':{**reviews[0]['payload'],'result':'failed','findings':['世界规则冲突'],'issue_count':1}}
hard_q=aggregate_quality(hard)
assert hard_q['payload']['status']=='failed'
assert hard_q['payload']['ordinary_issue_count']==1
assert hard_q['payload']['routing_recommendation']=='rewrite'
cross=[{**item} for item in reviews]
cross[0]={'payload':{**reviews[0]['payload'],'result':'failed','findings':['跨场事实矛盾'],'issue_count':1,'impact_scope':'cross_scene'}}
assert aggregate_quality(cross)['payload']['needs_arbiter'] is True
plot_instruction = reviewer_plot_instruction()
assert "after_state 必须同步进入 scene_state" in plot_instruction
assert "new_clue → events 或 unresolved_threads" in plot_instruction
assert "不能只在 progression_assessment 中写 after_state" in plot_instruction
assert "evidence_text in draft.payload.text" in plot_instruction
assert "不得跨段拼接" in plot_instruction
assert "partially_achieved" in plot_instruction
assert "expected_after_state" in plot_instruction
assert "不得为了显得认真而强行制造 findings" in plot_instruction
assert "suggestions 必须是数组" in plot_instruction
passed_feedback = quality_revision_feedback(
    previous_draft_id="d1", previous_text="上一稿", plan_id="p1", plan_version=1,
    progression_status="passed", reviewer_findings=[
        {"reviewer_role": "world_consistency", "result": "failed", "issue_count": 1,
         "severity": "ordinary", "impact_scope": "local", "findings": "世界规则冲突"},
    ], routing_recommendation="rewrite")
assert passed_feedback["failure_type"] == "quality_report"
assert passed_feedback["progression_failure_reason"] is None
assert "推进目标未完成" not in writing_quality_edit_instruction(passed_feedback)
assert "世界规则冲突" in writing_quality_edit_instruction(passed_feedback)
print('reviewer aggregation ok')

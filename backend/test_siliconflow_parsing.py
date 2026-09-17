from siliconflow import parse_contract_content
valid='{"contract_type":"ScenePlan","contract_version":"v1","payload":{"scene_goal":"x"}}'
assert parse_contract_content('说明文字\n```json\n'+valid+'\n```\n结束')['contract_type']=='ScenePlan'
assert parse_contract_content(valid)['payload']['scene_goal']=='x'
print('siliconflow response parsing ok')

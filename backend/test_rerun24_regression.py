import json
from pathlib import Path
from integration.run_real_test import aggregate_quality
from harness import required_fields_validator

sample=json.loads((Path(__file__).parent/'fixtures/rerun24_reviewer_responses.json').read_text())
for item in sample: required_fields_validator(item,'ReviewerResult')
report=aggregate_quality(sample)
required_fields_validator(report,'QualityReport')
state=report['payload']['accepted_scene_state']
assert state['characters'] and state['location'] and state['time_context'] and state['events']
assert state['relationship_changes']==[]
print('rerun24 real response regression ok')

import json
from pathlib import Path

def load_cases(): return json.loads((Path(__file__).parent/'cases.json').read_text())['cases']
def validate_cases():
    cases=load_cases(); assert len(cases)==12
    ids=[c['id'] for c in cases]; assert len(set(ids))==12
    assert all(c.get('expected') for c in cases)
    return len(cases)
if __name__=='__main__': print(f'{validate_cases()} acceptance cases loaded')

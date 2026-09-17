"""Regression path for the sanitized real rerun_31 MemoryProposal response."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path

from backend.harness import ContractFormatError, required_fields_validator
from backend.siliconflow import parse_contract_content
from integration.run_real_test import save_proposal


raw=(Path(__file__).parent/'fixtures/rerun31_scene2_memory_response.json').read_text()
response=parse_contract_content('模型原始输出如下：\n```json\n'+raw+'\n```')
assert response['payload']['status']=='pending'
assert 'target_key' not in response['payload']
try:
    required_fields_validator(response,'MemoryProposal')
except ContractFormatError as exc:
    assert exc.code=='CONTRACT_PAYLOAD_INVALID'
    assert str(exc)=='missing payload fields: target_key'
else:
    raise AssertionError('real response without target_key must fail')

# The no-memory branch bypasses proposal-only fields and remains a normal result.
required_fields_validator({'contract_type':'MemoryProposal','contract_version':'v1','payload':{'status':'skipped','reason':'本场没有长期记忆变化'}},'MemoryProposal')

generic=copy.deepcopy(response); generic['payload']['target_key']='context_pack_v1'
try:
    required_fields_validator(generic,'MemoryProposal')
except ContractFormatError as exc:
    assert exc.code=='CONTRACT_PAYLOAD_INVALID'
else:
    raise AssertionError('ContextPack filename cannot be a target_key')

corrected=copy.deepcopy(response); corrected['payload']['target_key']='character:linlan:archive_discovery'
required_fields_validator(corrected,'MemoryProposal')
with tempfile.TemporaryDirectory() as directory:
    db=sqlite3.connect(Path(directory)/'check.db')
    db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.execute("insert into prose_drafts values ('d','b','c','s',1,1,1,1,'正文',2,1250,1,'{}','passed','hash','hc',1,1,'2026')")
    db.execute("insert into quality_reports values ('r','b','c','s','d','hash',1,'completed','[]',0,0,0,0,0,'complete','{}','passed','2026')")
    db.commit()
    proposal_id,written=save_proposal(db,'b','c','s','d','r',corrected)
    assert proposal_id=='s_proposal_v1' and not written
    assert db.execute('select target_key,status from memory_proposals').fetchone()==('character:linlan:archive_discovery','pending')
    assert db.execute('select count(*) from memory_records').fetchone()[0]==0

print('rerun31 memory target_key regression ok')

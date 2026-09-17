import json
import sqlite3
import tempfile
from pathlib import Path

from backend.immutable_store import HistoricalRecordConflict
from integration.run_real_test import save_plan, save_draft, save_report, save_proposal


def expect_conflict(callback):
    try:
        callback()
    except HistoricalRecordConflict:
        return
    raise AssertionError('expected HistoricalRecordConflict')


plan = {'contract_type':'ScenePlan','contract_version':'v1','payload':{
    'scene_goal':'调查','entrance_state':{'a':1},'exit_state':{'b':1},'characters':['林照'],
    'location':'灯塔','time_context':'夜晚','conflict':'失踪','action_beats':['调查'],
    'must_happen':['发现'],'must_not_happen':['结案'],'knowledge_boundary':'有限记忆',
    'target_word_count':1250,'acceptance_criteria':['推进'],'validation_result':{'ok':True},'ready_for_writing':True}}
draft = {'contract_type':'ProseDraft','contract_version':'v1','payload':{
    'text':'林照调查灯塔。','word_count':6,'target_word_count':1250,'complete':True,'writer_self_check':{}}}
quality = {'contract_type':'QualityReport','contract_version':'v1','payload':{
    'review_completion_status':'completed','reviewer_results':[],'deduped_issue_count':0,'ordinary_issue_count':0,
    'serious_issue_count':0,'has_true_conflict':False,'needs_arbiter':False,'routing_recommendation':'complete',
    'accepted_scene_state':{'characters':['林照'],'location':'灯塔','time_context':'夜晚','events':['调查'],
                            'relationship_changes':[],'unresolved_threads':['林澜失踪']},'status':'passed'}}
proposal = {'contract_type':'MemoryProposal','contract_version':'v1','payload':{
    'memory_type':'scene_fact','target_scope':'scene_memory','target_key':'灯塔功能','action':'create',
    'before_value':None,'after_value':'灯塔保存记忆','evidence':'正文','evidence_location':'draft','change_reason':'事实',
    'conflict_status':'none','write_policy':'auto_save','status':'pending'}}

with tempfile.TemporaryDirectory() as folder:
    db=sqlite3.connect(Path(folder)/'records.db')
    db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')")
    db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.commit()
    pid=save_plan(db,'b','c','s',plan,'hc-plan')
    assert save_plan(db,'b','c','s',plan,'hc-plan') == pid
    changed={**plan,'payload':{**plan['payload'],'scene_goal':'其他调查'}}
    expect_conflict(lambda: save_plan(db,'b','c','s',changed,'hc-plan'))
    did,dh=save_draft(db,'b','c','s',draft,'hc-draft')
    assert save_draft(db,'b','c','s',draft,'hc-draft') == (did,dh)
    changed={**draft,'payload':{**draft['payload'],'text':'不同正文'}}
    expect_conflict(lambda: save_draft(db,'b','c','s',changed,'hc-draft'))
    rid,_,_=save_report(db,'b','c','s',did,dh,[quality])
    assert save_report(db,'b','c','s',did,dh,[quality])[0] == rid
    changed={**quality,'payload':{**quality['payload'],'routing_recommendation':'rewrite'}}
    expect_conflict(lambda: save_report(db,'b','c','s',did,dh,[changed]))
    mpid,written=save_proposal(db,'b','c','s',did,rid,proposal)
    assert written and save_proposal(db,'b','c','s',did,rid,proposal) == (mpid,True)
    assert db.execute('select count(*) from memory_records').fetchone()[0] == 1
    changed={**proposal,'payload':{**proposal['payload'],'after_value':'不同记忆'}}
    expect_conflict(lambda: save_proposal(db,'b','c','s',did,rid,changed))
    assert json.loads(db.execute('select after_value_json from memory_proposals where proposal_id=?',(mpid,)).fetchone()[0]) == '灯塔保存记忆'
    assert json.loads(db.execute('select value_json from memory_records where source_proposal_id=?',(mpid,)).fetchone()[0]) == '灯塔保存记忆'

print('immutable business records ok')

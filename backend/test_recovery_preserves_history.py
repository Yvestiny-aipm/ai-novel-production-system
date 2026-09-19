"""Mock end-to-end checks for checkpoint recovery against the prepared baseline."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from integration.recovery import request_rework
from integration.run_real_test import run, save_plan


ROOT = Path(__file__).parents[1]
PREPARED = ROOT / 'data/real_test_resume_28_prepared.db'
BASELINE = json.loads((ROOT / 'data/real_test_resume_28_prepared.baseline.json').read_text())


def scene_plan(number):
    return {'contract_type':'ScenePlan','contract_version':'v1','payload':{
        'scene_goal':f'场次{number}推进调查','entrance_state':{'scene':number},'exit_state':{'clue':number},
        'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚','conflict':'寻找林澜',
        'action_beats':['调查档案'],'must_happen':['发现线索'],'must_not_happen':['解决谜团'],
        'knowledge_boundary':'灯塔只能保存记忆','target_word_count':1250,
        'acceptance_criteria':['推进调查'],'validation_result':{'complete':True},'ready_for_writing':True,
        'progression_requirements':[{'progress_type':'new_clue','target_key':'灯塔线索','before_state':'未知','expected_after_state':'发现线索','acceptance_criterion':'正文发现线索'}]}}


def draft(number):
    return {'contract_type':'ProseDraft','contract_version':'v1','payload':{
        'text':(f'第{number}场正文：林照在灯塔档案室继续调查林澜失踪。' * 50), 'word_count':1250,
        'target_word_count':1250,'complete':True,'writer_self_check':{'complete':True}}}


def reviewer(role, number):
    return {'contract_type':'ReviewerResult','contract_version':'v1','payload':{
        'reviewer_role':role,'result':'passed','findings':[],'suggestions':[],'issue_count':0,'severity':'ordinary',
        'impact_scope':'local','true_conflict_candidate':False,'scene_state':{
            'characters':['林照'],'location':'灯塔档案室','time_context':'夜晚',
            'events':['发现线索'], 'relationship_changes':[], 'unresolved_threads':['林澜失踪']},
        'progression_assessment':{'status':'achieved','achieved_items':[{'progress_type':'new_clue','target_key':'灯塔线索','before_state':'未知','after_state':'发现线索','evidence_text':'林照','evidence_location':'draft.text'}],'missing_items':[],'evidence':'林照'}}}


def proposal(number):
    return {'contract_type':'MemoryProposal','contract_version':'v1','payload':{
        'memory_type':'narrative_event','target_scope':'book_memory','target_key':f'event-{number}',
        'action':'create','before_value':None,'after_value':f'第{number}场调查推进',
        'evidence':f'第{number}场正文','evidence_location':'draft.payload.text','change_reason':'审查通过的事件',
        'conflict_status':'none','write_policy':'human_confirmation','status':'pending'}}


class Adapter:
    def __init__(self): self.calls=[]
    def complete(self, request, timeout_seconds):
        self.calls.append(request)
        number=request['input']['checkpoint']['scene_id'].rsplit('_',1)[-1]
        role=request['task_type']
        if role=='planning': return scene_plan(number)
        if role=='writing': return draft(number)
        if role=='memory_extraction': return proposal(number)
        return reviewer({'review_world':'world_consistency','review_plot':'character_plot','review_style':'language_experience'}[role], number)


def snapshot(db):
    tables=('scene_plans','prose_drafts','quality_reports','memory_proposals','memory_records','harness_calls','context_packs')
    # The new length-audit migration may append columns to a legacy prepared
    # fixture.  Compare the frozen v0.1 business columns, not SQLite's shape.
    prose_columns=('draft_id','book_id','chapter_id','scene_id','draft_version','attempt','plan_version','context_pack_version','text','word_count','target_word_count','complete','writer_self_check_json','status','draft_hash','harness_call_id','content_attempt_in_plan','content_attempt_total','created_at')
    return {table:[tuple(row) for row in db.execute(
        f"SELECT {','.join(prose_columns) if table == 'prose_drafts' else '*'} FROM {table} ORDER BY 1")]
            for table in tables}


def copy_prepared(path):
    shutil.copy2(PREPARED, path)
    return sqlite3.connect(path)


with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'resume.db'; db=copy_prepared(path); before=snapshot(db); db.close()
    adapter=Adapter(); result=run(db_path=path,adapter=adapter,execution_mode='sequential')
    db=sqlite3.connect(path)
    first={table:before[table] for table in ('scene_plans','prose_drafts','quality_reports','memory_proposals','memory_records','context_packs')}
    after=snapshot(db)
    # The completed scene is untouched: zero calls and all durable rows exactly equal.
    assert result['scenes'][0]['skipped_existing'] and not result['scenes'][0]['calls']
    scene_index={'scene_plans':3,'prose_drafts':3,'quality_reports':3,'memory_proposals':3,'memory_records':2,'context_packs':3}
    for table, rows in first.items():
        index=scene_index[table]
        assert [r for r in after[table] if r[index].endswith('scene_1')] == [r for r in rows if r[index].endswith('scene_1')]
    scene1=BASELINE['scenes'][0]
    row=db.execute("select draft_hash from prose_drafts where draft_id=?",(scene1['drafts'][0]['draft_id'],)).fetchone()
    assert row[0]==scene1['drafts'][0]['draft_hash']
    assert db.execute("select status from memory_proposals where scene_id like '%scene_1'").fetchone()[0]=='approved'
    assert db.execute("select approval_status from memory_records where scene_id like '%scene_1'").fetchone()[0]=='approved'
    # Scene 2 starts, then intentionally waits for confirmation; 3-5 remain queued.
    assert any(c['input']['checkpoint']['scene_id'].endswith('scene_2') for c in adapter.calls)
    assert db.execute("select status from task_states where scene_id like '%scene_2'").fetchone()[0]=='waiting_confirmation'
    assert [r[0] for r in db.execute("select status from task_states where scene_id in (?,?,?) order by scene_id",('realtest_tide_archive_scene_3','realtest_tide_archive_scene_4','realtest_tide_archive_scene_5'))]==['queued','queued','queued']
    db.close()

with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'mid-node.db'; db=copy_prepared(path); db.row_factory=sqlite3.Row
    # Simulate a technical interruption after the durable plan checkpoint of scene 2.
    plan=scene_plan(2); save_plan(db,'realtest_tide_archive','realtest_tide_archive_chapter_1','realtest_tide_archive_scene_2',plan,'preexisting_call',2,1)
    before_plan=dict(db.execute("select * from scene_plans where scene_id like '%scene_2'").fetchone())
    db.execute("update task_states set status='exception_pending',current_node='writing' where scene_id like '%scene_2'"); db.commit(); db.close()
    adapter=Adapter(); result=run(db_path=path,adapter=adapter,execution_mode='sequential')
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row
    after_plan=dict(db.execute("select * from scene_plans where scene_id like '%scene_2'").fetchone())
    assert before_plan==after_plan
    assert not any(c['task_type']=='planning' and c['input']['checkpoint']['scene_id'].endswith('scene_2') for c in adapter.calls)
    assert any(c['task_type']=='writing' and c['input']['checkpoint']['scene_id'].endswith('scene_2') for c in adapter.calls)
    assert db.execute("select count(*) from scene_plans where scene_id like '%scene_2'").fetchone()[0]==1
    # Explicit rework is the only route that advances revision numbers.
    directive=request_rework(db,'realtest_tide_archive_scene_2_task','writing','verified revision request')
    assert directive['draft_version']==2 and directive['plan_version']==1
    db.close()

print('recovery preserves history ok')

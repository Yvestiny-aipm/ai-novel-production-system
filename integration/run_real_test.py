"""阶段 12：五场真实模型串行执行器。"""
import hashlib, json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
if str(Path(__file__).parent) not in sys.path: sys.path.insert(0,str(Path(__file__).parent))
from seed_real_test import seed
from backend.harness import Harness, ModelProfile, required_fields_validator, ContractFormatError
from backend.siliconflow import SiliconFlowAdapter
from backend.context_pack import ContextPackService
from backend.immutable_store import insert_snapshot

TYPES=['planning','writing','review_world','review_plot','review_style','memory_extraction','arbiter']
def h(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def put(db,table,columns,values): return insert_snapshot(db,table,columns,values)
def save_plan(db,book,ch,scene,resp,call,story_state_version=1,version=1):
    p=resp['payload']; pid=f'{scene}_plan_v{version}'; put(db,'scene_plans',['plan_id','book_id','chapter_id','scene_id','plan_version','brief_version','story_state_version','status','payload_json','content_hash','created_at'],[pid,book,ch,scene,version,1,story_state_version,'ready',json.dumps(p,ensure_ascii=False),h(p),str(time.time())]); return pid
def save_draft(db,book,ch,scene,resp,call,version=1,plan_version=1,context_pack_version=1):
    p=resp['payload']; did=f'{scene}_draft_v{version}'; text=p.get('text',''); put(db,'prose_drafts',['draft_id','book_id','chapter_id','scene_id','draft_version','attempt','plan_version','context_pack_version','text','word_count','target_word_count','complete','writer_self_check_json','status','draft_hash','harness_call_id','content_attempt_in_plan','content_attempt_total','created_at'],[did,book,ch,scene,version,version,plan_version,context_pack_version,text,p.get('word_count',0),1250,int(bool(p.get('complete',True))),json.dumps(p.get('writer_self_check',{})), 'in_review',h(p),call,version,version,str(time.time())]); return did,h(p)
def save_report(db,book,ch,scene,draft_id,draft_hash,results,arbiter=None):
    merged=arbiter or results; counts=[x.get('payload',{}).get('ordinary_issue_count',0) for x in merged]; serious=sum(x.get('payload',{}).get('serious_issue_count',0) for x in merged); conflict=any(x.get('payload',{}).get('has_true_conflict',False) for x in merged); passed=all(x.get('payload',{}).get('status')=='passed' for x in merged); rid=f'{scene}_report_v{draft_id.rsplit("_v",1)[-1]}'; state=merged[0].get('payload',{}).get('accepted_scene_state',{}) if merged else {}; put(db,'quality_reports',['report_id','book_id','chapter_id','scene_id','draft_id','draft_hash','review_attempt','review_completion_status','reviewer_results_json','deduped_issue_count','ordinary_issue_count','serious_issue_count','has_true_conflict','needs_arbiter','routing_recommendation','accepted_scene_state_json','status','created_at'],[rid,book,ch,scene,draft_id,draft_hash,1,'completed',json.dumps(merged,ensure_ascii=False),sum(counts),sum(counts),serious,int(conflict),int(bool(arbiter)), 'complete' if passed else 'rewrite',json.dumps(state,ensure_ascii=False),'passed' if passed else 'failed',str(time.time())]); return rid,passed,state
def aggregate_quality(reviews):
    payloads=[x['payload'] for x in reviews]; ordinary=sum(int(p.get('issue_count',0)) for p in payloads); serious=sum(1 for p in payloads if p.get('severity')=='serious'); conflict=any(bool(p.get('true_conflict_candidate')) for p in payloads); impact=any(p.get('impact_scope') in ('cross_scene','cross_chapter','book') for p in payloads); failed=any(p.get('result') in ('failed','fail') or int(p.get('issue_count',0))>0 for p in payloads); states=[p.get('scene_state') for p in payloads if isinstance(p.get('scene_state'),dict)]; state=states[0] if states else {}; return {'contract_type':'QualityReport','contract_version':'v1','payload':{'review_completion_status':'completed','reviewer_results':payloads,'deduped_issue_count':ordinary,'ordinary_issue_count':ordinary,'serious_issue_count':serious,'has_true_conflict':conflict,'needs_arbiter':serious>0 or impact or conflict,'routing_recommendation':'arbiter' if (serious>0 or impact or conflict) else ('rewrite' if failed else 'complete'),'accepted_scene_state':state,'status':'failed' if failed else 'passed'}}
def save_proposal(db,book,ch,scene,draft,report,resp,version=1):
    required_fields_validator(resp,'MemoryProposal')
    p=resp['payload']; pid=f'{scene}_proposal_v{version}'
    columns=['proposal_id','book_id','chapter_id','scene_id','source_draft_id','source_report_id','proposal_version','memory_type','target_scope','target_key','action','before_value_json','after_value_json','evidence','evidence_location','change_reason','conflict_status','write_policy','status','created_at']
    auto=p['memory_type']=='scene_fact' and p['target_scope']=='scene_memory' and p['write_policy']=='auto_save'
    values=[pid,book,ch,scene,draft,report,version,p['memory_type'],p['target_scope'],p['target_key'],p['action'],json.dumps(p['before_value']),json.dumps(p['after_value']),p['evidence'],p['evidence_location'],p['change_reason'],p['conflict_status'],p['write_policy'],'written' if auto else p['status'],str(time.time())]
    # Proposal and record commit together; any failure leaves neither half-written.
    with db:
        insert_snapshot(db,'memory_proposals',columns,values,commit=False)
        if auto:
            existing=db.execute('select version from memory_records where memory_record_id=?',(f'mem_{pid}',)).fetchone()
            memory_version=existing[0] if existing else db.execute('select coalesce(max(version),0)+1 from memory_records where book_id=? and scene_id=? and target_scope=? and target_key=?',(book,scene,p['target_scope'],p['target_key'])).fetchone()[0]
            insert_snapshot(db,'memory_records',['memory_record_id','book_id','scene_id','target_scope','memory_type','target_key','value_json','source_proposal_id','approval_status','version','created_at'],[f'mem_{pid}',book,scene,p['target_scope'],p['memory_type'],p['target_key'],json.dumps(p['after_value']),pid,'approved',memory_version,str(time.time())],commit=False)
    return pid,auto

def expected_memory_policy(payload):
    return {'scene_fact':('scene_memory','auto_save'),'narrative_event':('book_memory','human_confirmation'),'world_rule':('book_memory','human_confirmation'),'character_detail':('character_memory','human_confirmation')}.get(payload.get('memory_type'))

def policy_correction_needed(response):
    p=response.get('payload',{}) if isinstance(response,dict) else {}
    expected=expected_memory_policy(p)
    return bool(expected and p.get('target_scope')==expected[0] and p.get('write_policy')=='never_auto_write')

def validate_policy_correction(original, corrected):
    old, new = original['payload'], corrected['payload']
    if not policy_correction_needed(original): raise ValueError('POLICY_CORRECTION_NOT_APPLICABLE')
    if new.get('write_policy') != expected_memory_policy(old)[1]: raise ValueError('POLICY_CORRECTION_INVALID')
    for key in old:
        if key != 'write_policy' and new.get(key) != old.get(key): raise ValueError('POLICY_CORRECTION_CHANGED_CONTENT')
def save_task_result(db, task, final_status, node, reason='real test runner', block_reason=None, execution_mode='sequential'):
    row=db.execute('SELECT state_version,status,current_node FROM task_states WHERE task_id=?',(task,)).fetchone(); version=(row[0] if row else 0)+1
    next_action={'completed':'none','waiting_confirmation':'await_human_confirmation','blocked':'none','paused':'resume','exception_pending':'handle_exception'}.get(final_status,'rewrite')
    db.execute('UPDATE task_states SET current_node=?,status=?,next_action=?,block_reason=?,execution_mode=?,state_version=?,updated_at=? WHERE task_id=?',(node,final_status,next_action,block_reason,execution_mode,version,str(time.time()),task))
    db.execute('INSERT INTO task_events(event_id,task_id,event_type,from_node,from_status,to_node,to_status,payload_json,actor_id,reason,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(f'evt_{task}_{version}',task,'real_test_transition',row[2] if row else None,row[1] if row else None,node,final_status,'{}','real_test',reason,str(time.time()))); db.commit()
def prior_scenes_completed(db, book, scene_number):
    rows=db.execute("select t.status from task_states t join scenes s on s.scene_id=t.scene_id where s.book_id=? and s.scene_number<?",(book,scene_number)).fetchall()
    return all(row[0]=='completed' for row in rows) and len(rows)==scene_number-1
def run(*, db_path=None, adapter=None, execution_mode=None):
    # Explicit adapter injection is for local Mock tests; the CLI still requires opt-in.
    if adapter is None:
        if os.getenv('RUN_REAL_MODEL')!='1': return {'status':'not_run','reason':'set RUN_REAL_MODEL=1'}
        if not os.getenv('SILICONFLOW_API_KEY'): return {'status':'not_run','reason':'SILICONFLOW_API_KEY is missing'}
    from integration.recovery import run_recovery
    return run_recovery(Path(db_path or os.getenv('REAL_TEST_DB',ROOT/'data/real_test.db')),
                        adapter or SiliconFlowAdapter(), execution_mode or os.getenv('EXECUTION_MODE','sequential'),
                        mock=adapter is not None)

if __name__=='__main__': print(json.dumps(run(),ensure_ascii=False,indent=2))

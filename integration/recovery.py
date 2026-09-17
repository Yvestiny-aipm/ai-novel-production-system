"""Resume durable checkpoints; only an explicit rework allocates a new revision."""
import json
import time
import uuid

from backend.context_pack import ContextPackService
from backend.harness import Harness, ModelProfile, required_fields_validator, ContractFormatError
from integration.seed_real_test import seed
from integration.run_real_test import (TYPES, aggregate_quality, save_plan, save_draft,
    save_report, save_proposal, save_task_result, prior_scenes_completed,
    policy_correction_needed, validate_policy_correction)


def one(db, sql, args=()):
    cur = db.execute(sql, args)
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row is not None else None


def envelope(kind, payload):
    result = {'contract_type': kind, 'contract_version': 'v1', 'payload': payload}
    required_fields_validator(result, kind)
    return result


def request_rework(db, task_id, node, reason):
    """Formal revision boundary: persist its IDs before making any new call."""
    if node not in ('planning', 'writing') or not reason.strip():
        raise ValueError('REWORK_REQUIRES_NODE_AND_REASON')
    task = one(db, 'select * from task_states where task_id=?', (task_id,))
    scene = task['scene_id']
    pv = db.execute('select coalesce(max(plan_version),0) from scene_plans where scene_id=?', (scene,)).fetchone()[0]
    dv = db.execute('select coalesce(max(draft_version),0)+1 from prose_drafts where scene_id=?', (scene,)).fetchone()[0]
    cpv = db.execute('select coalesce(max(context_pack_version),0)+1 from context_packs where scene_id=?', (scene,)).fetchone()[0]
    directive = {'plan_version': pv+1 if node == 'planning' else pv,
                 'draft_version': dv, 'context_pack_version': cpv, 'reason': reason}
    if directive['plan_version'] < 1:
        raise ValueError('REWORK_WRITING_REQUIRES_PLAN')
    with db:
        db.execute('insert into task_events(event_id,task_id,event_type,payload_json,reason,created_at) values (?,?,?,?,?,?)',
                   ('evt_'+uuid.uuid4().hex, task_id, 'rework_requested', json.dumps(directive), reason, str(time.time())))
        db.execute('update task_states set status=?,current_node=?,next_action=?,active_contract_refs_json=? where task_id=?',
                   ('reworking_'+node, node, 'replan' if node == 'planning' else 'rewrite', json.dumps([{'rework':directive}]), task_id))
    return directive


class SceneRecovery:
    def __init__(self, db, harness, book, number, out):
        self.db, self.harness, self.book, self.number, self.out = db, harness, book, number, out
        self.scene, self.task = out['scene_id'], out['task_id']
        self.chapter = book+'_chapter_1'
        self.node = 'planning'

    def call(self, role, kind, payload):
        # Exact request matching prevents reuse across scenes, drafts or rework versions.
        payload = {**payload, 'checkpoint': self.checkpoint}
        for row in self.db.execute('select harness_call_id,request_json,response_json from harness_calls where task_id=? and agent_type=? and status=? order by started_at desc', (self.task,role,'success')):
            request = json.loads(row[1])
            if request.get('input') == payload and request.get('contract_type') == kind:
                response = json.loads(row[2]); required_fields_validator(response, kind)
                self.out['reused_calls'].append(row[0])
                return {'harness_call_id':row[0], 'response':response}
        before = {r[0] for r in self.db.execute('select harness_call_id from harness_calls where task_id=?',(self.task,))}
        try:
            return self.harness.run(task_id=self.task,agent_task_type=role,input_payload=payload,contract_type=kind,contract_validator=required_fields_validator)
        finally:
            self.out['calls'].extend(r[0] for r in self.db.execute('select harness_call_id from harness_calls where task_id=? order by started_at',(self.task,)) if r[0] not in before)

    def execute(self):
        task = one(self.db,'select * from task_states where task_id=?',(self.task,))
        directives = [r['rework'] for r in json.loads(task['active_contract_refs_json']) if 'rework' in r]
        directive = directives[-1] if directives else {}
        plan = one(self.db,'select * from scene_plans where scene_id=? order by plan_version desc limit 1',(self.scene,))
        draft = one(self.db,'select * from prose_drafts where scene_id=? order by draft_version desc limit 1',(self.scene,))
        pv = directive.get('plan_version', plan['plan_version'] if plan else 1)
        dv = directive.get('draft_version', draft['draft_version'] if draft else 1)
        cv = directive.get('context_pack_version', draft['context_pack_version'] if draft else 1)
        if plan and plan['plan_version'] != pv: plan = None
        if draft and (draft['draft_version'] != dv or draft['plan_version'] != pv): draft = None
        self.checkpoint = {'scene_id':self.scene,'plan_version':pv,'draft_version':dv,'context_pack_version':cv}
        previous = {}
        if self.number > 1:
            prior = one(self.db,'select q.*,p.story_state_version from quality_reports q join prose_drafts d on d.draft_id=q.draft_id join scene_plans p on p.scene_id=d.scene_id and p.plan_version=d.plan_version where q.scene_id=? and q.status=? order by d.draft_version desc limit 1', (f'{self.book}_scene_{self.number-1}','passed'))
            if not prior: raise ValueError('PREVIOUS_CONFIRMED_STATE_MISSING')
            previous = json.loads(prior['accepted_scene_state_json'])
            story_version = prior['story_state_version']+1
        else: story_version = 1
        sources = [{'source_id':'brief_real_v1','source_type':'brief','book_id':self.book,'version':1,'content':'潮痕档案：林照调查林澜失踪与灯塔档案；灯塔只能保存和展示记忆。'}]
        if previous: sources.append({'source_id':f'accepted_scene_{self.number-1}','source_type':'scene_memory','book_id':self.book,'version':story_version-1,'content':previous})
        cp = ContextPackService(self.db).assemble(pack_id=f'{self.scene}_pack_v{cv}',book_id=self.book,chapter_id=self.chapter,scene_id=self.scene,version=cv,target_agent='planning',target_node='planning',brief_version=1,plan_version=pv,story_state_version=story_version,canon_version=1,sources=sources,previous_scene_state=previous)
        if plan:
            planning = envelope('ScenePlan',json.loads(plan['payload_json']))
            self.out['plan_id'] = plan['plan_id']
        else:
            result = self.call('planning','ScenePlan',{'scene_number':self.number,'context_pack':cp})
            planning = result['response']
            self.out['plan_id'] = save_plan(self.db,self.book,self.chapter,self.scene,planning,result['harness_call_id'],story_version,pv)
        self.node = 'writing'
        if draft:
            call = one(self.db,'select response_json from harness_calls where harness_call_id=? and status=?',(draft['harness_call_id'],'success'))
            if not call: raise ValueError('DRAFT_SOURCE_CALL_MISSING')
            writing = json.loads(call['response_json']); required_fields_validator(writing,'ProseDraft')
            if writing['payload']['text'] != draft['text']: raise ValueError('DRAFT_SOURCE_MISMATCH')
            self.out['draft_id'], dh = draft['draft_id'], draft['draft_hash']
        else:
            result = self.call('writing','ProseDraft',{'context_pack':cp,'scene_plan':planning})
            writing = result['response']
            self.out['draft_id'], dh = save_draft(self.db,self.book,self.chapter,self.scene,writing,result['harness_call_id'],dv,pv,cv)
            prev = one(self.db,'select text from prose_drafts where scene_id=? and draft_version<? order by draft_version desc limit 1',(self.scene,dv))
            if prev and prev['text'] == writing['payload']['text']:
                self.out['block_reason']='duplicate_draft_content'; return 'blocked'
        self.node = 'reviewing'
        report = one(self.db,'select * from quality_reports where draft_id=? order by review_attempt desc limit 1',(self.out['draft_id'],))
        if report:
            if report['draft_hash'] != dh: raise ValueError('REPORT_DRAFT_HASH_MISMATCH')
            report_payload = {k:report[k] for k in ('review_completion_status','deduped_issue_count','ordinary_issue_count','serious_issue_count','has_true_conflict','needs_arbiter','routing_recommendation','status')}
            report_payload.update(reviewer_results=json.loads(report['reviewer_results_json']),accepted_scene_state=json.loads(report['accepted_scene_state_json']))
            quality = envelope('QualityReport',report_payload)
            self.out['report_id'] = report['report_id']
        else:
            reviews = [self.call(role,'ReviewerResult',{'context_pack':cp,'draft':writing})['response'] for role in ('review_world','review_plot','review_style')]
            quality = aggregate_quality(reviews); required_fields_validator(quality,'QualityReport')
            arb = None
            if quality['payload']['needs_arbiter']:
                self.node = 'arbiter'
                quality = self.call('arbiter','QualityReport',{'context_pack':cp,'draft':writing,'reviewer_results':reviews})['response']
                arb = [quality]; self.out['arbiter_called'] = True
            self.out['report_id'], _, _ = save_report(self.db,self.book,self.chapter,self.scene,self.out['draft_id'],dh,[quality],arb)
        if quality['payload']['status'] != 'passed':
            self.out['passed_review'] = False
            count = self.db.execute('select count(*) from prose_drafts where scene_id=? and plan_version=?',(self.scene,pv)).fetchone()[0]
            if count >= 3: self.out['block_reason']='review_attempts_exhausted'; return 'blocked'
            self.out['rework'] = True
            request_rework(self.db,self.task,'writing','validated QualityReport failed: '+self.out['report_id'])
            return self.execute()
        self.out['passed_review'] = True
        self.node = 'memory_processing'
        proposal = one(self.db,'select * from memory_proposals where source_draft_id=? and source_report_id=? order by proposal_version desc limit 1',(self.out['draft_id'],self.out['report_id']))
        if proposal:
            self.out['proposal_id'] = proposal['proposal_id']
            record = one(self.db,'select * from memory_records where source_proposal_id=?',(proposal['proposal_id'],))
            if record:
                if proposal['status'] not in ('approved','written'): raise ValueError('MEMORY_STATUS_MISMATCH')
                if (record['book_id'],record['scene_id'],record['value_json']) != (proposal['book_id'],proposal['scene_id'],proposal['after_value_json']): raise ValueError('MEMORY_SOURCE_MISMATCH')
                self.out['formal_memory_written']=True; return 'completed'
            if proposal['write_policy'] != 'auto_save': self.node='human_confirmation'; return 'waiting_confirmation'
            raise ValueError('MEMORY_WRITE_INCOMPLETE_REQUIRES_REPAIR')
        proposal_version = self.db.execute('select coalesce(max(proposal_version),0)+1 from memory_proposals where scene_id=?',(self.scene,)).fetchone()[0]
        memory_input = {'context_pack':cp,'draft':writing,'quality_report':quality}
        try:
            result = self.call('memory_extraction','MemoryProposal',memory_input)
        except ContractFormatError as error:
            if not policy_correction_needed(error.response): raise
            original = error.response
            # Raw v1 stays in harness_calls; correction request references its ID and revision.
            corrected = self.call('memory_extraction','MemoryProposal',{**memory_input,'policy_correction':{'original':original,'source_call_id':error.call_id,'original_version':proposal_version,'corrected_version':proposal_version+1,'instruction':'Change only write_policy; all other fields must remain identical.'}})
            validate_policy_correction(original,corrected['response'])
            result=corrected; proposal_version+=1
        if result['response']['payload'].get('status') == 'skipped':
            self.out.update(memory_status='skipped',memory_skip_reason=result['response']['payload']['reason']); return 'completed'
        self.out['proposal_id'],self.out['formal_memory_written'] = save_proposal(self.db,self.book,self.chapter,self.scene,self.out['draft_id'],self.out['report_id'],result['response'],proposal_version)
        if self.out['formal_memory_written']: return 'completed'
        self.node = 'human_confirmation'; return 'waiting_confirmation'


def run_recovery(path, adapter, mode, *, mock=False):
    if mode not in ('sequential','independent_test'): raise ValueError('INVALID_EXECUTION_MODE')
    db, book = seed(path)
    provider = 'mock' if mock else 'siliconflow'
    harness = Harness(path,{role:ModelProfile(provider,'mock' if mock else 'deepseek-ai/DeepSeek-V3',technical_retries=0,max_output_tokens=5000) for role in TYPES},{provider:adapter})
    start = time.time(); results = []
    try:
        for number in range(1,6):
            scene = f'{book}_scene_{number}'; task_id = scene+'_task'
            task = one(db,'select * from task_states where task_id=?',(task_id,))
            out = {'scene_id':scene,'task_id':task_id,'execution_mode':mode,'calls':[],'reused_calls':[],'rework':False,'arbiter_called':False,'proposal_id':None,'formal_memory_written':False,'final_status':task['status'],'current_node':task['current_node']}
            results.append(out)
            if task['status']=='completed': out['skipped_existing']=True; continue
            if task['status'] in ('waiting_confirmation','blocked','paused','cancelled','skipped'):
                out['paused_existing']=True; continue
            if mode=='sequential' and not prior_scenes_completed(db,book,number):
                out['skipped_due_to_dependency']=True; continue
            recovery = SceneRecovery(db,harness,book,number,out)
            try:
                out['final_status'] = recovery.execute()
                out['current_node'] = recovery.node
            except Exception as exc:
                out.update(final_status='exception_pending',current_node='exception_handling',technical_error=str(exc),failed_node=recovery.node)
            save_task_result(db,task_id,out['final_status'],out['current_node'],reason=out.get('technical_error','checkpoint recovery'),block_reason=out.get('block_reason'),execution_mode=mode)
    finally:
        harness.close(); db.close()
    return {'status':'completed','execution_mode':mode,'book_id':book,'database':str(path),'scenes':results,'call_count':sum(len(x['calls']) for x in results),'total_seconds':round(time.time()-start,2)}

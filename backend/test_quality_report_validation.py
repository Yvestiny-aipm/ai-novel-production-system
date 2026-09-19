import sqlite3, tempfile
from pathlib import Path
from harness import (Harness, ModelProfile, MockAdapter, required_fields_validator, ContractFormatError,
    ARBITER_PROMPT_VERSION, validate_quality_report_for_task)
from backend.progression import apply_to_quality
from backend.siliconflow import arbiter_quality_instruction, build_chat_messages

FIELDS={'review_completion_status':'completed','reviewer_results':[],'deduped_issue_count':0,'ordinary_issue_count':0,'serious_issue_count':0,'has_true_conflict':False,'needs_arbiter':False,'routing_recommendation':'complete','accepted_scene_state':{'characters':['林照'],'location':'灯塔','time_context':'夜晚','events':['调查'],'relationship_changes':[],'unresolved_threads':['林澜失踪']},'status':'passed'}
with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; c=sqlite3.connect(db); c.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); c.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); c.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')"); c.commit(); c.close()
    h=Harness(db,{'review_world':ModelProfile('mock','m')},{'mock':MockAdapter({'contract_type':'QualityReport','contract_version':'v1','payload':FIELDS})}); assert h.run(task_id='t',agent_task_type='review_world',input_payload={},contract_type='QualityReport',contract_validator=required_fields_validator); h.close()
    try: required_fields_validator({'contract_type':'QualityReport','contract_version':'v1','payload':{}},'QualityReport')
    except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
    else: raise AssertionError('missing QualityReport fields accepted')


def quality(updates=None):
    payload=dict(FIELDS)
    if updates:
        payload.update(updates)
    return {'contract_type':'QualityReport','contract_version':'v1','payload':payload}


def expect_invalid(response, task_type='arbiter'):
    try:
        required_fields_validator(response,'QualityReport')
        validate_quality_report_for_task(response, task_type)
    except ContractFormatError as error:
        assert error.code=='CONTRACT_PAYLOAD_INVALID'
        return
    raise AssertionError('invalid Arbiter QualityReport accepted')


def open_db(directory):
    db=Path(directory)/'arbiter.db'
    con=sqlite3.connect(db)
    con.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text())
    con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')")
    con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','arbiter','queued','start_arbiter','[]','[]','k','2026','2026')")
    con.commit(); con.close()
    return db


# 1. A complete Arbiter QualityReport is accepted.
with tempfile.TemporaryDirectory() as directory:
    db=open_db(directory)
    harness=Harness(db,{'arbiter':ModelProfile('mock','m',prompt_version=ARBITER_PROMPT_VERSION)},{'mock':MockAdapter(quality())})
    result=harness.run(task_id='t',agent_task_type='arbiter',input_payload={},contract_type='QualityReport',contract_validator=required_fields_validator)
    assert result['response']['payload']['status']=='passed'
    assert sqlite3.connect(db).execute("select status from harness_calls").fetchone()[0]=='success'
    harness.close()


# 2 / 3 / 4 / 5. Illegal Arbiter enums and missing status fail before success.
expect_invalid(quality({'review_completion_status':'complete'}))
missing=quality(); missing['payload']=dict(missing['payload']); missing['payload'].pop('status')
expect_invalid(missing)
expect_invalid(quality({'status':'accepted_with_notes'}))
expect_invalid(quality({'routing_recommendation':'proceed_with_revisions'}))
required_fields_validator(quality(),'QualityReport')
validate_quality_report_for_task(quality(),'arbiter')
validate_quality_report_for_task(quality({'routing_recommendation':'arbiter'}),'review_world')


# Arbiter passed cannot keep a backend progression failure.
overridden=apply_to_quality(quality(),{
    'progression_status':'failed','planned_progression_count':1,'achieved_progression_count':0,
    'verified_progression_items':[],'missing_progression_items':[{'failure_reason':'after_state_missing_from_accepted_scene_state'}],
    'progression_failure_reason':'after_state_missing_from_accepted_scene_state',
})
assert overridden['payload']['status']=='failed'
assert overridden['payload']['routing_recommendation']=='rewrite'


# Last-message instruction names the formal enums.
messages=build_chat_messages({'contract_type':'QualityReport','task_type':'arbiter','input':{'scene_plan':{}}})
assert messages[2]['content']==arbiter_quality_instruction()
assert 'completed' in messages[2]['content']
assert 'proceed_with_revisions' in messages[2]['content']
assert ARBITER_PROMPT_VERSION=='arbiter_contract_v2'
print('quality report validation ok')

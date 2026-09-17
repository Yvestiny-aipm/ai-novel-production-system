import sqlite3, tempfile
from pathlib import Path
from harness import Harness, ModelProfile, MockAdapter, required_fields_validator, ContractFormatError
FIELDS={'review_completion_status':'completed','reviewer_results':[],'deduped_issue_count':0,'ordinary_issue_count':0,'serious_issue_count':0,'has_true_conflict':False,'needs_arbiter':False,'routing_recommendation':'complete','accepted_scene_state':{'characters':['林照'],'location':'灯塔','time_context':'夜晚','events':['调查'],'relationship_changes':[],'unresolved_threads':['林澜失踪']},'status':'passed'}
with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; c=sqlite3.connect(db); c.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); c.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); c.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')"); c.commit(); c.close()
    h=Harness(db,{'review_world':ModelProfile('mock','m')},{'mock':MockAdapter({'contract_type':'QualityReport','contract_version':'v1','payload':FIELDS})}); assert h.run(task_id='t',agent_task_type='review_world',input_payload={},contract_type='QualityReport',contract_validator=required_fields_validator); h.close()
    try: required_fields_validator({'contract_type':'QualityReport','contract_version':'v1','payload':{}},'QualityReport')
    except ContractFormatError as e: assert e.code=='CONTRACT_PAYLOAD_INVALID'
    else: raise AssertionError('missing QualityReport fields accepted')
print('quality report validation ok')

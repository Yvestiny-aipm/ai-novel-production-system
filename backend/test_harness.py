import json, sqlite3, tempfile
from pathlib import Path
from harness import Harness, ModelProfile, MockAdapter, required_fields_validator, ContractFormatError

with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; con=sqlite3.connect(db); con.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); con.execute("INSERT INTO task_states(task_id,task_scope,book_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) VALUES ('t','book','b','planning','queued','start_planning','[]','[]','k','2026','2026')"); con.commit(); con.close()
    h=Harness(db, {'planning':ModelProfile('mock','m',technical_retries=1)}, {'mock':MockAdapter({'contract_type':'ScenePlan','contract_version':'v1','payload':{'scene_goal':'推进调查','entrance_state':{'location':'灯塔'},'exit_state':{'clue':'异常记录'},'characters':['林照'],'location':'灯塔','time_context':'夜晚','conflict':'寻找线索','action_beats':['翻阅档案'],'must_happen':['发现线索'],'must_not_happen':['谜团解决'],'knowledge_boundary':'灯塔只能展示记忆','target_word_count':1250,'acceptance_criteria':['推进剧情'],'validation_result':{'complete':True},'ready_for_writing':True}})})
    result=h.run(task_id='t',agent_task_type='planning',input_payload={'x':1},contract_type='ScenePlan',contract_validator=required_fields_validator); assert result['harness_call_id'].startswith('hc_')
    try: Harness(db, {'planning':ModelProfile('mock','m')}, {'mock':MockAdapter({})}).run(task_id='t',agent_task_type='planning',input_payload={},contract_type='ScenePlan',contract_validator=required_fields_validator)
    except ContractFormatError: pass
    else: raise AssertionError('invalid contract accepted')
    h.close(); print('ok')

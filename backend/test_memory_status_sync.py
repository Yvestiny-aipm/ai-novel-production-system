import sqlite3, tempfile
from pathlib import Path
from integration.run_real_test import save_proposal
from backend.memory_confirmation import confirm_proposal

schema=(Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()
with tempfile.TemporaryDirectory() as d:
    db=sqlite3.connect(Path(d)/'x.db'); db.row_factory=sqlite3.Row; db.executescript(schema)
    db.execute("insert into books values ('b','B',null,1,'2026','2026')"); db.execute("insert into chapters values ('c','b',1,null,'2026','2026')"); db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')")
    db.execute("insert into prose_drafts values ('d','b','c','s',1,1,1,1,'text',1,1250,1,'{}','passed','h','hc',1,1,'2026')"); db.execute("insert into quality_reports values ('r','b','c','s','d','h',1,'completed','[]',0,0,0,0,0,'complete','{}','passed','2026')"); db.commit()
    scene={'contract_type':'MemoryProposal','contract_version':'v1','payload':{'memory_type':'scene_fact','target_scope':'scene_memory','target_key':'k','action':'create','before_value':None,'after_value':'v','evidence':'e','evidence_location':'s','change_reason':'r','conflict_status':'none','write_policy':'auto_save','status':'pending'}}
    pid,written=save_proposal(db,'b','c','s','d','r',scene); assert written and db.execute("select status from memory_proposals where proposal_id=?",(pid,)).fetchone()[0]=='written'; assert db.execute("select approval_status from memory_records where source_proposal_id=?",(pid,)).fetchone()[0]=='approved'
    db.execute("insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) values ('t','scene','b','c','s','human_confirmation','waiting_confirmation','await_human_confirmation','[]','[]','k','2026','2026')")
    db.execute("insert into memory_proposals values ('p','b','c','s','d','r',2,'character_detail','character_memory','hero','create',null,'{\"name\":\"林照\"}','e','s','r','none','human_confirmation','pending','2026')"); db.commit(); confirm_proposal(db,'p','u'); assert db.execute("select status from memory_proposals where proposal_id='p'").fetchone()[0]=='approved'
print('memory status sync ok')

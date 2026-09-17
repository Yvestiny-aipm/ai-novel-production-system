import sqlite3, tempfile
from pathlib import Path
from integration.run_real_test import save_task_result
with tempfile.TemporaryDirectory() as d:
    db=sqlite3.connect(Path(d)/'x.db'); db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); db.execute("insert into books values ('b','B',null,1,'2026','2026')"); db.execute("insert into chapters values ('c','b',1,null,'2026','2026')"); db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')"); db.execute("insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) values ('t','scene','b','c','s','writing','running','rewrite','[]','[]','k','2026','2026')"); db.commit(); save_task_result(db,'t','blocked','writing','duplicate_draft_content','duplicate_draft_content','sequential'); row=db.execute("select current_node,status,block_reason,execution_mode from task_states where task_id='t'").fetchone(); assert tuple(row)==('writing','blocked','duplicate_draft_content','sequential')
print('execution mode and block reason ok')

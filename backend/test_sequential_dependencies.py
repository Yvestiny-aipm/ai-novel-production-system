import sqlite3, tempfile
from pathlib import Path
from integration.run_real_test import prior_scenes_completed
with tempfile.TemporaryDirectory() as d:
    db=sqlite3.connect(Path(d)/'x.db'); db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); db.execute("insert into books values ('b','B',null,1,'2026','2026')"); db.execute("insert into chapters values ('c','b',1,null,'2026','2026')")
    for n,status in enumerate(['waiting_confirmation','queued','queued','queued','queued'],1):
        s=f's{n}'; t=f't{n}'; db.execute("insert into scenes values (?,?,?,?,?,?,?,?)",(s,'b','c',n,None,None,'2026','2026')); db.execute("insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",(t,'scene','b','c',s,'planning',status,'start_planning','[]','[]',f'k{n}','2026','2026'))
    db.commit(); assert not prior_scenes_completed(db,'b',2); assert not prior_scenes_completed(db,'b',5)
print('sequential dependencies ok')

import sqlite3, tempfile
from pathlib import Path
from integration.run_real_test import save_report, save_task_result
with tempfile.TemporaryDirectory() as d:
    db=sqlite3.connect(Path(d)/'x.db'); db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); db.execute("insert into books values ('b','B',null,1,'2026','2026')"); db.execute("insert into chapters values ('c','b',1,null,'2026','2026')"); db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')"); db.execute("insert into task_states(task_id,task_scope,book_id,chapter_id,scene_id,current_node,status,next_action,active_contract_refs_json,state_history_json,idempotency_key,created_at,updated_at) values ('t','scene','b','c','s','writing','running','rewrite','[]','[]','k','2026','2026')"); db.commit()
    db.execute("insert into prose_drafts values ('s_draft_v1','b','c','s',1,1,1,1,'x',1,1250,1,'{}','passed','h1','hc1',1,1,'2026')"); db.execute("insert into prose_drafts values ('s_draft_v2','b','c','s',2,2,1,1,'x',1,1250,1,'{}','passed','h2','hc2',2,2,'2026')"); db.commit()
    q={'contract_type':'QualityReport','contract_version':'v1','payload':{'status':'failed','accepted_scene_state':{'x':1},'ordinary_issue_count':1,'serious_issue_count':0,'has_true_conflict':False,'needs_arbiter':False}}
    r1=save_report(db,'b','c','s','s_draft_v1','h1',[q]); r2=save_report(db,'b','c','s','s_draft_v2','h2',[q]); assert r1[0]=='s_report_v1' and r2[0]=='s_report_v2' and db.execute('select count(*) from quality_reports').fetchone()[0]==2
    save_task_result(db,'t','blocked','writing','duplicate_draft_content'); row=db.execute("select current_node,status from task_states where task_id='t'").fetchone(); assert tuple(row)==('writing','blocked')
print('stage12 semantics ok')

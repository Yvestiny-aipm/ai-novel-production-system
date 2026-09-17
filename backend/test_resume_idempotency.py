import sqlite3, tempfile
from pathlib import Path
from backend.context_pack import ContextPackService

with tempfile.TemporaryDirectory() as d:
    db=sqlite3.connect(Path(d)/'x.db'); db.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text())
    db.execute("insert into books values ('b','B',null,1,'2026','2026')"); db.execute("insert into chapters values ('c','b',1,null,'2026','2026')"); db.execute("insert into scenes values ('s','b','c',1,null,null,'2026','2026')"); db.commit()
    svc=ContextPackService(db); kwargs=dict(pack_id='p',book_id='b',chapter_id='c',scene_id='s',version=1,target_agent='planning',target_node='planning',brief_version=1,plan_version=1,story_state_version=1,canon_version=1,sources=[])
    a=svc.assemble(**kwargs); b=svc.assemble(**kwargs); assert a['content_hash']==b['content_hash']; assert db.execute('select count(*) from context_packs').fetchone()[0]==1
print('resume idempotency ok')

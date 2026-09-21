import sqlite3, tempfile
from pathlib import Path
from backend.context_pack import ContextPackService
with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; c=sqlite3.connect(db); c.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); c.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); c.execute("INSERT INTO chapters VALUES ('c','b',1,NULL,'2026','2026')"); c.execute("INSERT INTO scenes VALUES ('s','b','c',1,NULL,NULL,'2026','2026')"); c.commit()
    p=ContextPackService(c); out=p.assemble(pack_id='p',book_id='b',chapter_id='c',scene_id='s',version=1,target_agent='writing',target_node='writing',brief_version=1,plan_version=1,story_state_version=1,canon_version=1,keywords=['castle'],sources=[{'source_id':'a','source_type':'world_rule','target_key':'r','content':'castle is north','version':1},{'source_id':'b','source_type':'book_memory','target_key':'r','content':'castle is south','version':2},{'source_id':'pending','source_type':'book_memory','status':'pending','content':'secret'}],previous_scene_state={'characters':['林照用他']}); assert len(out['conflicts'])==1 and all(x['source_id']!='pending' for x in out['approved_facts']); assert out['content_hash']
    assert out['character_canon']['characters'][0]['name']=='林照'
    assert out['character_canon']['characters'][0]['pronoun']=='她'
    assert out['setting_canon']['places'][0]['name']=='档案室'
    assert [place['name'] for place in out['setting_canon']['places']]==['档案室','记忆厅','字库']
    assert out['previous_scene_state']=={'characters':['林照用他']}
    assert out['setting_canon'] != out['previous_scene_state']
    print('ok')

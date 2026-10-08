import sqlite3, tempfile
from pathlib import Path
from backend.context_pack import ContextPackService
from backend.established_facts import build_world_state
from backend.pacing import build_pacing_state
from backend.chapter_state import build_chapter_state
with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; c=sqlite3.connect(db); c.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); c.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); c.execute("INSERT INTO chapters VALUES ('c','b',1,NULL,'2026','2026')"); c.execute("INSERT INTO scenes VALUES ('s','b','c',1,NULL,NULL,'2026','2026')"); c.commit()
    p=ContextPackService(c); out=p.assemble(pack_id='p',book_id='b',chapter_id='c',scene_id='s',version=1,target_agent='writing',target_node='writing',brief_version=1,plan_version=1,story_state_version=1,canon_version=1,keywords=['castle'],sources=[{'source_id':'a','source_type':'world_rule','target_key':'r','content':'castle is north','version':1},{'source_id':'b','source_type':'book_memory','target_key':'r','content':'castle is south','version':2},{'source_id':'pending','source_type':'book_memory','status':'pending','content':'secret'}],previous_scene_state={'characters':['林照用他']}); assert len(out['conflicts'])==1 and all(x['source_id']!='pending' for x in out['approved_facts']); assert out['content_hash']
    assert out['character_canon']['characters'][0]['name']=='Lin Zhao'
    assert out['character_canon']['characters'][0]['pronoun']=='she'
    assert out['setting_canon']['places'][0]['name']=='Archive Room'
    assert [place['name'] for place in out['setting_canon']['places']]==['Archive Room','Memory Hall','Glyph Vault']
    assert out['previous_scene_state']=={'characters':['林照用他']}
    assert out['setting_canon'] != out['previous_scene_state']
    assert out['established_facts']['facts']==[]
    assert out['established_facts']['rule']=='established_facts_v1'
    assert out['chapter_summary']==''
    assert out['world_state']==build_world_state({'characters':['林照用他']})
    assert out['previous_scene_state']=={'characters':['林照用他']}
    assert out['pacing_state']==build_pacing_state()
    assert 'pacing_state' not in out['established_facts']
    assert out['chapter_state']['is_chapter_open'] is True
    assert out['chapter_state']['is_chapter_close'] is True
    assert out['chapter_state']['scene_in_chapter']==1
    assert out['chapter_state']['scenes_in_chapter']==1
    assert out['chapter_state']['chapter_number']==1
    assert out['chapter_state']['destination']==''
    assert out['chapter_state']['previous_destination']==''
    assert out['chapter_state']['previous_end_location']==''
    assert 'chapter_state' not in out['established_facts']
    assert out['chapter_state']==build_chapter_state(out['chapter_state'])
    print('ok')

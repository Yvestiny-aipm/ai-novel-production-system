import json, sqlite3, tempfile, threading, urllib.request
from pathlib import Path
from http.server import HTTPServer
from api import Handler
from task_state_service import TaskStateService

with tempfile.TemporaryDirectory() as d:
    db=Path(d)/'x.db'; con=sqlite3.connect(db); con.executescript((Path(__file__).parents[1]/'db/migrations/001_initial.sql').read_text()); con.execute("INSERT INTO books VALUES ('b','B',NULL,1,'2026','2026')"); con.commit(); con.close()
    Handler.service=TaskStateService(db); srv=HTTPServer(('127.0.0.1',0),Handler); threading.Thread(target=srv.handle_request).start(); base=f'http://127.0.0.1:{srv.server_port}'
    req=urllib.request.Request(base+'/api/v1/tasks',json.dumps({'task_id':'t','task_scope':'book','book_id':'b','idempotency_key':'k'}).encode(),headers={'Content-Type':'application/json'},method='POST'); assert json.load(urllib.request.urlopen(req))['data']['task_id']=='t'
    srv.server_close(); print('ok')

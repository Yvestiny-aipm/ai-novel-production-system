import http.client, json, sqlite3, tempfile, threading, urllib.request
from pathlib import Path

from backend.local_server import (
    DEMO_BOOK_ID, apply_migrations, build_health, create_local_server,
    ensure_demo_book, load_env_file, prepare_local_db, resolve_static_path,
)


root = Path(__file__).resolve().parents[1]
frontend = root / "frontend"


def start_server(db):
    server = create_local_server(db, host="127.0.0.1", port=0, frontend_root=frontend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def stop_server(server):
    server.shutdown()
    server.server_close()


with tempfile.TemporaryDirectory() as d:
    env_path = Path(d) / ".env"
    env_path.write_text(
        '# comment\nexport DEV_PORT=8124\nSILICONFLOW_API_KEY="sk-must-not-override"\nNEW_ONLY=ok\n',
        encoding="utf-8",
    )
    loaded = load_env_file(env_path, {"SILICONFLOW_API_KEY": "already-set"})
    assert loaded["SILICONFLOW_API_KEY"] == "already-set"
    assert loaded["DEV_PORT"] == "8124"
    assert loaded["NEW_ONLY"] == "ok"
    assert "sk-must-not-override" not in json.dumps(loaded)

    db = Path(d) / "local.db"
    apply_migrations(db)
    apply_migrations(db)
    versions = {
        row[0]
        for row in sqlite3.connect(db).execute("SELECT version FROM schema_migrations")
    }
    assert "001_initial" in versions
    assert "002_prose_draft_length_validation" in versions
    assert "004_scene_progression_checks" in versions
    assert ensure_demo_book(db) is True
    assert ensure_demo_book(db) is False
    assert sqlite3.connect(db).execute(
        "SELECT title FROM books WHERE book_id=?", (DEMO_BOOK_ID,)
    ).fetchone()[0] == "本地演示作品"

    health = build_health(db, frontend)
    assert health["status"] == "ok"
    assert health["db_ready"] is True
    assert health["frontend_ready"] is True
    dumped = json.dumps(health)
    assert "api_key" not in dumped.lower()
    assert "sk-" not in dumped

    assert resolve_static_path(frontend, "/").name == "index.html"
    assert resolve_static_path(frontend, "/admin.html").name == "admin.html"
    assert resolve_static_path(frontend, "/../requirements.txt") is None
    assert resolve_static_path(frontend, "/%2e%2e/requirements.txt") is None
    assert resolve_static_path(frontend, "/missing.html") is None

    prepare_local_db(db)
    server = start_server(db)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        health_body = json.load(urllib.request.urlopen(base + "/healthz"))
        assert health_body["data"]["status"] == "ok"
        assert "SILICONFLOW_API_KEY" not in json.dumps(health_body)
        html = urllib.request.urlopen(base + "/").read().decode()
        assert "创作工作台" in html
        admin = urllib.request.urlopen(base + "/admin.html").read().decode()
        assert "管理后台" in admin
        req = urllib.request.Request(
            base + "/api/v1/tasks",
            json.dumps({
                "task_id": "local-task",
                "task_scope": "book",
                "book_id": DEMO_BOOK_ID,
                "idempotency_key": "local-key",
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        created = json.load(urllib.request.urlopen(req))
        assert created["data"]["task_id"] == "local-task"
        fetched = json.load(urllib.request.urlopen(base + "/api/v1/tasks/local-task"))
        assert fetched["data"]["book_id"] == DEMO_BOOK_ID

        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        conn.request("GET", "/../requirements.txt")
        response = conn.getresponse()
        assert response.status == 404
        conn.close()
    finally:
        stop_server(server)

print("ok")

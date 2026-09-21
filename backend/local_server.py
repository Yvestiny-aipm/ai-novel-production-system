"""Local one-process server: frontend static files plus the existing REST API."""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from .api import Handler
    from .task_state_service import TaskStateService
except ImportError:
    from api import Handler
    from task_state_service import TaskStateService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "local.db"
DEFAULT_FRONTEND = ROOT / "frontend"
DEFAULT_MIGRATIONS = ROOT / "db" / "migrations"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8124
DEMO_BOOK_ID = "local-demo"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def load_env_file(path, environ=None):
    """Load KEY=VALUE lines without printing values or overriding existing env."""
    env = environ if environ is not None else os.environ
    env_path = Path(path)
    if not env_path.is_file():
        return env
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.isidentifier() or key in env:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def apply_migrations(db_path, migrations_dir=None):
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    folder = Path(migrations_dir or DEFAULT_MIGRATIONS)
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        for migration in sorted(folder.glob("*.sql")):
            version = migration.stem
            has_table = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            applied = False
            if has_table:
                applied = bool(
                    con.execute(
                        "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
                    ).fetchone()
                )
            if applied:
                continue
            con.executescript(migration.read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    return db


def ensure_demo_book(db_path):
    con = sqlite3.connect(db_path)
    try:
        if con.execute("SELECT 1 FROM books LIMIT 1").fetchone():
            return False
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        con.execute(
            "INSERT INTO books(book_id, title, current_brief_version, current_canon_version, created_at, updated_at) "
            "VALUES (?, ?, NULL, 1, ?, ?)",
            (DEMO_BOOK_ID, "本地演示作品", now, now),
        )
        con.commit()
        return True
    finally:
        con.close()


def prepare_local_db(db_path, migrations_dir=None):
    apply_migrations(db_path, migrations_dir=migrations_dir)
    ensure_demo_book(db_path)
    return Path(db_path)


def build_health(db_path, frontend_root):
    db_ready = False
    try:
        con = sqlite3.connect(db_path)
        try:
            db_ready = bool(
                con.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone()
            )
        finally:
            con.close()
    except sqlite3.Error:
        db_ready = False
    root = Path(frontend_root)
    frontend_ready = (root / "index.html").is_file() and (root / "admin.html").is_file()
    status = "ok" if db_ready and frontend_ready else "degraded"
    return {
        "status": status,
        "service": "local",
        "db_ready": db_ready,
        "frontend_ready": frontend_ready,
    }


def resolve_static_path(frontend_root, url_path):
    relative = unquote(url_path or "/")
    if relative in {"", "/"}:
        relative = "/index.html"
    if relative.startswith("/"):
        relative = relative[1:]
    root = Path(frontend_root).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


class LocalHandler(Handler):
    frontend_root = DEFAULT_FRONTEND
    db_path = DEFAULT_DB

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/healthz", "/api/v1/health"}:
            payload = build_health(self.db_path, self.frontend_root)
            code = 200 if payload["status"] == "ok" else 503
            return self._send(code, payload)
        if path.startswith("/api/"):
            return Handler.do_GET(self)
        return self._serve_static(path)

    def _serve_static(self, url_path):
        target = resolve_static_path(self.frontend_root, url_path)
        if target is None:
            return self._send(404, error="INVALID_INPUT")
        body = target.read_bytes()
        content_type = STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def create_local_server(db_path, host=DEFAULT_HOST, port=DEFAULT_PORT, frontend_root=None):
    db = prepare_local_db(db_path)
    LocalHandler.service = TaskStateService(str(db))
    LocalHandler.db_path = str(db)
    LocalHandler.frontend_root = Path(frontend_root or DEFAULT_FRONTEND)
    return HTTPServer((host, port), LocalHandler)


def serve(db_path=None, host=None, port=None, frontend_root=None):
    db = db_path or os.environ.get("NOVEL_DB") or DEFAULT_DB
    bind_host = host or os.environ.get("DEV_HOST") or DEFAULT_HOST
    bind_port = int(port or os.environ.get("DEV_PORT") or DEFAULT_PORT)
    server = create_local_server(db, host=bind_host, port=bind_port, frontend_root=frontend_root)
    print(f"local server http://{bind_host}:{server.server_port}/", flush=True)
    print(f"admin       http://{bind_host}:{server.server_port}/admin.html", flush=True)
    print(f"health      http://{bind_host}:{server.server_port}/healthz", flush=True)
    server.serve_forever()


def spawn_detached(*, db, host, port, frontend, env_file, pidfile, logfile):
    command = [
        sys.executable,
        "-m",
        "backend.local_server",
        "--db",
        str(db),
        "--host",
        str(host),
        "--port",
        str(port),
        "--frontend",
        str(frontend or DEFAULT_FRONTEND),
        "--env-file",
        str(env_file),
    ]
    Path(pidfile).parent.mkdir(parents=True, exist_ok=True)
    Path(logfile).parent.mkdir(parents=True, exist_ok=True)
    log = open(logfile, "ab")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    Path(pidfile).write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the local API and frontend on one port.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--frontend", default=None)
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--pidfile", default=str(ROOT / "data" / "dev.pid"))
    parser.add_argument("--logfile", default=str(ROOT / "data" / "dev.log"))
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    if args.daemon:
        pid = spawn_detached(
            db=args.db or os.environ.get("NOVEL_DB") or DEFAULT_DB,
            host=args.host or os.environ.get("DEV_HOST") or DEFAULT_HOST,
            port=args.port or os.environ.get("DEV_PORT") or DEFAULT_PORT,
            frontend=args.frontend,
            env_file=args.env_file,
            pidfile=args.pidfile,
            logfile=args.logfile,
        )
        print(f"started pid={pid}", flush=True)
        return
    serve(db_path=args.db, host=args.host, port=args.port, frontend_root=args.frontend)


if __name__ == "__main__":
    main()

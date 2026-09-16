from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def uid() -> str:
    return uuid.uuid4().hex


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


SCHEMA = """
CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 csrf_hash TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE login_limits(key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at REAL NOT NULL);
CREATE TABLE connections(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, config TEXT NOT NULL, secret TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(owner_id,name));
CREATE TABLE secrets(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, value TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(owner_id,name));
CREATE TABLE profiles(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, config TEXT NOT NULL, UNIQUE(owner_id,name));
CREATE TABLE jobs(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
 name TEXT NOT NULL, config TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
 updated_at REAL NOT NULL, started_at REAL, finished_at REAL, worker_id TEXT, attempt_token TEXT, gateway_hash TEXT,
 heartbeat_at REAL, cancel_requested INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT,
 parent_id TEXT REFERENCES jobs(id), attempt_number INTEGER NOT NULL DEFAULT 1);
CREATE INDEX jobs_owner_date ON jobs(owner_id,created_at DESC,id DESC);
CREATE INDEX jobs_queue ON jobs(status,created_at);
CREATE TABLE idempotency(owner_id TEXT NOT NULL REFERENCES users(id), key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), PRIMARY KEY(owner_id,key));
CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 source_id TEXT NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(job_id,source_id));
CREATE INDEX events_job ON events(job_id,id);
CREATE TABLE workers(id TEXT PRIMARY KEY, heartbeat_at REAL NOT NULL, capabilities TEXT NOT NULL,
 resources TEXT NOT NULL);
CREATE TABLE artifacts(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 job_id TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL, kind TEXT NOT NULL,
 manifest TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX artifacts_owner ON artifacts(owner_id,created_at);
CREATE TABLE conversations(id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, config TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE turns(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 job_id TEXT NOT NULL REFERENCES jobs(id), prompt TEXT NOT NULL, created_at REAL NOT NULL);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise RuntimeError("Database schema is newer than this application")
            if version == 0:
                db.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1; COMMIT;")
            if version < 2:
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE IF NOT EXISTS worker_claims(worker_id TEXT NOT NULL, claim_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), PRIMARY KEY(worker_id,claim_id)); PRAGMA user_version=2; COMMIT;")
            if version < 3:
                db.executescript("BEGIN IMMEDIATE; CREATE TABLE IF NOT EXISTS environment(owner_id TEXT PRIMARY KEY REFERENCES users(id), revision INTEGER NOT NULL, value TEXT NOT NULL); PRAGMA user_version=3; COMMIT;")
        path.chmod(0o600)

    @contextmanager
    def connect(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def backup(self, target: Path):
        with self.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        target.chmod(0o600)


def event(db, job_id: str, kind: str, payload: dict, source_id: str | None = None):
    db.execute("INSERT OR IGNORE INTO events(job_id,source_id,at,kind,payload) VALUES(?,?,?,?,?)",
               (job_id, source_id or uid(), time.time(), kind, encode(payload)))


TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def job_dict(row) -> dict:
    result = dict(row)
    result.pop("attempt_token", None)
    result.pop("gateway_hash", None)
    result["config"] = json.loads(result["config"])
    result["result"] = json.loads(result["result"]) if result["result"] else None
    result["cancel_requested"] = bool(result["cancel_requested"])
    result["worker_connected"] = (time.time() - (result["heartbeat_at"] or 0)) < 30
    return result

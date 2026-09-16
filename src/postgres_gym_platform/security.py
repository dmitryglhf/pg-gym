from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def private_file(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


def vault(directory: Path, database_exists: bool) -> Fernet:
    path = directory / "master.key"
    if not path.exists():
        if database_exists:
            raise RuntimeError("Master key is missing. Restore it; refusing to create a replacement key.")
        try:
            private_file(path, Fernet.generate_key())
        except FileExistsError:
            pass
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise RuntimeError("Master key permissions must be 0600")
    return Fernet(path.read_bytes().strip())


def verify_password(stored: str | None, supplied: str) -> bool:
    try:
        PASSWORDS.verify(stored or DUMMY_HASH, supplied)
        return stored is not None
    except VerificationError:
        return False


def principal(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    bearer = auth.startswith("Bearer ")
    token = auth[7:] if bearer else request.cookies.get("pg_session", "")
    with request.app.state.db.connect() as db:
        row = db.execute("SELECT users.*,sessions.csrf_hash,sessions.kind FROM sessions "
                         "JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires_at>?",
                         (digest(token), time.time())).fetchone()
    if row is None or (bearer and row["kind"] != "token"):
        raise HTTPException(401, "Authentication required")
    if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        csrf = request.headers.get("x-csrf-token", "")
        if origin != request.app.state.config.origin or not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
            raise HTTPException(403, "Invalid request origin or CSRF token")
    return {"id": row["id"], "username": row["username"], "token_hash": digest(token)}


def worker_auth(request: Request):
    expected = request.app.state.config.worker_token
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Worker authentication required")


def owned(db, table: str, identifier: str, owner: str):
    if table not in {"jobs", "connections", "secrets", "profiles", "artifacts", "conversations"}:
        raise ValueError("Unsupported owner table")
    row = db.execute(f"SELECT * FROM {table} WHERE id=? AND owner_id=?", (identifier, owner)).fetchone()
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row


def attempt(db, request: Request, job_id: str):
    row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if row is None or not row["attempt_token"] or not hmac.compare_digest(digest(supplied), row["attempt_token"]):
        raise HTTPException(401, "Invalid attempt token")
    return row

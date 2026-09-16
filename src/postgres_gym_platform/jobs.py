from __future__ import annotations

import hashlib
import json
import time

from fastapi import HTTPException

from .db import TERMINAL, encode, event, job_dict, uid


def submit(db, owner: str, kind: str, config: dict, key: str, *, limit: int = 20, parent_id: str | None = None) -> dict:
    if not key or len(key) > 200:
        raise HTTPException(400, "An Idempotency-Key of at most 200 characters is required")
    fingerprint = hashlib.sha256(encode({"kind": kind, "config": config, "parent": parent_id}).encode()).hexdigest()
    old = db.execute("SELECT * FROM idempotency WHERE owner_id=? AND key=?", (owner, key)).fetchone()
    if old:
        if old["fingerprint"] != fingerprint:
            raise HTTPException(409, "Idempotency-Key was already used for a different request")
        return job_dict(db.execute("SELECT * FROM jobs WHERE id=?", (old["job_id"],)).fetchone())
    active = db.execute("SELECT count(*) FROM jobs WHERE owner_id=? AND status NOT IN ('succeeded','failed','cancelled')", (owner,)).fetchone()[0]
    if active >= limit:
        raise HTTPException(429, "Active job limit reached")
    identifier, now = uid(), time.time()
    number = 1
    if parent_id:
        parent = db.execute("SELECT attempt_number FROM jobs WHERE id=? AND owner_id=?", (parent_id, owner)).fetchone()
        if not parent:
            raise HTTPException(404, "Parent job not found")
        number = parent[0] + 1
    db.execute("INSERT INTO jobs(id,owner_id,kind,name,config,status,created_at,updated_at,parent_id,attempt_number) "
               "VALUES(?,?,?,?,?,'queued',?,?,?,?)", (identifier, owner, kind, config.get("name", kind), encode(config), now, now, parent_id, number))
    db.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (owner, key, fingerprint, identifier))
    event(db, identifier, "status", {"status": "queued", "phase": "queued"})
    return job_dict(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())


def cancel(db, row) -> dict:
    if row["status"] not in TERMINAL:
        status = "cancelled" if row["status"] == "queued" else "cancelling"
        now = time.time()
        db.execute("UPDATE jobs SET status=?,cancel_requested=1,updated_at=?,finished_at=? WHERE id=?",
                   (status, now, now if status == "cancelled" else None, row["id"]))
        event(db, row["id"], "status", {"status": status})
    return job_dict(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())


def event_rows(db, job_id: str, after: int, limit: int = 500) -> list[dict]:
    return [{"id": row["id"], "at": row["at"], "kind": row["kind"], "payload": json.loads(row["payload"])}
            for row in db.execute("SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT ?", (job_id, after, limit))]

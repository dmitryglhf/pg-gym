from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from .db import encode, job_dict, uid
from .jobs import submit
from .schemas import Conversation, Turn
from .security import owned, principal

USER = Depends(principal)

router = APIRouter(prefix="/api/v1")


@router.get("/conversations")
def conversations(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return [{"id": row["id"], "name": row["name"], "created_at": row["created_at"], "config": json.loads(row["config"])} for row in db.execute("SELECT * FROM conversations WHERE owner_id=? ORDER BY created_at DESC LIMIT 200", (user["id"],))]


@router.post("/conversations", status_code=201)
def create(body: Conversation, request: Request, user=USER):
    if len(set(body.connection_ids)) != len(body.connection_ids):
        raise HTTPException(422, "Choose different connections for comparison")
    config = body.model_dump()
    identifier = uid()
    with request.app.state.db.connect(write=True) as db:
        config["connections"] = {key: json.loads(owned(db, "connections", key, user["id"])["config"]) for key in body.connection_ids}
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?)", (identifier, user["id"], body.name, encode(config), time.time()))
    return {"id": identifier, "name": body.name, "config": config}


@router.get("/conversations/{identifier}")
def get(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect() as db:
        row = owned(db, "conversations", identifier, user["id"])
        turns = [{"id": t["turn_id"], "prompt": t["prompt"], "job": job_dict(t)} for t in db.execute(
            "SELECT jobs.*,turns.id AS turn_id,turns.prompt FROM turns JOIN jobs ON jobs.id=turns.job_id WHERE conversation_id=? ORDER BY turns.created_at", (identifier,))]
    return {"id": identifier, "name": row["name"], "config": json.loads(row["config"]), "turns": turns}


@router.post("/conversations/{identifier}/turns", status_code=202)
def turn(identifier: str, body: Turn, request: Request, user=USER):
    key = request.headers.get("idempotency-key", "")
    with request.app.state.db.connect(write=True) as db:
        row = owned(db, "conversations", identifier, user["id"])
        previous = db.execute("SELECT jobs.*,turns.prompt FROM turns JOIN jobs ON jobs.id=turns.job_id WHERE conversation_id=? ORDER BY turns.created_at", (identifier,)).fetchall()
        prior = db.execute("SELECT job_id FROM idempotency WHERE owner_id=? AND key=?", (user["id"], key)).fetchone()
        if any(t["status"] not in {"succeeded", "failed", "cancelled"} for t in previous) and not prior:
            raise HTTPException(409, "Wait for the current response or stop it before sending another message")
        config = {**json.loads(row["config"]), "conversation_id": identifier, "prompt": body.prompt}
        config["history"] = [{"prompt": t["prompt"], "outputs": json.loads(t["result"] or "{}").get("outputs", {})} for t in previous if t["status"] == "succeeded" and (not prior or t["id"] != prior["job_id"])]
        job = submit(db, user["id"], "chat", config, key)
        if not prior:
            db.execute("INSERT INTO turns VALUES(?,?,?,?,?)", (uid(), identifier, job["id"], body.prompt, time.time()))
    return job

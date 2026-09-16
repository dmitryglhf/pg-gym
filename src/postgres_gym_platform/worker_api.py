from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from .db import TERMINAL, encode, event, job_dict
from .environment import connection_key, variable
from .network import upstream_request
from .schemas import Connection, Input
from .security import attempt, digest, owned, random_token, worker_auth

router = APIRouter(prefix="/internal")


@router.post("/jobs/{identifier}/deployment")
def activate_deployment(identifier: str, body: Connection, request: Request):
    with request.app.state.db.connect(write=True) as db:
        job = attempt(db, request, identifier)
        if job["kind"] != "deployment" or job["status"] in TERMINAL:
            raise HTTPException(409, "Not an active deployment")
        config = body.model_dump(exclude={"api_key"})
        config["managed_job_id"] = identifier
        config["artifact_id"] = json.loads(job["config"])["artifact_id"]
        key = request.app.state.vault.encrypt(body.api_key.get_secret_value().encode()).decode() if body.api_key else ""
        db.execute("INSERT INTO connections VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,secret=excluded.secret",
                   (identifier, job["owner_id"], body.name + " " + identifier[:8], encode(config), key, time.time()))
        db.execute("UPDATE jobs SET result=? WHERE id=?", (encode({"connection_id": identifier}), identifier))
    return {"id": identifier}


class WorkerReport(Input):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    capabilities: list[Literal["benchmark", "model_import", "training", "deployment", "chat", "evaluation"]] = Field(max_length=6)
    resources: dict = Field(default_factory=dict)
    claim_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Events(Input):
    events: list[dict] = Field(max_length=100)


class Finish(Input):
    status: Literal["succeeded", "failed", "cancelled"]
    error: str | None = Field(default=None, max_length=2000)
    result: dict | None = None


@router.post("/workers/heartbeat", dependencies=[Depends(worker_auth)])
def worker_heartbeat(body: WorkerReport, request: Request):
    with request.app.state.db.connect(write=True) as db:
        db.execute("INSERT INTO workers VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at,capabilities=excluded.capabilities,resources=excluded.resources",
                   (body.id, time.time(), encode(body.capabilities), encode(body.resources)))
    return {"ok": True}


@router.post("/workers/claim", dependencies=[Depends(worker_auth)])
def claim(body: WorkerReport, request: Request):
    token = hmac.new(request.app.state.config.worker_token.encode(), (body.id + ":" + body.claim_id).encode(), hashlib.sha256).hexdigest() if body.claim_id else random_token()
    gateway = hmac.new(token.encode(), b"provider-only", hashlib.sha256).hexdigest()
    with request.app.state.db.connect(write=True) as db:
        if body.claim_id:
            previous = db.execute("SELECT jobs.* FROM jobs JOIN worker_claims ON jobs.id=worker_claims.job_id WHERE worker_claims.worker_id=? AND claim_id=?", (body.id, body.claim_id)).fetchone()
            if previous:
                return {"job": job_dict(previous), "attempt_token": token, "gateway_token": gateway}
        busy_gpu = db.execute("SELECT 1 FROM jobs WHERE worker_id=? AND kind IN ('training','deployment','evaluation') AND status NOT IN ('succeeded','failed','cancelled')", (body.id,)).fetchone()
        active = db.execute("SELECT count(*) FROM jobs WHERE worker_id=? AND status NOT IN ('succeeded','failed','cancelled')", (body.id,)).fetchone()[0]
        if active >= 4:
            return {"job": None}
        kinds = [kind for kind in body.capabilities if not (busy_gpu and kind in {"training", "deployment", "evaluation"})]
        if not kinds:
            return {"job": None}
        placeholders = ",".join("?" for _ in kinds)
        candidates = db.execute(f"SELECT * FROM jobs WHERE status='queued' AND cancel_requested=0 AND kind IN ({placeholders}) ORDER BY created_at LIMIT 1", kinds).fetchall()
        selected = next((r for r in candidates if r["kind"] in body.capabilities and not (busy_gpu and r["kind"] in {"training", "deployment", "evaluation"})), None)
        if not selected:
            return {"job": None}
        now = time.time()
        db.execute("UPDATE jobs SET status='preparing',worker_id=?,attempt_token=?,gateway_hash=?,heartbeat_at=?,started_at=?,updated_at=? WHERE id=? AND status='queued'",
                   (body.id, digest(token), digest(gateway), now, now, now, selected["id"]))
        if body.claim_id:
            db.execute("INSERT INTO worker_claims VALUES(?,?,?)", (body.id, body.claim_id, selected["id"]))
        event(db, selected["id"], "status", {"status": "preparing", "worker_id": body.id})
        job = job_dict(db.execute("SELECT * FROM jobs WHERE id=?", (selected["id"],)).fetchone())
    return {"job": job, "attempt_token": token, "gateway_token": gateway}


@router.post("/jobs/{identifier}/heartbeat")
def heartbeat(identifier: str, request: Request):
    with request.app.state.db.connect(write=True) as db:
        row = attempt(db, request, identifier)
        if row["status"] not in TERMINAL:
            db.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (time.time(), identifier))
        return {"cancel_requested": bool(row["cancel_requested"]), "status": row["status"]}


@router.get("/jobs/{identifier}/input")
def job_input(identifier: str, request: Request):
    with request.app.state.db.connect() as db:
        row = attempt(db, request, identifier)
        if row["status"] in TERMINAL:
            raise HTTPException(409, "Attempt has finished")
        config = json.loads(row["config"])
        credential = None
        if row["kind"] == "model_import" and config.get("credential_id"):
            secret = owned(db, "secrets", config["credential_id"], row["owner_id"])
            credential = request.app.state.vault.decrypt(secret["value"].encode()).decode()
        if row["kind"] == "model_import" and config.get("credential_env"):
            credential = variable(db, request.app.state.vault, row["owner_id"], config["credential_env"])
    return {"job": job_dict(row), "credential": credential}


@router.post("/jobs/{identifier}/events")
def events(identifier: str, body: Events, request: Request):
    with request.app.state.db.connect(write=True) as db:
        row = attempt(db, request, identifier)
        if row["status"] in TERMINAL:
            return {"ok": True}
        for item in body.events:
            if not isinstance(item.get("source_id"), str) or not isinstance(item.get("payload"), dict) or item.get("kind") not in {"status", "phase", "log", "metrics", "episode", "delta", "artifact", "resource"}:
                raise HTTPException(422, "Invalid worker event")
            event(db, identifier, item["kind"], item["payload"], item["source_id"])
        db.execute("UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelling' ELSE 'running' END,updated_at=?,heartbeat_at=? WHERE id=?", (time.time(), time.time(), identifier))
    return {"ok": True}


@router.post("/jobs/{identifier}/finish")
def finish(identifier: str, body: Finish, request: Request):
    with request.app.state.db.connect(write=True) as db:
        row = attempt(db, request, identifier)
        if row["status"] in TERMINAL:
            return job_dict(row)
        now = time.time()
        db.execute("UPDATE jobs SET status=?,error=?,result=?,updated_at=?,finished_at=?,heartbeat_at=? WHERE id=?",
                   (body.status, body.error, encode(body.result) if body.result is not None else None, now, now, now, identifier))
        event(db, identifier, "status", {"status": body.status, "error": body.error})
        return job_dict(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())


@router.post("/provider/{identifier}/v1/{path:path}")
async def provider(identifier: str, path: str, request: Request):
    if path not in {"chat/completions", "completions"}:
        raise HTTPException(404, "Unsupported provider operation")
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    with request.app.state.db.connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        if row is None or row["status"] in TERMINAL or not row["gateway_hash"] or not hmac.compare_digest(digest(supplied), row["gateway_hash"]):
            raise HTTPException(401, "Invalid provider token")
        cfg = json.loads(row["config"])
        connection_id = request.headers.get("x-pg-connection") or cfg.get("connection_id")
        allowed = cfg.get("connection_ids", [cfg.get("connection_id")])
        if connection_id not in allowed:
            raise HTTPException(403, "Connection does not belong to this attempt")
        connection = owned(db, "connections", connection_id, row["owner_id"])
        snapshot = cfg.get("connection") or cfg.get("connections", {}).get(connection_id)
        if not snapshot:
            raise HTTPException(409, "Connection snapshot is missing")
        key = connection_key(db, request.app.state.vault, connection, snapshot)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(422, "Expected a provider request object")
    body["model"] = snapshot["model"]
    try:
        requested = int(body.get("max_tokens") or snapshot["max_tokens"])
    except (TypeError, ValueError):
        raise HTTPException(422, "Invalid token limit") from None
    body["max_tokens"] = min(max(requested, 1), snapshot["max_tokens"])
    headers = {"Authorization": "Bearer " + key} if key else {}
    client = request.app.state.http
    try:
        outgoing = upstream_request(client, snapshot, request.app.state.config.allowed_hosts, "POST", "/" + path, json=body, headers=headers)
        upstream = await client.send(outgoing, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Provider could not be reached") from exc
    async def stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
    return StreamingResponse(stream(), status_code=upstream.status_code, media_type=upstream.headers.get("content-type", "application/json"), headers={"X-Accel-Buffering": "no"})

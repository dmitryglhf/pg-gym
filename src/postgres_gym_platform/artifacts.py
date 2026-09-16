from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

from .db import encode, event, uid
from .schemas import Input
from .security import attempt, owned, principal

USER = Depends(principal)

router = APIRouter()


class ArtifactFile(Input):
    path: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=0, le=100 * 1024**3)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactCreate(Input):
    job_id: str
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern=r"^(model|adapter|report|checkpoint)$")
    files: list[ArtifactFile] = Field(min_length=1, max_length=10000)
    metadata: dict = Field(default_factory=dict)


def safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in value or ":" in value or any(p.startswith(".") for p in path.parts):
        raise HTTPException(422, "Invalid artifact path")
    return Path(*path.parts)


def public_artifact(row):
    return {"id": row["id"], "job_id": row["job_id"], "name": row["name"], "kind": row["kind"], "created_at": row["created_at"], **json.loads(row["manifest"])}


@router.get("/api/v1/artifacts")
def list_artifacts(request: Request, paginated: bool = False, limit: int = 50,
                   cursor: str | None = None, kind: str | None = None, user=USER):
    from .pagination import decode_cursor
    if not paginated:
        with request.app.state.db.connect() as db:
            return [public_artifact(row) for row in db.execute("SELECT * FROM artifacts WHERE owner_id=? ORDER BY created_at DESC LIMIT 500", (user["id"],))]
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    stamp, identifier = decode_cursor(cursor)
    with request.app.state.db.connect() as db:
        rows = db.execute(
            "SELECT * FROM artifacts WHERE owner_id=? AND (? IS NULL OR kind=?) "
            "AND (? IS NULL OR created_at<? OR (created_at=? AND id<?)) "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (user["id"], kind, kind, stamp, stamp, stamp, identifier, limit + 1),
        ).fetchall()
    next_cursor = f"{rows[limit - 1]['created_at']}:{rows[limit - 1]['id']}" if len(rows) > limit else None
    return {"items": [public_artifact(row) for row in rows[:limit]], "next": next_cursor}


@router.get("/api/v1/artifacts/{identifier}")
def get_artifact(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return public_artifact(owned(db, "artifacts", identifier, user["id"]))


def file_response(row, relative: str, request: Request):
    safe_relative(relative)
    manifest = json.loads(row["manifest"])
    if manifest["status"] != "ready" or relative not in {f["path"] for f in manifest["files"]}:
        raise HTTPException(404, "Artifact file is not available")
    path = request.app.state.config.data / "artifacts" / row["id"] / relative
    if not path.is_file():
        raise HTTPException(503, "Artifact file is missing from storage")
    return FileResponse(path, filename=Path(relative).name, media_type="application/octet-stream")


@router.get("/api/v1/artifacts/{identifier}/files/{relative:path}")
def download(identifier: str, relative: str, request: Request, user=USER):
    with request.app.state.db.connect() as db:
        row = owned(db, "artifacts", identifier, user["id"])
    return file_response(row, relative, request)


@router.get("/internal/jobs/{job_id}/artifacts/{identifier}")
def worker_artifact(job_id: str, identifier: str, request: Request):
    with request.app.state.db.connect() as db:
        job = attempt(db, request, job_id)
        row = owned(db, "artifacts", identifier, job["owner_id"])
    return public_artifact(row)


@router.get("/internal/jobs/{job_id}/artifacts/{identifier}/files/{relative:path}")
def worker_download(job_id: str, identifier: str, relative: str, request: Request):
    with request.app.state.db.connect() as db:
        job = attempt(db, request, job_id)
        row = owned(db, "artifacts", identifier, job["owner_id"])
    return file_response(row, relative, request)


@router.post("/internal/artifacts", status_code=201)
def create_artifact(body: ArtifactCreate, request: Request):
    paths = [item.path for item in body.files]
    if len(paths) != len(set(paths)):
        raise HTTPException(422, "Artifact paths must be unique")
    for path in paths:
        safe_relative(path)
    total = sum(item.size for item in body.files)
    if total > 250 * 1024**3:
        raise HTTPException(413, "Artifact exceeds 250 GiB")
    if shutil.disk_usage(request.app.state.config.data).free < total + 1024**3:
        raise HTTPException(409, "Insufficient artifact storage")
    identifier = hashlib.sha256(encode(body.model_dump()).encode()).hexdigest()[:32]
    with request.app.state.db.connect(write=True) as db:
        job = attempt(db, request, body.job_id)
        existing = db.execute("SELECT * FROM artifacts WHERE id=? AND owner_id=?", (identifier, job["owner_id"])).fetchone()
        if existing:
            return {"id": identifier, "status": json.loads(existing["manifest"])["status"]}
        if body.metadata.get("base_artifact_id"):
            owned(db, "artifacts", body.metadata["base_artifact_id"], job["owner_id"])
        manifest = {"status": "uploading", "files": [f.model_dump() for f in body.files], "metadata": body.metadata, "size": total}
        db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", (identifier, job["owner_id"], body.job_id, body.name, body.kind, encode(manifest), time.time()))
    (request.app.state.config.data / "artifacts" / identifier).mkdir(parents=True, exist_ok=True, mode=0o700)
    return {"id": identifier}


@router.put("/internal/artifacts/{identifier}/files/{relative:path}")
async def upload(identifier: str, relative: str, request: Request):
    safe_relative(relative)
    with request.app.state.db.connect() as db:
        row = db.execute("SELECT * FROM artifacts WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, "Artifact not found")
        attempt(db, request, row["job_id"])
        manifest = json.loads(row["manifest"])
    if manifest["status"] != "uploading":
        raise HTTPException(409, "Artifact is immutable")
    expected = next((f for f in manifest["files"] if f["path"] == relative), None)
    if expected is None:
        raise HTTPException(404, "File is not in the manifest")
    path = request.app.state.config.data / "artifacts" / identifier / relative
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".upload-" + uid())
    checksum, count = hashlib.sha256(), 0
    try:
        with temporary.open("xb") as output:
            temporary.chmod(0o600)
            async for chunk in request.stream():
                count += len(chunk)
                if count > expected["size"]:
                    raise HTTPException(413, "File exceeds declared size")
                checksum.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if count != expected["size"] or checksum.hexdigest() != expected["sha256"]:
            raise HTTPException(422, "File size or checksum does not match")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/internal/artifacts/{identifier}/complete")
def complete(identifier: str, request: Request):
    with request.app.state.db.connect(write=True) as db:
        row = db.execute("SELECT * FROM artifacts WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise HTTPException(404, "Artifact not found")
        attempt(db, request, row["job_id"])
        manifest = json.loads(row["manifest"])
        directory = request.app.state.config.data / "artifacts" / identifier
        if any(not (directory / f["path"]).is_file() or (directory / f["path"]).stat().st_size != f["size"] for f in manifest["files"]):
            raise HTTPException(409, "Artifact upload is incomplete")
        manifest["status"] = "ready"
        db.execute("UPDATE artifacts SET manifest=? WHERE id=?", (encode(manifest), identifier))
        event(db, row["job_id"], "artifact", {"id": identifier, "name": row["name"], "kind": row["kind"]}, "artifact-" + identifier)
    return {"id": identifier, "status": "ready"}

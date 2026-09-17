from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager

import httpx2
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .catalog import Catalog
from .config import Config
from .db import TERMINAL, Database, encode, job_dict, uid
from .environment import connection_key, variable
from .jobs import cancel, event_rows, submit
from .network import endpoint, upstream_request
from .schemas import (
    Benchmark,
    Connection,
    Credential,
    Deployment,
    Evaluation,
    Harness,
    Login,
    ModelImport,
    Register,
    TokenRequest,
    Training,
)
from .security import (
    PASSWORDS,
    digest,
    owned,
    principal,
    random_token,
    vault,
    verify_password,
)

USER = Depends(principal)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        os.environ["POSTGRES_GYM_ROOT"] = str(cfg.root)
        app.state.config = cfg
        app.state.vault = vault(cfg.secret_dir, (cfg.data / "platform.sqlite").exists())
        app.state.db = Database(cfg.data / "platform.sqlite")
        app.state.catalog = Catalog(cfg.root)
        async with httpx2.AsyncClient(
            timeout=httpx2.Timeout(120, connect=15),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.http = client
            yield

    app = FastAPI(
        title="Postgres Gym",
        version=__version__,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        codes = {
            400: "invalid_request",
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "too_large",
            422: "validation_error",
            429: "rate_limit",
            503: "unavailable",
        }
        return JSONResponse(
            {
                "error": {
                    "code": codes.get(exc.status_code, "request_failed"),
                    "message": str(exc.detail),
                }
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Check the submitted fields",
                    "fields": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                        for e in exc.errors()
                    ],
                }
            },
            status_code=422,
        )

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(_request, _exc):
        return JSONResponse(
            {
                "error": {
                    "code": "conflict",
                    "message": "A resource with this name already exists",
                }
            },
            status_code=409,
        )

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": str(exc)}}, status_code=422
        )

    @app.middleware("http")
    async def headers(request: Request, call_next):
        length = request.headers.get("content-length", "0")
        try:
            too_large = int(length) > 2 * 1024 * 1024
        except ValueError:
            too_large = True
        streaming_file = (
            request.method == "PUT"
            and request.url.path.startswith("/internal/artifacts/")
            and "/files/" in request.url.path
        )
        if too_large and not streaming_file:
            return JSONResponse(
                {
                    "error": {
                        "code": "too_large",
                        "message": "Request body exceeds 2 MiB",
                    }
                },
                status_code=413,
            )
        if not streaming_file:
            content = bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > 2 * 1024 * 1024:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "too_large",
                                "message": "Request body exceeds 2 MiB",
                            }
                        },
                        status_code=413,
                    )
            request._body = bytes(content)
        response = await call_next(request)
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["cache-control"] = "no-store"
        response.headers["x-request-id"] = uid()
        return response

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "version": __version__}

    app.include_router(public)
    from .artifacts import router as artifact_router
    from .environment import router as environment_router
    from .inference import router as inference_router
    from .worker_api import router as worker_router

    app.include_router(environment_router)
    app.include_router(artifact_router)
    app.include_router(inference_router)
    app.include_router(worker_router)
    return app


public = APIRouter(prefix="/api/v1")


def auth_origin(request: Request):
    if (
        request.headers.get("origin")
        and request.headers["origin"] != request.app.state.config.origin
    ):
        raise HTTPException(403, "Invalid request origin")


@public.get("/auth/options")
def auth_options(request: Request):
    return {
        "registration_code_required": not request.app.state.config.open_registration
    }


@public.post("/auth/register", status_code=201)
def register(body: Register, request: Request):
    auth_origin(request)
    cfg = request.app.state.config
    if not cfg.open_registration and (
        not cfg.registration_token
        or not hmac.compare_digest(
            body.invitation.get_secret_value(), cfg.registration_token
        )
    ):
        raise HTTPException(403, "A valid registration code is required")
    with request.app.state.db.connect(write=True) as db:
        identifier = uid()
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?)",
            (
                identifier,
                body.username,
                PASSWORDS.hash(body.password.get_secret_value()),
                time.time(),
            ),
        )
    return {"id": identifier, "username": body.username}


def authenticate(body: Login, request: Request):
    auth_origin(request)
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    bucket = digest(ip + ":" + body.username.casefold())
    with request.app.state.db.connect(write=True) as db:
        limit = db.execute(
            "SELECT * FROM login_limits WHERE key=?", (bucket,)
        ).fetchone()
        if limit and limit["reset_at"] > now and limit["attempts"] >= 10:
            raise HTTPException(
                429, "Too many login attempts. Try again in 15 minutes."
            )
        if not limit or limit["reset_at"] <= now:
            db.execute(
                "INSERT OR REPLACE INTO login_limits VALUES(?,1,?)", (bucket, now + 900)
            )
        else:
            db.execute(
                "UPDATE login_limits SET attempts=attempts+1 WHERE key=?", (bucket,)
            )
        row = db.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (body.username,)
        ).fetchone()
    if not verify_password(
        row["password_hash"] if row else None, body.password.get_secret_value()
    ):
        raise HTTPException(401, "Invalid username or password")
    with request.app.state.db.connect(write=True) as db:
        db.execute("DELETE FROM login_limits WHERE key=?", (bucket,))
    return row


@public.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    row = authenticate(body, request)
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    bucket = digest(ip + ":" + body.username.casefold())
    token, csrf = random_token(), random_token()
    cfg = request.app.state.config
    with request.app.state.db.connect(write=True) as db:
        db.execute("DELETE FROM login_limits WHERE key=?", (bucket,))
        db.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
            (
                digest(token),
                row["id"],
                digest(csrf),
                "session",
                "Browser",
                now + cfg.session_seconds,
            ),
        )
    response.set_cookie(
        "pg_session",
        token,
        httponly=True,
        secure=cfg.secure_cookie,
        samesite="lax",
        max_age=cfg.session_seconds,
        path="/",
    )
    response.set_cookie(
        "pg_csrf",
        csrf,
        httponly=False,
        secure=cfg.secure_cookie,
        samesite="lax",
        max_age=cfg.session_seconds,
        path="/",
    )
    return {"id": row["id"], "username": row["username"], "csrf": csrf}


@public.post("/auth/logout")
def logout(request: Request, response: Response, user=USER):
    with request.app.state.db.connect(write=True) as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
    response.delete_cookie("pg_session", path="/")
    response.delete_cookie("pg_csrf", path="/")
    return {"ok": True}


@public.get("/me")
def me(user=USER):
    return {"id": user["id"], "username": user["username"]}


@public.post("/api-tokens", status_code=201)
def token_create(body: TokenRequest, request: Request, user=USER):
    value, expires = random_token(), time.time() + body.days * 86400
    with request.app.state.db.connect(write=True) as db:
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
            (digest(value), user["id"], "", "token", body.name, expires),
        )
    return {"token": value, "expires_at": expires, "id": digest(value)}


@public.get("/api-tokens")
def tokens(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT token_hash AS id,name,expires_at FROM sessions WHERE user_id=? AND kind='token'",
                (user["id"],),
            )
        ]


@public.delete("/api-tokens/{identifier}")
def token_delete(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        db.execute(
            "DELETE FROM sessions WHERE token_hash=? AND user_id=? AND kind='token'",
            (identifier, user["id"]),
        )
    return {"ok": True}


@public.get("/suites")
def suites(
    request: Request,
    paginated: bool = False,
    limit: int = 50,
    cursor: str | None = None,
    _user=USER,
):
    values = request.app.state.catalog.suites
    if not paginated:
        return values
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be between 1 and 200")
    values = sorted(
        (item for item in values if cursor is None or item["id"] > cursor),
        key=lambda item: item["id"],
    )
    return {
        "items": values[:limit],
        "next": values[limit - 1]["id"] if len(values) > limit else None,
    }


@public.get("/suites/{suite}/tasks")
def tasks(suite: str, request: Request, split: str | None = None, _user=USER):
    return [
        {"suite": item["suite"], "name": item["name"]}
        for item in request.app.state.catalog.select(suite, split=split)
    ]


@public.get("/suites/{suite}/tasks/{task}")
def task(suite: str, task: str, request: Request, _user=USER):
    return request.app.state.catalog.select(suite, [task])[0]


def connection_public(row):
    return {
        "id": row["id"],
        **json.loads(row["config"]),
        "has_key": bool(row["secret"] or json.loads(row["config"]).get("api_key_env")),
    }


@public.get("/connections")
def connections(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return [
            connection_public(row)
            for row in db.execute(
                "SELECT * FROM connections WHERE owner_id=? ORDER BY created_at",
                (user["id"],),
            )
        ]


@public.post("/connections", status_code=201)
def connection_create(body: Connection, request: Request, user=USER):
    cfg = body.model_dump(exclude={"api_key"})
    cfg["base_url"] = endpoint(body.base_url, request.app.state.config.allowed_hosts)
    secret = (
        request.app.state.vault.encrypt(
            body.api_key.get_secret_value().encode()
        ).decode()
        if body.api_key
        else ""
    )
    identifier = uid()
    with request.app.state.db.connect(write=True) as db:
        if body.api_key_env:
            variable(db, request.app.state.vault, user["id"], body.api_key_env)
            secret = ""
        db.execute(
            "INSERT INTO connections VALUES(?,?,?,?,?,?)",
            (identifier, user["id"], body.name, encode(cfg), secret, time.time()),
        )
        return connection_public(owned(db, "connections", identifier, user["id"]))


@public.put("/connections/{identifier}")
def connection_update(identifier: str, body: Connection, request: Request, user=USER):
    cfg = body.model_dump(exclude={"api_key"})
    cfg["base_url"] = endpoint(body.base_url, request.app.state.config.allowed_hosts)
    with request.app.state.db.connect(write=True) as db:
        old = owned(db, "connections", identifier, user["id"])
        if json.loads(old["config"]).get("managed_job_id"):
            raise HTTPException(
                409, "Managed connections are configured by their deployment"
            )
        secret = (
            old["secret"]
            if body.api_key is None
            else (
                request.app.state.vault.encrypt(
                    body.api_key.get_secret_value().encode()
                ).decode()
                if body.api_key.get_secret_value()
                else ""
            )
        )
        if body.api_key_env:
            variable(db, request.app.state.vault, user["id"], body.api_key_env)
            secret = ""
        db.execute(
            "UPDATE connections SET name=?,config=?,secret=? WHERE id=?",
            (body.name, encode(cfg), secret, identifier),
        )
        return connection_public(owned(db, "connections", identifier, user["id"]))


@public.post("/connections/{identifier}/check")
async def connection_check(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect() as db:
        row = owned(db, "connections", identifier, user["id"])
        cfg = json.loads(row["config"])
        key = connection_key(db, request.app.state.vault, row)
    try:
        client = request.app.state.http
        outgoing = upstream_request(
            client,
            cfg,
            request.app.state.config.allowed_hosts,
            "GET",
            "/models",
            headers={"Authorization": "Bearer " + key} if key else {},
        )
        response = await client.send(outgoing)
        response.raise_for_status()
        models = [
            item["id"]
            for item in response.json().get("data", [])
            if isinstance(item.get("id"), str)
        ]
        return {
            "ok": cfg["model"] in models,
            "models": models,
            "message": "Model is available"
            if cfg["model"] in models
            else "Configured model was not listed",
        }
    except (httpx2.HTTPError, ValueError, KeyError) as exc:
        logging.getLogger(__name__).info(
            "Connection check failed: %s", type(exc).__name__
        )
        raise HTTPException(
            502, "Endpoint check failed. Check the address, model and credentials."
        ) from exc


@public.get("/secrets")
def secrets_list(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT id,name,created_at FROM secrets WHERE owner_id=?", (user["id"],)
            )
        ]


@public.post("/secrets", status_code=201)
def secret_create(body: Credential, request: Request, user=USER):
    identifier = uid()
    value = request.app.state.vault.encrypt(
        body.value.get_secret_value().encode()
    ).decode()
    with request.app.state.db.connect(write=True) as db:
        db.execute(
            "INSERT INTO secrets VALUES(?,?,?,?,?)",
            (identifier, user["id"], body.name, value, time.time()),
        )
    return {"id": identifier, "name": body.name}


@public.get("/harness-profiles")
def profiles(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return [
            {"id": r["id"], **json.loads(r["config"])}
            for r in db.execute(
                "SELECT * FROM profiles WHERE owner_id=?", (user["id"],)
            )
        ]


@public.post("/harness-profiles", status_code=201)
def profile_create(body: Harness, request: Request, user=USER):
    identifier = uid()
    with request.app.state.db.connect(write=True) as db:
        db.execute(
            "INSERT INTO profiles VALUES(?,?,?,?)",
            (identifier, user["id"], body.name, encode(body.model_dump())),
        )
    return {"id": identifier, **body.model_dump()}


@public.post("/benchmarks", status_code=202)
def benchmark_create(body: Benchmark, request: Request, user=USER):
    selected = request.app.state.catalog.select(body.suite, body.tasks, body.split)
    cfg = body.model_dump()
    cfg["tasks"] = [item["name"] for item in selected]
    cfg["task_hashes"] = {item["name"]: item["task_hash"] for item in selected}
    cfg["protocol"] = "agentic-benchmark.v1"
    with request.app.state.db.connect(write=True) as db:
        row = owned(db, "connections", body.connection_id, user["id"])
        cfg["connection"] = json.loads(row["config"])
        if not cfg["connection"].get("tools"):
            raise HTTPException(
                422, "Benchmark requires a connection configured for tool calling"
            )
        if body.profile_id:
            profile = json.loads(
                owned(db, "profiles", body.profile_id, user["id"])["config"]
            )
            if profile["harness"] != body.harness:
                raise HTTPException(422, "Profile belongs to a different harness")
            cfg["profile"] = profile
        return submit(
            db,
            user["id"],
            "benchmark",
            cfg,
            request.headers.get("idempotency-key", ""),
            limit=request.app.state.config.max_jobs_per_user,
        )


@public.post("/models/imports", status_code=202)
def model_import(body: ModelImport, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        if body.credential_id and body.credential_env:
            raise HTTPException(422, "Choose one credential source")
        if body.credential_env:
            variable(db, request.app.state.vault, user["id"], body.credential_env)
        if body.credential_id:
            owned(db, "secrets", body.credential_id, user["id"])
        return submit(
            db,
            user["id"],
            "model_import",
            body.model_dump(),
            request.headers.get("idempotency-key", ""),
        )


@public.post("/training-runs", status_code=202)
def training_create(body: Training, request: Request, user=USER):
    tasks = request.app.state.catalog.select(body.suite, split=body.split)
    if body.split == "test":
        raise HTTPException(422, "The test split is reserved for evaluation")
    cfg = {
        **body.model_dump(),
        "task_hashes": {t["name"]: t["task_hash"] for t in tasks},
        "protocol": "direct-diff-grpo.v1",
    }
    with request.app.state.db.connect(write=True) as db:
        artifact = owned(db, "artifacts", body.artifact_id, user["id"])
        if (
            json.loads(artifact["manifest"]).get("status") != "ready"
            or artifact["kind"] != "model"
        ):
            raise HTTPException(422, "Select a complete base model artifact")
        return submit(
            db, user["id"], "training", cfg, request.headers.get("idempotency-key", "")
        )


@public.post("/deployments", status_code=202)
def deployment_create(body: Deployment, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        artifact = owned(db, "artifacts", body.artifact_id, user["id"])
        if json.loads(artifact["manifest"]).get("status") != "ready" or artifact[
            "kind"
        ] not in {"model", "adapter"}:
            raise HTTPException(422, "Select a complete model or adapter")
        return submit(
            db,
            user["id"],
            "deployment",
            body.model_dump(),
            request.headers.get("idempotency-key", ""),
        )


@public.get("/jobs")
def jobs_list(
    request: Request,
    kind: str | None = None,
    before: str | None = None,
    limit: int = 50,
    user=USER,
):
    limit = max(1, min(limit, 200))
    stamp, identifier = None, ""
    if before:
        parts = before.split(":", 1)
        try:
            stamp = float(parts[0])
        except ValueError:
            raise HTTPException(422, "Invalid pagination cursor") from None
        identifier = parts[1] if len(parts) > 1 else ""
    with request.app.state.db.connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs WHERE owner_id=? AND (? IS NULL OR kind=?) AND (? IS NULL OR created_at<? OR (created_at=? AND id<?)) ORDER BY created_at DESC,id DESC LIMIT ?",
            (user["id"], kind, kind, stamp, stamp, stamp, identifier, limit + 1),
        ).fetchall()
    cursor = (
        f"{rows[limit - 1]['created_at']}:{rows[limit - 1]['id']}"
        if len(rows) > limit
        else None
    )
    return {"items": [job_dict(row) for row in rows[:limit]], "next": cursor}


@public.get("/jobs/{identifier}")
def job_get(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect() as db:
        return job_dict(owned(db, "jobs", identifier, user["id"]))


@public.post("/jobs/{identifier}/cancel", status_code=202)
@public.post("/deployments/{identifier}/stop", status_code=202)
def job_cancel(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        return cancel(db, owned(db, "jobs", identifier, user["id"]))


@public.post("/jobs/{identifier}/retries", status_code=202)
def job_retry(identifier: str, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        row = owned(db, "jobs", identifier, user["id"])
        if row["status"] not in TERMINAL or row["kind"] == "chat":
            raise HTTPException(409, "Only finished non-chat jobs can be retried")
        return submit(
            db,
            user["id"],
            row["kind"],
            json.loads(row["config"]),
            request.headers.get("idempotency-key", ""),
            parent_id=identifier,
        )


@public.get("/jobs/{identifier}/events")
async def job_events(identifier: str, request: Request, after: int = 0, user=USER):
    with request.app.state.db.connect() as db:
        owned(db, "jobs", identifier, user["id"])
        rows = event_rows(db, identifier, max(0, after))
    if "text/event-stream" not in request.headers.get("accept", ""):
        return {"items": rows, "next": rows[-1]["id"] if rows else after}
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(400, "Invalid event cursor") from None

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            try:
                principal(request)
            except HTTPException:
                break
            with request.app.state.db.connect() as db:
                rows = event_rows(db, identifier, cursor)
                row = owned(db, "jobs", identifier, user["id"])
            for item in rows:
                cursor = item["id"]
                yield f"id: {cursor}\ndata: {encode(item)}\n\n"
            if not rows and row["status"] in TERMINAL:
                yield "event: end\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@public.get("/capabilities")
def capabilities(request: Request, _user=USER):
    with request.app.state.db.connect() as db:
        workers = [
            {
                "id": r["id"],
                "connected": time.time() - r["heartbeat_at"] < 30,
                "capabilities": json.loads(r["capabilities"]),
                "resources": json.loads(r["resources"]),
                "sample_at": r["heartbeat_at"],
            }
            for r in db.execute("SELECT * FROM workers")
        ]
    return {
        "workers": workers,
        "harnesses": ["markov", "opencode"],
        "algorithms": ["GRPO"],
        "version": __version__,
    }


@public.post("/evaluations", status_code=202)
def evaluation_create(body: Evaluation, request: Request, user=USER):
    selected = request.app.state.catalog.select(body.suite, split=body.split)
    config = {
        **body.model_dump(),
        "task_hashes": {t["name"]: t["task_hash"] for t in selected},
        "protocol": "direct-diff-evaluation.v1",
    }
    with request.app.state.db.connect(write=True) as db:
        artifact = owned(db, "artifacts", body.artifact_id, user["id"])
        if (
            artifact["kind"] not in {"model", "adapter"}
            or json.loads(artifact["manifest"])["status"] != "ready"
        ):
            raise HTTPException(422, "Select a ready model or adapter")
        return submit(
            db,
            user["id"],
            "evaluation",
            config,
            request.headers.get("idempotency-key", ""),
        )


@public.post("/auth/token")
def password_token(body: Login, request: Request):
    row = authenticate(body, request)
    token = random_token()
    with request.app.state.db.connect(write=True) as db:
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?)",
            (digest(token), row["id"], "", "token", "CLI", time.time() + 86400 * 30),
        )
    return {"token": token, "user": {"id": row["id"], "username": row["username"]}}


@public.delete("/connections/{identifier}")
@public.delete("/secrets/{identifier}")
@public.delete("/harness-profiles/{identifier}")
def settings_delete(identifier: str, request: Request, user=USER):
    resource = request.url.path.split("/")[-2]
    table = {
        "connections": "connections",
        "secrets": "secrets",
        "harness-profiles": "profiles",
    }[resource]
    with request.app.state.db.connect(write=True) as db:
        resource_row = owned(db, table, identifier, user["id"])
        if table == "connections" and json.loads(resource_row["config"]).get(
            "managed_job_id"
        ):
            running = db.execute(
                "SELECT 1 FROM jobs WHERE id=? AND status NOT IN ('succeeded','failed','cancelled')",
                (identifier,),
            ).fetchone()
            if running:
                raise HTTPException(
                    409, "Stop the deployment before deleting its connection"
                )
        active = db.execute(
            "SELECT 1 FROM jobs WHERE owner_id=? AND status NOT IN ('succeeded','failed','cancelled') AND config LIKE ?",
            (user["id"], "%" + identifier + "%"),
        ).fetchone()
        if active:
            raise HTTPException(409, "This resource is used by an active job")
        db.execute(
            f"DELETE FROM {table} WHERE id=? AND owner_id=?", (identifier, user["id"])
        )
    return {"ok": True}


@public.put("/secrets/{identifier}")
def secret_update(identifier: str, body: Credential, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        owned(db, "secrets", identifier, user["id"])
        value = request.app.state.vault.encrypt(
            body.value.get_secret_value().encode()
        ).decode()
        db.execute(
            "UPDATE secrets SET name=?,value=? WHERE id=?",
            (body.name, value, identifier),
        )
    return {"id": identifier, "name": body.name}


@public.put("/harness-profiles/{identifier}")
def profile_update(identifier: str, body: Harness, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        owned(db, "profiles", identifier, user["id"])
        db.execute(
            "UPDATE profiles SET name=?,config=? WHERE id=?",
            (body.name, encode(body.model_dump()), identifier),
        )
    return {"id": identifier, **body.model_dump()}

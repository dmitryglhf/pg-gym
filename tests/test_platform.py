from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from postgres_gym_platform.api import create_app
from postgres_gym_platform.config import Config
from postgres_gym_platform.runtime import atomic_json
from postgres_gym_platform.worker import sync_job

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "a-long-testing-password"
WORKER = {"Authorization": "Bearer test-worker-token"}


@pytest.fixture
def client(tmp_path):
    cfg = Config(
        data=tmp_path / "data",
        secret_dir=tmp_path / "secrets",
        root=ROOT,
        open_registration=True,
        worker_token="test-worker-token",
    )
    with TestClient(create_app(cfg)) as client:
        yield client


def account(client, name="alice"):
    body = {"username": name, "password": PASSWORD}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    r = client.post("/api/v1/auth/token", json=body)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def connection(client, auth):
    r = client.post(
        "/api/v1/connections",
        headers=auth,
        json={
            "name": "Endpoint",
            "base_url": "http://127.0.0.1:9812/v1",
            "model": "original-model",
            "api_key": "test-upstream-secret",
            "tools": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def benchmark(client, auth, conn, key="submission-1"):
    r = client.post(
        "/api/v1/benchmarks",
        headers={**auth, "Idempotency-Key": key},
        json={"suite": "sql-function-set", "tasks": ["area"], "connection_id": conn},
    )
    assert r.status_code == 202, r.text
    return r.json()


def claim(client, identifier="cpu-1", key=None, kinds=None):
    r = client.post(
        "/internal/workers/claim",
        headers=WORKER,
        json={
            "id": identifier,
            "capabilities": kinds or ["benchmark"],
            "claim_id": key,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def attempt_headers(assignment):
    return {"Authorization": "Bearer " + assignment["attempt_token"]}


def test_idempotent_submit_claim_and_gpu_exclusion(client):
    auth = account(client)
    conn = connection(client, auth)
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = list(pool.map(lambda _: benchmark(client, auth, conn), range(6)))
    assert len({job["id"] for job in jobs}) == 1
    one = claim(client, key="a" * 32)
    assert one == claim(client, key="a" * 32)
    assert claim(client, identifier="cpu-2")["job"] is None
    assert "attempt_token" not in one["job"] and "gateway_hash" not in one["job"]
    r = client.post(
        "/api/v1/benchmarks",
        headers={**auth, "Idempotency-Key": "submission-1"},
        json={
            "suite": "sql-function-set",
            "tasks": ["area"],
            "connection_id": conn,
            "name": "Different",
        },
    )
    assert r.status_code == 409
    with client.app.state.db.connect(write=True) as db:
        db.execute("UPDATE jobs SET kind='training' WHERE id=?", (one["job"]["id"],))
    two = benchmark(client, auth, conn, "submission-2")
    with client.app.state.db.connect(write=True) as db:
        db.execute("UPDATE jobs SET kind='deployment' WHERE id=?", (two["id"],))
    assert claim(client, kinds=["deployment"])["job"] is None
    assert (
        claim(client, identifier="gpu-2", kinds=["deployment"])["job"]["id"]
        == two["id"]
    )


def test_pagination_same_timestamp(client):
    auth = account(client)
    conn = connection(client, auth)
    for i in range(3):
        benchmark(client, auth, conn, f"submit-{i}")
    with client.app.state.db.connect(write=True) as db:
        db.execute("UPDATE jobs SET created_at=12345")
    seen, cursor = [], None
    for _ in range(3):
        page = client.get(
            "/api/v1/jobs",
            headers=auth,
            params={"limit": 1, **({"before": cursor} if cursor else {})},
        ).json()
        seen += [j["id"] for j in page["items"]]
        cursor = page["next"]
    assert len(set(seen)) == 3 and cursor is None


def test_worker_recovers_truncated_event_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "postgres_gym_platform.worker.cleanup_containers", lambda _: True
    )
    atomic_json(
        tmp_path / "assignment.json",
        {"job": {"id": "lost"}, "attempt_token": "attempt"},
    )
    atomic_json(tmp_path / "process.json", {"pid": 99999999, "created": time.time()})
    (tmp_path / "events.jsonl").write_bytes(b'{"source_id":"unfinished')
    observed = []

    def transport(request):
        observed.append(request.url.path)
        return httpx.Response(
            200, json={"status": "running", "cancel_requested": False}
        )

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(transport)
    ) as http:
        sync_job(http, tmp_path)
    assert (tmp_path / "acknowledged").exists()
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "failed"
    assert "/internal/jobs/lost/finish" in observed


def test_process_identity_in_pid_namespace():
    import os

    from postgres_gym_platform.runtime import process_identity
    from postgres_gym_platform.worker import alive

    identity = process_identity()
    assert identity["pid"] == os.getpid()
    assert alive(identity)
    assert not alive({**identity, "created": identity["created"] - 1})


def test_worker_keeps_reservation_until_container_cleanup(tmp_path, monkeypatch):
    atomic_json(
        tmp_path / "assignment.json",
        {"job": {"id": "deployment", "kind": "deployment"}, "attempt_token": "attempt"},
    )
    atomic_json(
        tmp_path / "result.json", {"status": "cancelled", "error": None, "result": None}
    )
    observed = []

    def transport(request):
        observed.append(request.url.path)
        return httpx.Response(
            200, json={"status": "cancelling", "cancel_requested": True}
        )

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(transport)
    ) as http:
        monkeypatch.setattr(
            "postgres_gym_platform.worker.cleanup_containers", lambda _: False
        )
        sync_job(http, tmp_path)
        assert not (tmp_path / "acknowledged").exists()
        assert "/internal/jobs/deployment/finish" not in observed
        monkeypatch.setattr(
            "postgres_gym_platform.worker.cleanup_containers", lambda _: True
        )
        sync_job(http, tmp_path)
        assert (tmp_path / "acknowledged").exists()

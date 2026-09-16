from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from postgres_gym_platform.api import create_app
from postgres_gym_platform.config import Config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def platform(tmp_path):
    config = Config(data=tmp_path / "data", secret_dir=tmp_path / "secrets", root=ROOT,
                    registration_token="registration-test", worker_token="worker-test")
    app = create_app(config)
    with TestClient(app) as client:
        users = {}
        for name in ("alice", "bob"):
            body = {"username": name, "password": "test-password-1234"}
            assert client.post("/api/v1/auth/register", json={**body, "invitation": "registration-test"}).status_code == 201
            response = client.post("/api/v1/auth/token", json=body)
            assert response.status_code == 200
            users[name] = {"Authorization": "Bearer " + response.json()["token"]}
        yield client, app, users


def connection(client, headers, name="local"):
    response = client.post("/api/v1/connections", headers=headers, json={
        "name": name, "base_url": "http://127.0.0.1:9009/v1", "model": "test-model", "api_key": "private-provider-test", "tools": True})
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, headers, connection_id, key="benchmark-1", **config):
    return client.post("/api/v1/benchmarks", headers={**headers, "Idempotency-Key": key}, json={
        "suite": "sql-function-set", "tasks": ["area"], "connection_id": connection_id, **config})


def claim(client, capabilities=None):
    response = client.post("/internal/workers/claim", headers={"Authorization": "Bearer worker-test"}, json={
        "id": "test-worker", "capabilities": capabilities or ["benchmark", "model_import", "training", "evaluation", "deployment", "chat"], "resources": {}})
    assert response.status_code == 200, response.text
    return response.json()

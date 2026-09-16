import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi.testclient import TestClient

from postgres_gym_platform.api import create_app

from .conftest import claim, connection, submit


def test_auth_and_csrf(platform):
    client, _, users = platform
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.post("/api/v1/auth/register", json={"username": "eve", "password": "test-password-1234"}).status_code == 403
    response = client.post("/api/v1/auth/login", json={"username": "alice", "password": "test-password-1234"})
    assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example", "X-CSRF-Token": response.json()["csrf"]}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:8000", "X-CSRF-Token": response.json()["csrf"]}).status_code == 200
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=users["alice"]).status_code == 200


def test_owner_isolation_and_encrypted_credentials(platform):
    client, app, users = platform
    alice, bob = users.values()
    conn = connection(client, alice)
    assert "private-provider-test" not in json.dumps(conn)
    job = submit(client, alice, conn["id"]).json()
    for suffix in ("", "/events"):
        assert client.get("/api/v1/jobs/" + job["id"] + suffix, headers=bob).status_code == 404
    assert client.post("/api/v1/jobs/" + job["id"] + "/cancel", headers=bob).status_code == 404
    assert client.delete("/api/v1/connections/" + conn["id"], headers=bob).status_code == 404
    assert submit(client, bob, conn["id"]).status_code == 404
    assert client.get("/api/v1/connections", headers=bob).json() == []
    with app.state.db.connect() as db:
        secret = db.execute("SELECT secret FROM connections WHERE id=?", (conn["id"],)).fetchone()[0]
        assert "private-provider-test" not in secret
        assert app.state.vault.decrypt(secret.encode()) == b"private-provider-test"


def test_concurrent_submission_claims_and_retries(platform):
    client, _, users = platform
    headers = users["alice"]
    conn = connection(client, headers)
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: submit(client, headers, conn["id"]), range(4)))
    assert all(r.status_code == 202 for r in responses)
    job_id = responses[0].json()["id"]
    assert {r.json()["id"] for r in responses} == {job_id}
    assert submit(client, headers, conn["id"], name="changed").status_code == 409
    with ThreadPoolExecutor(4) as pool:
        claims = list(pool.map(lambda _: claim(client), range(4)))
    assignments = [c for c in claims if c["job"]]
    assert len(assignments) == 1
    job_token = {"Authorization": "Bearer " + assignments[0]["attempt_token"]}
    finish = client.post(f"/internal/jobs/{job_id}/finish", headers=job_token, json={"status": "succeeded", "result": {"mean_reward": 0.5}})
    assert finish.status_code == 200
    retry = client.post(f"/api/v1/jobs/{job_id}/retries", headers={**headers, "Idempotency-Key": "retry"}).json()
    assert retry["parent_id"] == job_id and retry["attempt_number"] == 2
    assert retry["config"] == responses[0].json()["config"]


def test_events_reconnect_scope_and_cancellation(platform):
    client, _, users = platform
    headers = users["alice"]
    conn = connection(client, headers)
    job = submit(client, headers, conn["id"]).json()
    assigned = claim(client)
    token = {"Authorization": "Bearer " + assigned["attempt_token"]}
    gateway = {"Authorization": "Bearer " + assigned["gateway_token"]}
    assert client.get(f'/internal/jobs/{job["id"]}/input', headers=gateway).status_code == 401
    assert client.post("/internal/workers/claim", headers=token, json={"id": "bad", "capabilities": []}).status_code == 401
    endpoint = f'/internal/jobs/{job["id"]}'
    event = {"source_id": "event-1", "kind": "phase", "payload": {"phase": "build"}}
    for _ in range(2):
        assert client.post(endpoint + "/events", headers=token, json={"events": [event]}).status_code == 200
    events = client.get(f'/api/v1/jobs/{job["id"]}/events', headers=headers).json()
    assert len([e for e in events["items"] if e["kind"] == "phase"]) == 1
    assert client.get(f'/api/v1/jobs/{job["id"]}/events?after={events["next"]}', headers=headers).json()["items"] == []
    assert client.post(f'/api/v1/jobs/{job["id"]}/cancel', headers=headers).json()["status"] == "cancelling"
    assert client.post(endpoint + "/heartbeat", headers=token).json()["cancel_requested"]
    assert client.post(endpoint + "/finish", headers=token, json={"status": "cancelled"}).status_code == 200
    response = client.get(f'/api/v1/jobs/{job["id"]}/events', headers={**headers, "Accept": "text/event-stream", "Last-Event-ID": str(events["next"])})
    assert "event: end" in response.text and '"status":"cancelled"' in response.text


def test_sqlite_restart_preserves_history(platform):
    client, app, users = platform
    conn = connection(client, users["alice"])
    job = submit(client, users["alice"], conn["id"]).json()
    with TestClient(create_app(app.state.config)) as restarted:
        assert restarted.get("/api/v1/jobs/" + job["id"], headers=users["alice"]).json()["id"] == job["id"]
        assert restarted.get("/api/v1/connections", headers=users["alice"]).json()[0]["has_key"]


def test_artifact_integrity_and_access(platform):
    client, _, users = platform
    headers = users["alice"]
    conn = connection(client, headers)
    job = submit(client, headers, conn["id"]).json()
    assigned = claim(client)
    token = {"Authorization": "Bearer " + assigned["attempt_token"]}
    content = b'{"reward":0.8}'
    body = {"job_id": job["id"], "name": "Report", "kind": "report", "files": [{"path": "episode.json", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}]}
    invalid = {**body, "files": [{**body["files"][0], "path": "../secret"}]}
    assert client.post("/internal/artifacts", headers=token, json=invalid).status_code == 422
    response = client.post("/internal/artifacts", headers=token, json=body)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    path = f"/internal/artifacts/{identifier}"
    assert client.post(path + "/complete", headers=token).status_code == 409
    assert client.put(path + "/files/episode.json", headers=token, content=b"bad").status_code == 422
    assert client.put(path + "/files/episode.json", headers=token, content=content).status_code == 200
    assert client.post(path + "/complete", headers=token).status_code == 200
    assert client.put(path + "/files/episode.json", headers=token, content=content).status_code == 409
    assert client.get(f"/api/v1/artifacts/{identifier}/files/episode.json", headers=headers).content == content
    assert client.get(f"/api/v1/artifacts/{identifier}/files/episode.json", headers=users["bob"]).status_code == 404


def test_validation_does_not_echo_secrets_and_limits_chunked_body(platform):
    client, _, users = platform
    response = client.post("/api/v1/connections", headers=users["alice"], json={"api_key": "secret-not-to-echo"})
    assert response.status_code == 422 and "secret-not-to-echo" not in response.text
    response = client.post("/api/v1/connections", headers=users["alice"], content=iter([b"a" * 1024**2] * 3))
    assert response.status_code == 413


def test_gateway_forces_snapshot_and_hides_provider_key(platform):
    client, app, users = platform
    conn = connection(client, users["alice"])
    job = submit(client, users["alice"], conn["id"]).json()
    assignment = claim(client)
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(200, json={"model": "test-model", "choices": []})
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    response = client.post(f'/internal/provider/{job["id"]}/v1/chat/completions', headers={"Authorization": "Bearer " + assignment["gateway_token"]}, json={"model": "other", "max_tokens": 999999})
    assert response.status_code == 200
    assert json.loads(seen[0].content)["model"] == "test-model"
    assert json.loads(seen[0].content)["max_tokens"] == 4096
    assert seen[0].headers["authorization"] == "Bearer private-provider-test"
    assert "private-provider-test" not in response.text


def test_chat_serialization_and_private_history(platform):
    client, _, users = platform
    conn = connection(client, users["alice"])
    conv = client.post("/api/v1/conversations", headers=users["alice"], json={"connection_ids": [conn["id"]]}).json()
    endpoint = f'/api/v1/conversations/{conv["id"]}'
    headers = {**users["alice"], "Idempotency-Key": "turn-1"}
    job = client.post(endpoint + "/turns", headers=headers, json={"prompt": "hello"}).json()
    assert client.post(endpoint + "/turns", headers=headers, json={"prompt": "hello"}).json()["id"] == job["id"]
    assert client.post(endpoint + "/turns", headers={**headers, "Idempotency-Key": "turn-2"}, json={"prompt": "next"}).status_code == 409
    assert client.get(endpoint, headers=users["bob"]).status_code == 404
    assert client.get(endpoint, headers=users["alice"]).json()["turns"][0]["prompt"] == "hello"

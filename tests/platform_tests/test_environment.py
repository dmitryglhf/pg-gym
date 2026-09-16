import json

import httpx

from .conftest import claim


def test_environment_is_private_encrypted_and_revision_checked(platform):
    client, app, users = platform
    alice, bob = users["alice"], users["bob"]
    assert client.get("/api/v1/environment").status_code == 401
    saved = client.put("/api/v1/environment", headers=alice, json={"revision": 0, "variables": {"MODEL_KEY": "private-env-key", "EMPTY": ""}})
    assert saved.status_code == 200
    assert saved.json() == {"revision": 1, "names": ["EMPTY", "MODEL_KEY"]}
    assert "private-env-key" not in client.get("/api/v1/environment", headers=alice).text
    assert client.post("/api/v1/environment/reveal", headers=bob).json()["variables"] == {}
    assert client.post("/api/v1/environment/reveal", headers=alice).json()["variables"]["MODEL_KEY"] == "private-env-key"
    with app.state.db.connect() as db:
        stored = db.execute("SELECT value FROM environment").fetchone()[0]
    assert "private-env-key" not in stored
    assert json.loads(app.state.vault.decrypt(stored.encode()))["MODEL_KEY"] == "private-env-key"
    assert client.put("/api/v1/environment", headers=alice, json={"revision": 0, "variables": {}}).status_code == 409
    assert client.put("/api/v1/environment", headers=alice, json={"revision": 1, "variables": {"MODEL_KEY": None}}).status_code == 200
    assert client.post("/api/v1/environment/reveal", headers=alice).json()["variables"] == {"MODEL_KEY": "private-env-key"}
    invalid = client.put("/api/v1/environment", headers=alice, json={"revision": 2, "variables": {"INVALID KEY": "secret-never-echo"}})
    assert invalid.status_code == 422 and "secret-never-echo" not in invalid.text
    assert client.put("/api/v1/environment", headers=alice, json={"revision": 2, "variables": {"MODEL_KEY": "a\x00b"}}).status_code == 422


def test_environment_keys_resolve_for_connections_and_hf(platform):
    client, app, users = platform
    alice, bob = users["alice"], users["bob"]
    client.put("/api/v1/environment", headers=alice, json={"revision": 0, "variables": {"MODEL_KEY": "model-env-secret", "HF_TOKEN": "hf-env-secret"}})
    body = {"name": "variable model", "base_url": "http://localhost:9009/v1", "model": "model", "api_key_env": "MODEL_KEY", "tools": True}
    assert client.post("/api/v1/connections", headers=bob, json=body).status_code == 422
    conn = client.post("/api/v1/connections", headers=alice, json=body).json()
    assert conn["has_key"] and "model-env-secret" not in json.dumps(conn)
    seen = []

    def provider(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"data": [{"id": "model"}]})

    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    assert client.post(f'/api/v1/connections/{conn["id"]}/check', headers=alice).json()["ok"]
    assert seen == ["Bearer model-env-secret"]
    assert client.put("/api/v1/environment", headers=alice, json={"revision": 1, "variables": {"HF_TOKEN": None}}).status_code == 409
    job = client.post("/api/v1/models/imports", headers={**alice, "Idempotency-Key": "env-hf"}, json={"repository": "org/model", "credential_env": "HF_TOKEN"}).json()
    assert "hf-env-secret" not in json.dumps(job)
    assignment = claim(client, capabilities=["model_import"])
    response = client.get(f'/internal/jobs/{job["id"]}/input', headers={"Authorization": "Bearer " + assignment["attempt_token"]})
    assert response.status_code == 200
    assert response.json()["credential"] == "hf-env-secret"
    assert "environment" not in response.json()
    assert client.put("/api/v1/environment", headers=alice, json={"revision": 1, "variables": {"MODEL_KEY": None}}).status_code == 409

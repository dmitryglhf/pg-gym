import json
from pathlib import Path

import httpx2

from postgres_gym.collect import journal
from postgres_gym.collect.journal import Recorder


def completion(prompt_tokens: int) -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 3},
    }


def gateway(responses: list[dict], seen: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/v1/models":
            return httpx2.Response(200, json={"data": [{"id": "m"}]})
        return httpx2.Response(200, json=responses.pop(0))

    return httpx2.MockTransport(handler)


def post(recorder: Recorder, episode: str, body: dict, headers=None) -> journal.Reply:
    return recorder.handle(
        "POST", episode, journal.COMPLETIONS, headers or {}, json.dumps(body).encode()
    )


def test_completions_are_journaled_in_order(tmp_path: Path):
    seen: list[httpx2.Request] = []
    recorder = Recorder(
        tmp_path,
        "http://gateway/",
        transport=gateway([completion(100), completion(250)], seen),
    )
    headers = {"Authorization": "Bearer k", "Host": "proxy", "Content-Length": "0"}
    for content in ("hi", "again"):
        reply = post(
            recorder,
            "ep",
            {"messages": [{"role": "user", "content": content}]},
            headers,
        )
        assert reply.status == 200
        assert json.loads(reply.body)["usage"]["completion_tokens"] == 3

    lines = journal.read(recorder.path("ep"))
    assert [line["turn"] for line in lines] == [0, 1]
    assert lines[1]["request"]["messages"][0]["content"] == "again"
    assert lines[1]["usage"]["prompt_tokens"] == 250
    assert lines[1]["response"]["choices"][0]["message"]["content"] == "ok"
    assert lines[1]["error"] is None
    assert [r.headers["authorization"] for r in seen] == ["Bearer k", "Bearer k"]
    assert seen[0].headers["host"] == "gateway"
    assert str(seen[0].url) == "http://gateway/v1/chat/completions"
    turns = recorder.turns("ep")
    assert (turns.calls, turns.max_prompt_tokens, turns.errors) == (2, 250, 0)
    assert not turns.exhausted


def test_budget_refuses_the_next_call_once_the_ceiling_is_passed(tmp_path: Path):
    seen: list[httpx2.Request] = []
    recorder = Recorder(
        tmp_path,
        "http://gateway",
        budget=200,
        transport=gateway([completion(100), completion(250)], seen),
    )
    assert post(recorder, "ep", {}).status == 200
    assert post(recorder, "ep", {}).status == 200
    refused = post(recorder, "ep", {})
    assert refused.status == 400
    error = json.loads(refused.body)["error"]
    assert error["kind"] == "budget"
    assert "250" in error["message"] and "200" in error["message"]
    assert post(recorder, "ep", {}).status == 400

    lines = journal.read(recorder.path("ep"))
    assert len(lines) == 3
    assert lines[2]["turn"] == 2
    assert lines[2]["response"] is None
    assert lines[2]["error"]["kind"] == "budget"
    assert len(seen) == 2
    turns = recorder.turns("ep")
    assert (turns.calls, turns.errors, turns.exhausted) == (2, 1, True)


def test_other_requests_pass_through_without_a_journal(tmp_path: Path):
    seen: list[httpx2.Request] = []
    recorder = Recorder(tmp_path, "http://gateway", transport=gateway([], seen))
    reply = recorder.handle(
        "GET", "ep", "v1/models", {"Authorization": "Bearer k"}, b""
    )

    assert reply.status == 200
    assert json.loads(reply.body)["data"][0]["id"] == "m"
    assert str(seen[0].url) == "http://gateway/v1/models"
    assert not recorder.path("ep").exists()
    assert recorder.turns("ep").calls == 0


def test_gateway_failures_are_journaled_as_errors(tmp_path: Path):
    transport = httpx2.MockTransport(lambda request: httpx2.Response(500, text="boom"))
    recorder = Recorder(tmp_path, "http://gateway", transport=transport)
    reply = post(recorder, "ep", {})

    assert reply.status == 500
    line = journal.read(recorder.path("ep"))[0]
    assert line["error"] == {"kind": "provider", "status": 500, "message": "boom"}
    assert line["response"] is None
    assert recorder.turns("ep").errors == 1


def test_unreachable_gateway_answers_502(tmp_path: Path):
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    recorder = Recorder(
        tmp_path, "http://gateway", transport=httpx2.MockTransport(handler)
    )
    reply = post(recorder, "ep", {})

    assert reply.status == 502
    assert json.loads(reply.body)["error"]["kind"] == "transport"
    assert journal.read(recorder.path("ep"))[0]["error"]["status"] == 502


def test_split_path():
    assert journal.split_path("/episodes/e1/v1/chat/completions?x=1") == (
        "e1",
        "v1/chat/completions",
    )
    assert journal.split_path("/episodes/e1/model/info") == ("e1", "model/info")
    assert journal.split_path("/health") == (None, "")
    assert journal.split_path("/episodes/") == (None, "")


def test_served_over_http(tmp_path: Path):
    seen: list[httpx2.Request] = []
    transport = gateway([completion(5)], seen)
    with Recorder(
        tmp_path, "http://gateway", host="127.0.0.1", transport=transport
    ) as recorder:
        url = recorder.url("ep", host="127.0.0.1")
        assert url == f"http://127.0.0.1:{recorder.port}/episodes/ep"
        assert (
            recorder.url("ep")
            == f"http://host.docker.internal:{recorder.port}/episodes/ep"
        )
        with httpx2.Client(trust_env=False) as client:
            reply = client.post(
                url + "/v1/chat/completions",
                json={"messages": []},
                headers={"Authorization": "Bearer k"},
            )
            assert reply.status_code == 200
            assert reply.json()["usage"]["prompt_tokens"] == 5
            assert (
                client.get(f"http://127.0.0.1:{recorder.port}/nope").status_code == 404
            )
    assert journal.read(recorder.path("ep"))[0]["request"] == {"messages": []}
    assert seen[0].headers["authorization"] == "Bearer k"


def test_default_upstream_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("PGPRO_HOST", raising=False)
    monkeypatch.setenv("MARKOV_BASE_URL", "http://gw:4000/v1")
    assert journal.default_upstream() == "http://gw:4000"
    monkeypatch.setenv("PGPRO_HOST", "http://other/")
    assert journal.default_upstream() == "http://other"
    monkeypatch.delenv("PGPRO_HOST")
    monkeypatch.delenv("MARKOV_BASE_URL")
    assert journal.default_upstream() == journal.DEFAULT_UPSTREAM

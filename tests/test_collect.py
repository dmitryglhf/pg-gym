import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest

from postgres_gym import settings
from postgres_gym.collect import episode, run
from postgres_gym.collect.journal import Turns
from postgres_gym.execution.base import TaskResult
from postgres_gym.gym import EpisodeResult, Gym

SUITE = "sql-function-set"


class FakeBackend:
    name = "fake"
    scored = False

    def available(self):
        return None

    def build(self, args=None):
        return 0

    def run(self, request):
        raise AssertionError("episodes are faked in these tests")


def result(record: dict | None, returncode: int = 0) -> EpisodeResult:
    records = (Path("record.json"),) if returncode == 0 else ()
    execution = TaskResult(returncode, "", "boom", records, "fake")
    return EpisodeResult(SUITE, "area", episode.AGENT, execution, record)


@pytest.mark.parametrize(
    ("record", "outcome", "turns", "expected"),
    [
        ({"pass": True}, {}, Turns(calls=3), "scored_pass"),
        ({"pass": False}, {}, Turns(calls=3), "scored_fail"),
        ({"pass": False}, {}, Turns(), "no_trajectory"),
        ({"pass": False}, {"timed_out": True}, Turns(calls=2), "agent_timeout"),
        (
            {"pass": False, "agent_meta": {"timed_out": True}},
            {},
            Turns(calls=2),
            "agent_timeout",
        ),
        (
            {"pass": True},
            {},
            Turns(calls=4, errors=1, exhausted=True),
            "budget_exhausted",
        ),
        ({"pass": False}, {"max_turns_message": True}, Turns(calls=4), "max_turns"),
        ({"pass": False}, {}, Turns(calls=2, errors=1), "provider_error"),
        (
            {"pass": False},
            {"error": "RequestError: x"},
            Turns(calls=2),
            "provider_error",
        ),
        ({"pass": False}, {"error_reply": True}, Turns(calls=2), "provider_error"),
        ({"pass": False, "error": "boom"}, {}, Turns(calls=2), "execution_error"),
    ],
)
def test_classify(record, outcome, turns, expected):
    assert episode.classify(result(record), outcome, turns) == expected


def test_classify_failed_execution():
    assert episode.classify(result(None, returncode=1), {}, Turns(calls=2)) == (
        "execution_error"
    )


def test_harness_environment_points_markov_at_the_recorder():
    harness = episode.Harness("m", 60, 28000, 1800, "s3cret")
    env = harness.environment("http://host.docker.internal:5/episodes/e")

    assert env["PGPRO_HOST"] == "http://host.docker.internal:5/episodes/e"
    assert env["GOOSE_MODEL"] == "m"
    assert env["GOOSE_MAX_TURNS"] == "60"
    assert env["GOOSE_TOOL_PAIR_SUMMARIZATION"] == "false"
    assert env["GOOSE_SERVER__SECRET_KEY"] == "s3cret"
    assert env["POSTGRES_GYM_AGENT_TIMEOUT"] == str(
        1800 + episode.CONTAINER_TIMEOUT_MARGIN
    )


def fake_markov_sdk(monkeypatch, failure: Exception) -> None:
    """A markov_sdk whose turn breaks with `failure` before any event."""

    class Stream:
        def __iter__(self):
            raise failure

    class Chat:
        id = "session-1"

        def tools(self):
            return [SimpleNamespace(name=name) for name in reversed(episode.TOOLS)]

        def stream_sync(self, prompt):
            return Stream()

        def close(self):
            return None

    class Agent:
        def __init__(self, *args, **kwargs):
            self.loop = SimpleNamespace(run=lambda value: value)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def open_session_sync(self):
            return Chat()

    module = types.ModuleType("markov_sdk")
    module.Agent = Agent
    module.Builtin = lambda name: name
    module.MarkovError = type("MarkovError", (Exception,), {})
    module.MessageUsage = type("MessageUsage", (), {})
    module.Server = SimpleNamespace(remote=lambda url, secret_key: None)
    module.ToolCallStarted = type("ToolCallStarted", (), {})
    monkeypatch.setitem(sys.modules, "markov_sdk", module)


def test_converse_treats_a_late_transport_error_as_a_timeout(monkeypatch):
    fake_markov_sdk(monkeypatch, httpx2.ReadError("connection closed"))
    harness = episode.Harness("m", 60, 28000, 0, "s3cret")

    outcome = episode.converse("http://127.0.0.1:1", "fix it", harness)

    assert outcome["timed_out"] is True
    assert "error" not in outcome
    assert outcome["tools"] == sorted(episode.TOOLS)


def test_converse_reports_an_early_transport_error(monkeypatch):
    fake_markov_sdk(monkeypatch, httpx2.ReadError("connection closed"))
    harness = episode.Harness("m", 60, 28000, 1800, "s3cret")

    outcome = episode.converse("http://127.0.0.1:1", "fix it", harness)

    assert outcome["timed_out"] is False
    assert outcome["error"] == "ReadError: connection closed"


def test_report_carries_the_harness_and_the_outcome(tmp_path: Path):
    record = {"pass": True, "reward": 1.0, "execution": {"image_id": "sha256:1"}}
    execution = TaskResult(0, "", "", (tmp_path / "record.json",), "docker")
    outcome = {
        "session_id": "s",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5},
        "tool_calls": 2,
        "agent_seconds": 3.0,
        "tools": list(episode.TOOLS),
    }
    harness = episode.Harness("m", 60, 28000, 1800, "s3cret")
    trajectory = tmp_path / "e1.jsonl"
    trajectory.write_text("{}\n")
    entry = episode.report(
        EpisodeResult(SUITE, "area", episode.AGENT, execution, record),
        outcome,
        Turns(calls=3, max_prompt_tokens=900),
        harness,
        episode_id="e1",
        attempt=1,
        task_hash="h",
        trajectory=trajectory,
        seconds=12.34,
    )

    assert entry["state"] == "scored_pass" and entry["pass"]
    assert entry["image_id"] == "sha256:1"
    assert entry["trajectory_file"] == "e1.jsonl"
    assert entry["record_file"] == str(tmp_path / "record.json")
    assert (entry["provider_calls"], entry["max_prompt_tokens"]) == (3, 900)
    assert entry["seconds"] == 12.3
    assert entry["error"] is None
    assert "container_tail" not in entry
    assert "s3cret" not in json.dumps(entry)


def test_report_keeps_the_container_tail_when_execution_failed(tmp_path: Path):
    execution = TaskResult(1, "", "traceback", (), "docker")
    entry = episode.report(
        EpisodeResult(SUITE, "area", episode.AGENT, execution, None),
        {"error": "container never started"},
        Turns(),
        episode.Harness("m", 60, None, 1800, "x"),
        episode_id="e1",
        attempt=1,
        task_hash="h",
        trajectory=tmp_path / "e1.jsonl",
        seconds=1,
    )

    assert entry["state"] == "execution_error"
    assert entry["container_tail"] == "traceback"
    assert entry["trajectory_file"] is None
    assert entry["error"] == "container never started"


def fake_episode(calls: list, passing):
    def run_episode(gym, recorder, episode_id, task, harness, *, attempt=1):
        calls.append((task, attempt))
        passed = passing(task, attempt)
        return {
            "episode_id": episode_id,
            "suite": SUITE,
            "task": task,
            "attempt": attempt,
            "state": "scored_pass" if passed else "scored_fail",
            "pass": passed,
            "provider_calls": 3,
            "max_prompt_tokens": 1000,
            "seconds": 1.0,
            "error": None,
        }

    return run_episode


def test_collect_resumes_and_stops_after_a_pass(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_ROOT", settings.RUNS_ROOT)
    backend = FakeBackend()
    first, second = Gym(SUITE, backend).tasks("train")[:2]
    calls: list = []
    monkeypatch.setattr(
        episode,
        "run_episode",
        fake_episode(calls, lambda task, attempt: task == first or attempt == 2),
    )
    lines: list[str] = []
    kwargs = {
        "tasks": [first, second],
        "attempts": 2,
        "workers": 1,
        "backend": backend,
        "upstream": "http://gateway",
        "log": lines.append,
    }
    summary = run.collect(tmp_path, [SUITE], **kwargs)

    assert calls == [(first, 1), (second, 1), (second, 2)]
    assert (summary["episodes"], summary["tasks_passed"]) == (3, 2)
    assert summary["by_state"]["scored_fail"] == 1
    assert summary["pass_rate"] == 1.0
    assert (tmp_path / "reports" / SUITE / second / "2.json").is_file()
    assert (tmp_path / "summary.json").is_file()
    frozen = json.loads((tmp_path / "run.json").read_text())
    assert frozen["max_turns"] == 60 and frozen["agent"] == "acp:markov"
    assert any(f"{SUITE}/{second} #1: scored_fail" in line for line in lines)
    assert settings.RUNS_DIR == tmp_path / "runs" / SUITE

    calls.clear()
    summary = run.collect(tmp_path, [SUITE], **kwargs)
    assert calls == []
    assert summary["episodes"] == 3


def test_collect_records_a_crashed_attempt_and_goes_on(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_ROOT", settings.RUNS_ROOT)
    backend = FakeBackend()
    first, second = Gym(SUITE, backend).tasks("train")[:2]
    calls: list = []
    passing = fake_episode(calls, lambda task, attempt: task == second or attempt == 2)

    def run_episode(gym, recorder, episode_id, task, harness, *, attempt=1):
        if task == first and attempt == 1:
            calls.append((task, attempt))
            raise RuntimeError("cancel failed")
        return passing(gym, recorder, episode_id, task, harness, attempt=attempt)

    monkeypatch.setattr(episode, "run_episode", run_episode)
    lines: list[str] = []
    summary = run.collect(
        tmp_path,
        [SUITE],
        tasks=[first, second],
        attempts=2,
        workers=1,
        backend=backend,
        upstream="http://gateway",
        log=lines.append,
    )

    assert calls == [(first, 1), (first, 2), (second, 1)]
    crashed = json.loads((tmp_path / "reports" / SUITE / first / "1.json").read_text())
    assert crashed["state"] == "execution_error"
    assert crashed["pass"] is False
    assert crashed["error"] == "RuntimeError: cancel failed"
    assert "RuntimeError: cancel failed" in crashed["host_tail"]
    assert crashed["task_hash"] == Gym(SUITE, backend).task(first).task_hash
    assert summary["by_state"]["execution_error"] == 1
    assert summary["tasks_passed"] == 2
    assert any(f"{SUITE}/{first} #1: execution_error" in line for line in lines)


def test_collect_refuses_a_run_frozen_with_another_harness(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_ROOT", settings.RUNS_ROOT)
    calls: list = []
    monkeypatch.setattr(episode, "run_episode", fake_episode(calls, lambda *_: True))
    common = {
        "limit": 1,
        "workers": 1,
        "backend": FakeBackend(),
        "upstream": "http://gateway",
        "log": lambda _: None,
    }
    run.collect(tmp_path, [SUITE], **common)
    assert len(calls) == 1

    with pytest.raises(SystemExit, match="max_turns differ"):
        run.collect(tmp_path, [SUITE], config=run.RunConfig(max_turns=5), **common)
    run.collect(
        tmp_path, [SUITE], config=run.RunConfig(max_turns=5), force=True, **common
    )
    assert len(calls) == 1
    assert json.loads((tmp_path / "run.json").read_text())["max_turns"] == 5


def test_select():
    assert run.select(["a", "b", "c"], None, 2) == ["a", "b"]
    assert run.select(["a", "b", "c"], ["c", "a"], None) == ["a", "c"]
    with pytest.raises(SystemExit, match="outside the selection: nope"):
        run.select(["a", "b"], ["nope"], None)


def test_describe_marks_a_pass_that_ended_early():
    entry = {
        "suite": SUITE,
        "task": "area",
        "attempt": 2,
        "state": "budget_exhausted",
        "pass": True,
        "provider_calls": 7,
        "max_prompt_tokens": 30000,
        "seconds": 12.0,
    }
    assert run.describe(entry).startswith(f"{SUITE}/area #2: budget_exhausted (pass)")

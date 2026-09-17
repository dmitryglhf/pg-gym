import json
import subprocess
import sys
from pathlib import Path

import pytest

from postgres_gym import settings, worker

SUITE = "sql-function-set"


def test_parser_defaults():
    args = worker.build_parser().parse_args(["area", "--suite", SUITE])

    assert (args.task, args.suite) == ("area", SUITE)
    assert (args.agent, args.level, args.judge) == ("cli:markov", "L0", False)
    assert args.judge_model is None


def fake_runner(monkeypatch, seen: dict, record: dict) -> None:
    def guarded(suite, name, agent, **kwargs):
        seen.update(suite=suite.id, name=name, agent=agent, kwargs=kwargs)
        return record

    monkeypatch.setattr(settings, "REQUIRE_LANGFUSE", False)
    monkeypatch.setattr(worker.runner, "guarded", guarded)
    monkeypatch.setattr(
        worker.records,
        "save",
        lambda record, task, agent, level: seen.update(saved=(task, agent, level)),
    )


def test_run_scores_the_task_and_saves_the_record(monkeypatch):
    seen: dict = {}
    fake_runner(monkeypatch, seen, {"pass": True, "agent_meta": {"tail": "x"}})
    args = worker.build_parser().parse_args(
        ["area", "--suite", SUITE, "--agent", "noop"]
    )
    record = worker.run(args)

    assert record["pass"]
    assert (seen["suite"], seen["name"], seen["agent"]) == (SUITE, "area", "noop")
    assert seen["kwargs"] == {
        "judge": False,
        "judge_model": None,
        "judge_base_url": None,
    }
    assert seen["saved"] == ("area", "noop", "L0")


def test_external_agents_receive_the_level(monkeypatch):
    seen: dict = {}
    fake_runner(monkeypatch, seen, {"pass": False})
    monkeypatch.setattr(settings, "REQUIRE_MARKOV_KEY", False)
    monkeypatch.setattr(settings, "DISPOSABLE_GIT", True)
    args = worker.build_parser().parse_args(
        ["area", "--suite", SUITE, "--agent", "acp:markov", "--level", "L1", "--judge"]
    )
    worker.run(args)

    assert seen["kwargs"]["level"] == "L1"
    assert seen["kwargs"]["judge"] is True
    assert seen["saved"] == ("area", "acp:markov", "L1")


def test_main_prints_the_public_record_and_fails_on_error(monkeypatch, capsys):
    fake_runner(
        monkeypatch, {}, {"pass": False, "error": "boom", "agent_meta": {"secret": 1}}
    )
    with pytest.raises(SystemExit) as raised:
        worker.main(["area", "--suite", SUITE, "--agent", "noop"])

    assert raised.value.code == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["error"] == "boom"
    assert "agent_meta" not in printed


def test_worker_imports_without_the_platform_dependencies():
    code = (
        "import sys\n"
        "for name in ('typer', 'fastapi', 'httpx2', 'markov_sdk', 'rich'):\n"
        "    sys.modules[name] = None\n"
        "import postgres_gym.worker\n"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_gym import FakeBackend
from typer.testing import CliRunner

from postgres_gym.cli import app
from postgres_gym.gym import Gym

GROUPS = [
    "benchmark",
    "dev",
    "platform",
    "jobs",
    "context",
    "auth",
    "suites",
    "tasks",
    "models",
    "artifacts",
    "inference",
    "rl",
    "server",
    "connections",
    "credentials",
    "profiles",
]


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setenv("PG_GYM_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("PG_GYM_URL", raising=False)
    monkeypatch.delenv("PG_GYM_TOKEN", raising=False)
    return CliRunner()


def error(result) -> dict:
    return json.loads(result.stderr.strip().splitlines()[-1])["error"]


@pytest.mark.parametrize("group", GROUPS)
def test_every_group_has_help(cli, group):
    result = cli.invoke(app, [group, "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage: pg-gym " + group in result.stdout


def test_version_and_root_help(cli):
    assert cli.invoke(app, ["--version"]).stdout.startswith("pg-gym ")
    assert "Usage: pg-gym" in cli.invoke(app, []).output
    assert "doctor" in cli.invoke(app, ["--help"]).stdout


def test_benchmark_run_exposes_its_options(cli):
    result = cli.invoke(app, ["benchmark", "run", "--help"])

    for option in ("--task", "--split", "--agent", "--level", "--since", "--judge"):
        assert option in result.stdout


def test_benchmark_run_uses_gym_and_reports_json(cli, monkeypatch, tmp_path):
    import postgres_gym

    monkeypatch.setattr(
        postgres_gym, "Gym", lambda suite: Gym(suite, FakeBackend(tmp_path))
    )
    result = cli.invoke(
        app,
        [
            "--json",
            "benchmark",
            "run",
            "sql-function-set",
            "--task",
            "area",
            "--agent",
            "noop",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "suite": "sql-function-set",
        "execution_errors": 0,
    }
    assert "[1/1] area" in result.stderr


def test_benchmark_run_rejects_tasks_outside_the_split(cli, monkeypatch, tmp_path):
    import postgres_gym

    monkeypatch.setattr(
        postgres_gym, "Gym", lambda suite: Gym(suite, FakeBackend(tmp_path))
    )
    result = cli.invoke(
        app, ["benchmark", "run", "sql-function-set", "--task", "no-such-task"]
    )

    assert result.exit_code == 2
    assert "no-such-task" in result.stderr


def test_output_modes(cli):
    cli.invoke(app, ["context", "add", "local", "--url", "http://localhost:9432"])

    as_json = cli.invoke(app, ["--json", "context", "list"])
    assert json.loads(as_json.stdout) == {
        "active": "local",
        "contexts": {"local": {"url": "http://localhost:9432", "authenticated": False}},
    }
    as_table = cli.invoke(app, ["context", "list"])
    assert "Field" in as_table.stdout and "local" in as_table.stdout


def test_missing_context_is_reported_as_json_on_stderr(cli):
    result = cli.invoke(app, ["jobs", "list"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert error(result) == {
        "code": 2,
        "message": "Configure a context or set PG_GYM_URL",
    }


def test_transport_failure_exits_with_code_4(cli, monkeypatch):
    monkeypatch.setenv("PG_GYM_URL", "http://127.0.0.1:1")
    result = cli.invoke(app, ["jobs", "list"])

    assert result.exit_code == 4
    assert error(result)["code"] == 4


def test_invalid_root_options_exit_with_code_2(cli):
    assert cli.invoke(app, ["--timeout", "nan", "doctor"]).exit_code == 2
    assert cli.invoke(app, ["--json", "--jsonl", "doctor"]).exit_code == 2
    assert cli.invoke(app, ["--wait-timeout", "0", "doctor"]).exit_code == 2


def test_cli_import_stays_on_base_dependencies():
    script = (
        "import sys, postgres_gym.cli; "
        "print(sorted(m for m in ('pydantic', 'fastapi', 'psutil', 'yaml') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.stdout.strip() == "[]"

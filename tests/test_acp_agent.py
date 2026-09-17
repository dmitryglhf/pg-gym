import json
import os
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core import acp_agent
from postgres_gym.core.acp_agent import AcpAgent

SERVE_AND_FINISH = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "markov 0.0-test"; exit 0; fi
echo "fake $@"
printf '{"session_id": "s1", "stop_reason": "end_turn"}' > "$POSTGRES_GYM_ACP_DIR/agent.json"
: > "$POSTGRES_GYM_ACP_DIR/done"
exec sleep 30
"""
SERVE_FOREVER = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "markov 0.0-test"; exit 0; fi
exec sleep 30
"""
EXIT_EARLY = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "markov 0.0-test"; exit 0; fi
echo "cannot bind"
exit 3
"""


def install(tmp_path: Path, monkeypatch, script: str | None) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if script is not None:
        markov = bin_dir / "markov"
        markov.write_text(script)
        markov.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
    monkeypatch.setattr(settings, "PG_SRC", tmp_path)
    exchange = tmp_path / "acp"
    monkeypatch.setenv("POSTGRES_GYM_ACP_DIR", str(exchange))
    return exchange


def test_run_waits_for_done_and_merges_the_host_outcome(tmp_path: Path, monkeypatch):
    exchange = install(tmp_path, monkeypatch, SERVE_AND_FINISH)
    meta = AcpAgent(timeout=10).run({}, {}, suite=None, stand=None)

    assert (meta["profile"], meta["transport"], meta["level"]) == (
        "markov",
        "acp",
        "L0",
    )
    assert meta["session_id"] == "s1" and meta["stop_reason"] == "end_turn"
    assert "error" not in meta
    assert meta["timed_out"] is False
    assert "0.0-test" in meta["agent_version"]
    assert f"fake serve --host 0.0.0.0 --port {acp_agent.DEFAULT_PORT}" in meta["tail"]
    assert (exchange / acp_agent.LOG).is_file()


def test_run_reports_a_server_that_exited_early(tmp_path: Path, monkeypatch):
    install(tmp_path, monkeypatch, EXIT_EARLY)
    meta = AcpAgent(timeout=10).run({}, {}, suite=None, stand=None)

    assert meta["error"] == "markov serve exited before the episode finished"
    assert meta["returncode"] == 3
    assert "cannot bind" in meta["tail"]


def test_run_times_out_without_done(tmp_path: Path, monkeypatch):
    install(tmp_path, monkeypatch, SERVE_FOREVER)
    meta = AcpAgent(timeout=1).run({}, {}, suite=None, stand=None)

    assert meta["timed_out"] is True
    assert "error" not in meta
    assert meta["seconds"] < 10


def test_run_without_markov_on_path(tmp_path: Path, monkeypatch):
    install(tmp_path, monkeypatch, None)
    meta = AcpAgent(timeout=1).run({}, {}, suite=None, stand=None)

    assert meta == {"error": "markov not on PATH", "profile": "markov"}


def test_exchange_dir_defaults_to_work(monkeypatch):
    monkeypatch.delenv("POSTGRES_GYM_ACP_DIR", raising=False)
    assert acp_agent.exchange_dir() == Path("/work/acp")
    assert json.dumps({"done": acp_agent.DONE}) == '{"done": "done"}'

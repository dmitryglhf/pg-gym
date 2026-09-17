from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core.agents import Agent
from postgres_gym.core.cli_agent import _SCRUBBED, agent_version

DEFAULT_PORT = 3284
DONE = "done"
RESULT = "agent.json"
LOG = "serve.log"


def exchange_dir() -> Path:
    return Path(os.environ.get("POSTGRES_GYM_ACP_DIR", "/work/acp"))


class AcpAgent(Agent):
    """Serves markov over ACP and lets a client outside the container run the episode.

    The container publishes the port, the host drives the session through
    markov-sdk, writes its outcome to `agent.json` and touches `done`. Nothing
    here talks to the model; the prompt is sent by the host from the same suite
    data, so the record keeps the usual shape.
    """

    name = "acp:markov"

    def __init__(
        self,
        level: str = "L0",
        timeout: int | None = None,
        extra_env: dict | None = None,
    ):
        self.level = level
        self.timeout = timeout or settings.AGENT_TIMEOUT
        self.extra_env = extra_env or {}

    def run(self, task: dict, oracle: dict, *, suite, stand) -> dict:
        directory = exchange_dir()
        directory.mkdir(parents=True, exist_ok=True)
        done, result, log_path = (directory / n for n in (DONE, RESULT, LOG))
        port = os.environ.get("POSTGRES_GYM_ACP_PORT", str(DEFAULT_PORT))
        env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED}
        env.update(self.extra_env)
        argv = ["markov", "serve", "--host", "0.0.0.0", "--port", port]
        started = time.time()
        timed_out = False
        with log_path.open("ab") as log:
            try:
                proc = subprocess.Popen(
                    argv,
                    cwd=settings.PG_SRC,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except FileNotFoundError:
                return {"error": "markov not on PATH", "profile": "markov"}
            try:
                while not done.exists() and proc.poll() is None:
                    if time.time() - started > self.timeout:
                        timed_out = True
                        break
                    time.sleep(0.5)
            finally:
                _stop(proc)

        meta = {
            "profile": "markov",
            "transport": "acp",
            "level": self.level,
            "provider": settings.AGENT_PROVIDER,
            "model": settings.AGENT_MODEL,
            "agent_version": agent_version("markov"),
            "returncode": proc.returncode,
            "timed_out": timed_out,
            "seconds": round(time.time() - started, 1),
            "tail": log_path.read_text(encoding="utf-8", errors="replace")[-6000:],
        }
        if not done.exists() and not timed_out:
            meta["error"] = "markov serve exited before the episode finished"
        if result.is_file():
            meta.update(json.loads(result.read_text(encoding="utf-8")))
        return meta


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()

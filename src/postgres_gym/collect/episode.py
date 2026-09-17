from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import httpx2

from postgres_gym import settings
from postgres_gym.collect.journal import Recorder, Turns
from postgres_gym.core import acp_agent
from postgres_gym.execution.docker import DockerBackend
from postgres_gym.gym import EpisodeResult, Gym

AGENT = "acp:markov"
LABEL = "pg-gym.episode"
CWD = "/bench/pg"
TOOLS = ("edit", "read_image", "shell", "tree", "write")
MAX_TURNS_MESSAGE = (
    "I've reached the maximum number of actions I can do without user input."
)
STATES = (
    "scored_pass",
    "scored_fail",
    "budget_exhausted",
    "max_turns",
    "agent_timeout",
    "provider_error",
    "execution_error",
    "no_trajectory",
)


@dataclass(frozen=True)
class Harness:
    """What the teacher runs with. Frozen into run.json and every report."""

    model: str
    max_turns: int
    token_budget: int | None
    agent_timeout: int
    secret: str

    def environment(self, provider_host: str) -> dict[str, str]:
        return {
            "GOOSE_PROVIDER": "pgpro",
            "GOOSE_MODEL": self.model,
            "GOOSE_MODE": "auto",
            "GOOSE_MAX_TURNS": str(self.max_turns),
            "GOOSE_DISABLE_SESSION_NAMING": "true",
            "GOOSE_TOOL_PAIR_SUMMARIZATION": "false",
            "GOOSE_RANDOM_THINKING_MESSAGES": "false",
            "GOOSE_SERVER__SECRET_KEY": self.secret,
            "PGPRO_HOST": provider_host,
            "POSTGRES_GYM_AGENT_TIMEOUT": str(self.agent_timeout),
        }


def run_episode(
    gym: Gym,
    recorder: Recorder,
    episode_id: str,
    task: str,
    harness: Harness,
    *,
    attempt: int = 1,
) -> dict:
    """One scored episode: the container grades, this process drives markov."""
    spec = gym.task(task)
    request = replace(
        gym.request(
            task, AGENT, environment=harness.environment(recorder.url(episode_id))
        ),
        ports=(acp_agent.DEFAULT_PORT,),
        labels={LABEL: episode_id},
    )
    backend = gym.backend
    if not isinstance(backend, DockerBackend):
        raise TypeError("ACP episodes need the docker backend")
    started = time.time()
    with ThreadPoolExecutor(1, thread_name_prefix="pg-gym-episode") as pool:
        future = pool.submit(gym.execute, request)
        outcome = drive(backend, future, episode_id, spec.prompt, harness)
        result = future.result()
    return report(
        result,
        outcome,
        recorder.turns(episode_id),
        harness,
        episode_id=episode_id,
        attempt=attempt,
        task_hash=spec.task_hash,
        trajectory=recorder.path(episode_id),
        seconds=time.time() - started,
    )


def drive(
    backend: DockerBackend,
    future: Future[EpisodeResult],
    episode_id: str,
    prompt: str,
    harness: Harness,
) -> dict:
    """Wait for the container to serve ACP, run the turn, hand the outcome back."""
    container = _wait_for(
        lambda: _first(backend.containers(f"{LABEL}={episode_id}")), future
    )
    if container is None:
        return {"error": "container never started"}
    port = _wait_for(
        lambda: backend.published_port(container, acp_agent.DEFAULT_PORT), future
    )
    if port is None:
        return {"error": "container exposed no ACP port"}
    url = f"http://127.0.0.1:{port}"
    if not _wait_for(lambda: _healthy(url) or None, future, settings.CONTAINER_TIMEOUT):
        return {"error": "markov serve never became healthy"}

    outcome = converse(url, prompt, harness)
    exchange = acp_agent.exchange_dir()
    try:
        backend.write(
            container, str(exchange / acp_agent.RESULT), json.dumps(outcome).encode()
        )
        backend.write(container, str(exchange / acp_agent.DONE), b"")
    except RuntimeError as exc:
        outcome.setdefault("error", f"could not signal the container: {exc}")
    return outcome


def converse(url: str, prompt: str, harness: Harness) -> dict:
    """The markov-sdk part: one session, one turn, events counted along the way."""
    from markov_sdk import (
        Agent,
        Builtin,
        MarkovError,
        MessageUsage,
        Server,
        ToolCallStarted,
    )

    outcome: dict = {
        "provider_calls": 0,
        "tool_calls": 0,
        "max_prompt_tokens": 0,
        "timed_out": False,
    }
    server = Server.remote(url, secret_key=harness.secret)
    agent = Agent(
        f"pgpro:{harness.model}",
        server=server,
        cwd=CWD,
        mode="auto",
        plugins=[Builtin("developer")],
        timeout=harness.agent_timeout,
    )
    started = time.time()
    try:
        with agent:
            chat = agent.open_session_sync()
            outcome["session_id"] = chat.id
            outcome["tools"] = sorted(t.name for t in agent.loop.run(chat.tools()))
            stream = chat.stream_sync(prompt)
            for event in stream:
                if isinstance(event, MessageUsage):
                    outcome["provider_calls"] += 1
                    outcome["max_prompt_tokens"] = max(
                        outcome["max_prompt_tokens"], event.input_tokens or 0
                    )
                elif isinstance(event, ToolCallStarted):
                    outcome["tool_calls"] += 1
            result = stream.result
            outcome.update(
                stop_reason=result.stop_reason,
                usage=result.usage.model_dump(),
                text_tail=result.text[-2000:],
                max_turns_message=MAX_TURNS_MESSAGE in result.text,
            )
            agent.loop.run(chat.close())
    except TimeoutError:
        outcome["timed_out"] = True
    except MarkovError as exc:
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    outcome["agent_seconds"] = round(time.time() - started, 1)
    return outcome


def classify(result: EpisodeResult, outcome: dict, turns: Turns, max_turns: int) -> str:
    record = result.record or {}
    meta = record.get("agent_meta") or {}
    if not result.execution.ok or not record or record.get("error"):
        return "execution_error"
    if turns.calls == 0 and turns.errors == 0:
        return "no_trajectory"
    if outcome.get("timed_out") or meta.get("timed_out"):
        return "agent_timeout"
    if turns.exhausted:
        return "budget_exhausted"
    if outcome.get("max_turns_message") or turns.calls >= max_turns:
        return "max_turns"
    if turns.errors or outcome.get("error"):
        return "provider_error"
    return "scored_pass" if record.get("pass") else "scored_fail"


def report(
    result: EpisodeResult,
    outcome: dict,
    turns: Turns,
    harness: Harness,
    *,
    episode_id: str,
    attempt: int,
    task_hash: str,
    trajectory: Path,
    seconds: float,
) -> dict:
    record = result.record or {}
    execution = record.get("execution") or {}
    entry = {
        "episode_id": episode_id,
        "suite": result.suite,
        "task": result.task,
        "task_hash": task_hash,
        "attempt": attempt,
        "model": harness.model,
        "image_id": execution.get("image_id", ""),
        "max_turns": harness.max_turns,
        "token_budget": harness.token_budget,
        "state": classify(result, outcome, turns, harness.max_turns),
        "pass": bool(record.get("pass")),
        "reward": record.get("reward"),
        "seconds": round(seconds, 1),
        "agent_seconds": outcome.get("agent_seconds"),
        "provider_calls": turns.calls,
        "provider_errors": turns.errors,
        "tool_calls": outcome.get("tool_calls"),
        "max_prompt_tokens": turns.max_prompt_tokens,
        "usage": outcome.get("usage"),
        "stop_reason": outcome.get("stop_reason"),
        "session_id": outcome.get("session_id"),
        "tools": outcome.get("tools"),
        "trajectory_file": trajectory.name if trajectory.is_file() else None,
        "record_file": str(result.execution.records[-1])
        if result.execution.records
        else None,
        "error": record.get("error") or outcome.get("error"),
    }
    if not result.execution.ok:
        tail = (result.execution.stderr or result.execution.stdout)[-4000:]
        entry["container_tail"] = tail
    return entry


def _wait_for(
    probe, future: Future, timeout: float | None = None, interval: float = 1.0
):
    deadline = time.monotonic() + (timeout or settings.CONTAINER_TIMEOUT)
    while time.monotonic() < deadline:
        found = probe()
        if found is not None:
            return found
        if future.done():
            return None
        time.sleep(interval)
    return None


def _first(items: list[str]) -> str | None:
    return items[0] if items else None


def _healthy(url: str) -> bool:
    try:
        return httpx2.get(f"{url}/health", timeout=2.0).status_code == 200
    except httpx2.HTTPError:
        return False

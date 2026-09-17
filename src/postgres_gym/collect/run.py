from __future__ import annotations

import json
import secrets
import sys
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_gym import settings
from postgres_gym.collect import episode
from postgres_gym.collect.journal import Recorder
from postgres_gym.execution.base import ExecutionBackend
from postgres_gym.execution.docker import DockerBackend
from postgres_gym.gym import Gym

RUN_FILE = "run.json"
SUMMARY_FILE = "summary.json"
DEFAULT_MODEL = "DeepSeek-V4-Flash-0731"
DEFAULT_SUITES = ("sql-function-set", "commit")


@dataclass(frozen=True)
class RunConfig:
    model: str = DEFAULT_MODEL
    image: str = settings.TASK_IMAGE
    max_turns: int = 60
    token_budget: int | None = 28000
    agent_timeout: int = 1800

    def frozen(self, image_id: str) -> dict:
        return {
            "agent": episode.AGENT,
            "model": self.model,
            "image": self.image,
            "image_id": image_id,
            "tools": list(episode.TOOLS),
            "max_turns": self.max_turns,
            "token_budget": self.token_budget,
        }


def collect(
    run_dir: Path,
    suites: list[str] | None = None,
    *,
    split: str | None = "train",
    tasks: list[str] | None = None,
    limit: int | None = None,
    config: RunConfig | None = None,
    attempts: int = 1,
    workers: int = 2,
    upstream: str | None = None,
    force: bool = False,
    backend: ExecutionBackend | None = None,
    log: Callable[[str], None] = lambda line: print(line, file=sys.stderr, flush=True),
) -> dict:
    """Run the teacher over the selected tasks, resuming a run directory.

    A task is skipped when a passing report exists or all attempts were used.
    `run.json` freezes the harness; a second call with a different one refuses
    to mix episodes unless `force` is given.
    """
    config = config or RunConfig()
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    backend = backend or DockerBackend(image=config.image)
    freeze(run_dir, config.frozen(getattr(backend, "image_id", lambda: "")()), force)
    settings.RUNS_ROOT = run_dir / "runs"
    harness = episode.Harness(
        model=config.model,
        max_turns=config.max_turns,
        token_budget=config.token_budget,
        agent_timeout=config.agent_timeout,
        secret=secrets.token_urlsafe(32),
    )
    lock = threading.Lock()
    with Recorder(
        run_dir / "trajectories", upstream, budget=config.token_budget
    ) as recorder:
        for suite in suites or DEFAULT_SUITES:
            settings.use_suite(suite)
            gym = Gym(suite, backend)
            names = select(gym.tasks(split), tasks, limit)
            pending = [n for n in names if attempts_left(run_dir, suite, n, attempts)]
            log(f"{suite}: {len(pending)} of {len(names)} tasks to run")

            def work(name: str, gym: Gym = gym, suite: str = suite) -> None:
                for attempt in range(
                    done_attempts(run_dir, suite, name) + 1, attempts + 1
                ):
                    result = episode.run_episode(
                        gym, recorder, new_episode_id(), name, harness, attempt=attempt
                    )
                    with lock:
                        save_report(run_dir, result)
                        log(describe(result))
                    if result["pass"]:
                        return

            with ThreadPoolExecutor(
                max(1, workers), thread_name_prefix="pg-gym-collect"
            ) as pool:
                list(pool.map(work, pending))
    summary = summarize(run_dir)
    (run_dir / SUMMARY_FILE).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def freeze(run_dir: Path, frozen: dict, force: bool) -> None:
    path = run_dir / RUN_FILE
    created = datetime.now(UTC).isoformat(timespec="seconds")
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        created = previous.pop("created", created)
        if previous != frozen and not force:
            changed = sorted(
                k
                for k in set(previous) | set(frozen)
                if previous.get(k) != frozen.get(k)
            )
            raise SystemExit(
                f"{path} was frozen with a different harness ({', '.join(changed)} differ); "
                "use another --run directory or pass --force"
            )
    frozen = {**frozen, "created": created}
    path.write_text(json.dumps(frozen, indent=2), encoding="utf-8")


def select(names: list[str], tasks: list[str] | None, limit: int | None) -> list[str]:
    if tasks:
        unknown = sorted(set(tasks) - set(names))
        if unknown:
            raise SystemExit("tasks outside the selection: " + ", ".join(unknown))
        names = [n for n in names if n in set(tasks)]
    return names[:limit] if limit else names


def new_episode_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def reports_dir(run_dir: Path, suite: str, task: str) -> Path:
    return run_dir / "reports" / suite / task


def reports(run_dir: Path, suite: str, task: str) -> list[dict]:
    directory = reports_dir(run_dir, suite, task)
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def done_attempts(run_dir: Path, suite: str, task: str) -> int:
    return len(reports(run_dir, suite, task))


def attempts_left(run_dir: Path, suite: str, task: str, attempts: int) -> bool:
    previous = reports(run_dir, suite, task)
    if any(r.get("pass") for r in previous):
        return False
    return len(previous) < attempts


def save_report(run_dir: Path, result: dict) -> Path:
    directory = reports_dir(run_dir, result["suite"], result["task"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result['attempt']}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def describe(result: dict) -> str:
    outcome = result["state"]
    if result["pass"] and not outcome.startswith("scored"):
        outcome += " (pass)"
    return (
        f"{result['suite']}/{result['task']} #{result['attempt']}: {outcome}"
        f" · {result['provider_calls']} calls"
        f" · {result['max_prompt_tokens']} max prompt tokens"
        f" · {result['seconds']}s"
        + (f" · {result['error']}" if result.get("error") else "")
    )


def all_reports(run_dir: Path) -> list[dict]:
    root = Path(run_dir) / "reports"
    if not root.is_dir():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.rglob("*.json"))
    ]


def summarize(run_dir: Path) -> dict:
    """Counts by state, pass rate and the spread of calls and prompt sizes."""
    entries = all_reports(run_dir)
    by_state = {state: 0 for state in episode.STATES}
    by_suite: dict[str, dict] = {}
    for entry in entries:
        by_state[entry["state"]] = by_state.get(entry["state"], 0) + 1
        suite = by_suite.setdefault(
            entry["suite"], {"episodes": 0, "passed": 0, "tasks": set()}
        )
        suite["episodes"] += 1
        suite["passed"] += int(entry["pass"])
        suite["tasks"].add(entry["task"])
    for suite in by_suite.values():
        suite["tasks"] = len(suite["tasks"])
    passed_tasks = {(e["suite"], e["task"]) for e in entries if e["pass"]}
    tasks = {(e["suite"], e["task"]) for e in entries}
    return {
        "episodes": len(entries),
        "tasks": len(tasks),
        "tasks_passed": len(passed_tasks),
        "pass_rate": round(len(passed_tasks) / len(tasks), 3) if tasks else None,
        "by_state": by_state,
        "by_suite": by_suite,
        "provider_calls": percentiles([e["provider_calls"] for e in entries]),
        "max_prompt_tokens": percentiles([e["max_prompt_tokens"] for e in entries]),
        "failed_tasks": sorted(f"{s}/{t}" for s, t in tasks - passed_tasks),
    }


def percentiles(values: list[int]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)

    def at(fraction: float) -> int:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    return {"min": ordered[0], "p50": at(0.5), "p90": at(0.9), "max": ordered[-1]}

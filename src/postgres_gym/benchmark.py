from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core import records
from postgres_gym.gym import Gym


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def run(
    gym: Gym,
    agent: str,
    level: str,
    *,
    tasks: list[str] | None = None,
    split: str | None = None,
    since: str | None = None,
    judge: bool = False,
    judge_model: str | None = None,
    judge_base_url: str | None = None,
) -> int:
    names = tasks or gym.tasks(split)
    if tasks and split:
        allowed = set(gym.tasks(split))
        names = [name for name in tasks if name in allowed]
    if not names:
        raise SystemExit("no runnable tasks")

    started = stamp()
    print(
        f"bench {started}  suite={gym.suite.id}  tasks={len(names)}  "
        f"agent={agent}  backend={gym.backend.name}",
        flush=True,
    )

    broken = 0
    done = records.done_since(agent, level, since) if since else set()
    for position, name in enumerate(names, 1):
        if name in done:
            print(f"[{position}/{len(names)}] {name}  skipped", flush=True)
            continue

        print(f"[{position}/{len(names)}] {name}", flush=True)
        result = gym.run(
            name,
            agent,
            level=level,
            judge=judge,
            judge_model=judge_model,
            judge_base_url=judge_base_url,
        )
        if result.ok:
            reward = result.reward
            suffix = f"  reward={reward:g}" if reward is not None else ""
            print(f"    ok{suffix}", flush=True)
            continue

        broken += 1
        _write_backend_log(name, result.execution.stdout, result.execution.stderr)
        reason = (
            "worker failed" if result.execution.returncode else "worker wrote no record"
        )
        print(f"    {reason}", flush=True)
        for line in (
            (result.execution.stdout + result.execution.stderr)
            .strip()
            .splitlines()[-10:]
        ):
            print(f"    | {line}", flush=True)

    print(f"bench done  broken={broken}", flush=True)
    return broken


def _write_backend_log(task: str, stdout: str, stderr: str) -> Path:
    directory = settings.RUNS_DIR / "backend-errors"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task}-{stamp()}.log"
    path.write_text(stdout + stderr, encoding="utf-8")
    return path

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from postgres_gym import settings

NOT_RESULTS = frozenset({"invalidated", ".out"})


def iter_records(pattern: str = "*.json"):
    for path in settings.RUNS_DIR.rglob(pattern):
        if NOT_RESULTS.intersection(path.relative_to(settings.RUNS_DIR).parts[:-1]):
            continue
        yield path


def slug(agent: str) -> str:
    return agent.replace(":", "-")


def stem(func: str, agent: str, level: str, stamp: str | None = None) -> str:
    stamp = stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{func}-{slug(agent)}-{level}-{stamp}"


def save(record: dict, func: str, agent: str, level: str) -> Path:
    directory = settings.RUNS_DIR
    model = ((record.get("agent_meta") or {}).get("model") or "").rsplit("/", 1)[-1]
    if model:
        directory = directory / model
    directory.mkdir(parents=True, exist_ok=True)
    name = stem(func, agent, level)

    diff_text = record.pop("diff", "") or ""
    if diff_text.strip():
        (directory / f"{name}.diff").write_text(diff_text, encoding="utf-8")
        record["diff_file"] = f"{name}.diff"

    path = directory / f"{name}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def done_since(agent: str, level: str, since: str | None = None) -> set[str]:
    suffix = f"-{slug(agent)}-{level}-"
    done = set()
    for path in iter_records(f"*{suffix}*.json"):
        func, _, stamp = path.stem.rpartition(suffix)
        if since and stamp < since:
            continue
        done.add(func)
    return done

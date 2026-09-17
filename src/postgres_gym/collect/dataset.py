from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_gym import settings
from postgres_gym.collect import journal
from postgres_gym.collect.episode import TOOLS
from postgres_gym.collect.run import RUN_FILE, all_reports
from postgres_gym.core import registry

FORMAT = "agent-target-v1"
FINISH_REASONS = frozenset({"stop", "tool_calls"})


@dataclass(frozen=True)
class Rejection:
    episode_id: str
    reason: str


def build(
    runs: list[Path],
    out: Path,
    *,
    dev_fraction: float = 0.1,
    seed: int = 0,
) -> dict:
    """Turn passing episodes into one training row per assistant turn.

    `prompt` is the message list exactly as markov sent it, `completion` the
    assistant message the teacher answered with, `tools` the schemas of that
    request. Dev holds whole task groups so no task leaks between splits.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    rejected: list[Rejection] = []
    seen = 0
    for run_dir in runs:
        run_dir = Path(run_dir)
        for entry in all_reports(run_dir):
            if not entry.get("pass"):
                continue
            seen += 1
            trajectory = entry.get("trajectory_file")
            path = run_dir / "trajectories" / trajectory if trajectory else None
            if path is None or not path.is_file():
                rejected.append(Rejection(entry["episode_id"], "no_trajectory"))
                continue
            try:
                rows += episode_rows(entry, journal.read(path), sha256(path))
            except ValueError as exc:
                rejected.append(Rejection(entry["episode_id"], str(exc)))

    dev_groups = pick_dev(rows, dev_fraction, seed)
    train = [r for r in rows if r["metadata"]["group"] not in dev_groups]
    dev = [r for r in rows if r["metadata"]["group"] in dev_groups]
    for row in rows:
        row["metadata"]["split"] = (
            "dev" if row["metadata"]["group"] in dev_groups else "train"
        )
    write_jsonl(out / "train.jsonl", train)
    write_jsonl(out / "dev.jsonl", dev)
    write_jsonl(out / "rejected.jsonl", [r.__dict__ for r in rejected])
    manifest = {
        "format": FORMAT,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "runs": [str(Path(r).resolve()) for r in runs],
        "harness": [
            read_json(Path(r) / RUN_FILE)
            for r in runs
            if (Path(r) / RUN_FILE).is_file()
        ],
        "episodes": {
            "passing": seen,
            "accepted": len({r["metadata"]["episode_id"] for r in rows}),
            "rejected": len(rejected),
        },
        "rows": {"train": len(train), "dev": len(dev)},
        "tasks": {
            "train": len({r["metadata"]["group"] for r in train}),
            "dev": len(dev_groups),
        },
        "by_suite": counts(rows, "suite"),
        "by_state": counts(rows, "state"),
        "prompt_tokens": spread(
            [
                r["metadata"]["prompt_tokens"]
                for r in rows
                if r["metadata"].get("prompt_tokens")
            ]
        ),
        "files": {
            name: sha256(out / name)
            for name in ("train.jsonl", "dev.jsonl", "rejected.jsonl")
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def episode_rows(entry: dict, lines: list[dict], digest: str) -> list[dict]:
    """Every completed model call of one episode as a training row."""
    if not lines:
        raise ValueError("empty_trajectory")
    completed = [line for line in lines if not line.get("error")]
    if not completed:
        raise ValueError("no_completed_calls")
    if [line["turn"] for line in lines] != list(range(len(lines))):
        raise ValueError("turn_gap")
    if any(line.get("error") for line in lines[: len(completed)]):
        raise ValueError("error_before_last_call")
    rows = []
    for line in completed:
        request, response = line["request"], line["response"]
        if not request or not request.get("messages"):
            raise ValueError("empty_request")
        names = sorted(tool["function"]["name"] for tool in request.get("tools") or [])
        if names != sorted(TOOLS):
            raise ValueError("unexpected_tools:" + ",".join(names))
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("role") != "assistant":
            raise ValueError("no_assistant_message")
        if choice.get("finish_reason") not in FINISH_REASONS:
            raise ValueError("finish_reason:" + str(choice.get("finish_reason")))
        for call in message.get("tool_calls") or []:
            name = call.get("function", {}).get("name")
            if name not in TOOLS:
                raise ValueError("unknown_tool_call:" + str(name))
            try:
                json.loads(call["function"].get("arguments") or "")
            except (TypeError, ValueError):
                raise ValueError("tool_arguments_not_json") from None
        usage = line.get("usage") or {}
        rows.append(
            {
                "format": FORMAT,
                "prompt": request["messages"],
                "completion": [message],
                "tools": request["tools"],
                "metadata": {
                    "episode_id": entry["episode_id"],
                    "suite": entry["suite"],
                    "task": entry["task"],
                    "task_hash": entry.get("task_hash"),
                    "group": group_key(entry["suite"], entry["task"]),
                    "state": entry["state"],
                    "turn": line["turn"],
                    "turns": len(completed),
                    "finish_reason": choice.get("finish_reason"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "source_model": entry["model"],
                    "trajectory_sha256": digest,
                },
            }
        )
    return rows


_GROUPS: dict[tuple[str, str], str] = {}


def group_key(suite: str, task: str) -> str:
    """Tasks cut from one upstream commit stay on the same side of the split."""
    if (suite, task) not in _GROUPS:
        key = f"{suite}:{task}"
        try:
            settings.use_suite(suite)
            _, oracle = registry.load(suite).load(task)
            if sha := oracle.get("sha"):
                key = f"{suite}:{sha}"
        except Exception:  # noqa: BLE001
            pass
        _GROUPS[(suite, task)] = key
    return _GROUPS[(suite, task)]


def pick_dev(rows: list[dict], fraction: float, seed: int) -> set[str]:
    groups = sorted({row["metadata"]["group"] for row in rows})
    if not groups or fraction <= 0:
        return set()
    random.Random(seed).shuffle(groups)
    return set(groups[: max(1, math.ceil(len(groups) * fraction))])


def counts(rows: list[dict], key: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for row in rows:
        value = str(row["metadata"].get(key))
        found[value] = found.get(value, 0) + 1
    return dict(sorted(found.items()))


def spread(values: list[int]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": ordered[len(ordered) // 2],
        "p90": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
        "max": ordered[-1],
        "mean": round(sum(ordered) / len(ordered)),
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

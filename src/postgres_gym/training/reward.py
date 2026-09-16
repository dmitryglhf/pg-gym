from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

from postgres_gym import Gym


def completion_text(completion: str | list[dict]) -> str:
    if isinstance(completion, str):
        return completion
    return "".join(str(message.get("content") or "") for message in completion)


def diff_from_completion(completion: str | list[dict]) -> str:
    text = completion_text(completion).replace("\r\n", "\n")
    text = text.rsplit("</think>", 1)[-1]
    fenced = re.finditer(r"^```(?:diff|patch)?[^\S\n]*\n(.*?)^```[^\S\n]*$", text, re.MULTILINE | re.DOTALL)
    for block in fenced:
        if re.search(r"^(?:diff --git |--- [^\n]+\n\+\+\+ )", block.group(1), re.MULTILINE):
            text = block.group(1)
            break
    start = re.search(r"^(?:diff --git |--- [^\n]+\n\+\+\+ )", text, re.MULTILINE)
    if start is None:
        return ""
    text = text[start.start():]
    # Models often emit empty context lines without the required leading space.
    # Normalize them so git can parse otherwise usable unified diffs.
    lines = text.splitlines()
    in_hunk = False
    normalized = []
    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
        if in_hunk and line == "":
            line = " "
        normalized.append(line)
    text = "\n".join(normalized)
    return text if text.endswith("\n") else text + "\n"


def rollout(gym: Gym, task: str, completion: str | list[dict]) -> dict:
    patch = diff_from_completion(completion)
    result = gym.run(task, "patch", completion=patch)
    return {"suite": gym.suite.id, "task": task, "completion": completion_text(completion),
            "patch": patch, "reward": result.reward if result.ok else None,
            "record": result.record, "execution_error": result.execution.stderr}


def applied(rollout_record: dict) -> bool:
    record = rollout_record.get("record") or {}
    return bool((record.get("agent_meta") or {}).get("applied"))


def append_rollout(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def gym_reward(
    *, completions: Sequence[str | list[dict]], suite: Sequence[str], task: Sequence[str],
    audit_path: Path | None = None, **kwargs
) -> list[float | None]:
    gyms = {suite_id: Gym(suite_id) for suite_id in set(suite)}
    rewards = []
    for completion, suite_id, task_id in zip(completions, suite, task, strict=True):
        record = rollout(gyms[suite_id], task_id, completion)
        rewards.append(record["reward"])
        if audit_path is not None:
            append_rollout(audit_path, record)
    return rewards


def audited_reward(output: Path):
    def score(**kwargs):
        return gym_reward(audit_path=output / "rollouts.jsonl", **kwargs)

    return score

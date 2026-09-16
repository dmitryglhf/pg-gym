from __future__ import annotations

import json
import os

from postgres_gym import settings
from postgres_gym.core import data


def build(
    suite, name: str, execution: dict | None = None, completion: str | None = None,
    *, judge: bool = False,
) -> bytes:
    task, oracle = suite.load(name)
    body = {
        "task": task,
        "oracle": oracle,
        "patch": suite.mutation(oracle),
        "task_hash": data.task_hash(suite.data, name),
        "execution": execution or {},
        "completion": completion,
        "secrets": _secrets() if judge else {},
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _secrets() -> dict[str, str]:
    key = os.environ.get(settings.JUDGE_KEY_ENV)
    return {settings.JUDGE_KEY_ENV: key} if key else {}

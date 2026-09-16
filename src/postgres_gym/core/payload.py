from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from postgres_gym import settings

_PAYLOAD: dict | None = None


def payload() -> dict:
    global _PAYLOAD
    if _PAYLOAD is None:
        _PAYLOAD = json.loads(sys.stdin.read())
    return _PAYLOAD


def load(name: str, data: Path) -> tuple[dict, dict]:
    if settings.PAYLOAD_STDIN:
        sent = payload()
        task = sent["task"]
        identity = task.get("func") or task.get("name")
        if identity != name:
            raise SystemExit(f"payload is for {identity!r}, not {name!r}")
        return task, sent["oracle"]
    task = json.loads((data / "tasks" / f"{name}.json").read_text())
    oracle = json.loads((data / "oracle" / f"{name}.json").read_text())
    return task, oracle


def mutation(oracle: dict, data: Path) -> str:
    if settings.PAYLOAD_STDIN:
        return payload()["patch"]
    return (data / oracle["patch"]).read_text(encoding="utf-8", errors="replace")


def metadata() -> dict:
    if not settings.PAYLOAD_STDIN:
        return {}
    sent = payload()
    return {
        "task_hash": sent.get("task_hash"),
        "execution": sent.get("execution") or {},
    }


def completion() -> str:
    if not settings.PAYLOAD_STDIN:
        return ""
    return str(payload().get("completion") or "")


def judge_key() -> str:
    if settings.PAYLOAD_STDIN:
        return payload().get("secrets", {}).get(settings.JUDGE_KEY_ENV, "")
    return os.environ.get(settings.JUDGE_KEY_ENV, "")

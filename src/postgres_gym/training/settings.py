from __future__ import annotations

import os
from pathlib import Path


def text(name: str, default: str) -> str:
    return os.environ.get(name, default) or default


def integer(name: str, default: int) -> int:
    return int(text(name, str(default)))


def decimal(name: str, default: float) -> float:
    return float(text(name, str(default)))


def path(name: str, default: str) -> Path:
    return Path(text(name, default))


def suites() -> tuple[str, ...]:
    value = text("POSTGRES_GYM_TRAIN_SUITES", "sql-function-set,commit")
    result = tuple(part.strip() for part in value.split(",") if part.strip())
    if not result:
        raise ValueError("POSTGRES_GYM_TRAIN_SUITES must name at least one suite")
    return result

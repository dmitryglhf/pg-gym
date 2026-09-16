from __future__ import annotations

from postgres_gym import settings
from postgres_gym.execution.base import ExecutionBackend
from postgres_gym.execution.docker import DockerBackend


def load_backend(name: str | None = None) -> ExecutionBackend:
    backend = name or settings.EXECUTION_BACKEND
    if backend == "docker":
        return DockerBackend()
    raise SystemExit(f"unknown execution backend {backend!r}")

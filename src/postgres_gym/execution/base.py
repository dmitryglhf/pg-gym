from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TaskRequest:
    suite: str
    task: str
    agent: str
    level: str
    payload: bytes
    extra_args: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    returncode: int
    stdout: str
    stderr: str
    records: tuple[Path, ...]
    backend: str
    container_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and bool(self.records)


class ExecutionBackend(Protocol):
    name: str
    scored: bool

    def available(self) -> str | None: ...
    def run(self, request: TaskRequest) -> TaskResult: ...
    def build(self, args: list[str] | None = None) -> int: ...

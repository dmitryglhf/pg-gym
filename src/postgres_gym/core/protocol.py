from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, runtime_checkable

from postgres_gym.core.process import Step


class TestReport(Protocol):
    ok: bool
    seconds: float
    failed: list[str]
    total: int
    output: str
    diff_lines: int
    diff_by_file: dict[str, int]


class Hidden(Protocol):
    files: list[str]
    recreated: list[str]


@runtime_checkable
class Stand(Protocol):
    name: str

    root: Path

    def reset(self) -> str: ...
    def apply(self, patch: str, reverse: bool = False) -> Step: ...
    def commit_baseline(self, message: str) -> str: ...
    def sever_history(self) -> str: ...
    def restore_history(self) -> bool: ...
    def reset_to(self, sha: str | None = None) -> None: ...
    def anchor(self) -> str: ...

    def build(self, changed: list[str] | None = None) -> Step: ...
    def install(self) -> Step: ...
    def test(self, tests: list[str] | None = None) -> TestReport: ...

    def diff(self) -> str: ...
    def changed_files(self) -> list[str]: ...

    def hide(self, paths: list[str]) -> AbstractContextManager[Hidden]: ...

    def search_roots(self) -> list[Path]: ...

    def history(self) -> dict: ...

    def is_protected(self, path: str) -> bool: ...

    def is_test_area(self, path: str) -> bool: ...

    def diverged(self, diff_by_file: dict[str, int]) -> set[str]: ...


class Suite:
    id: str = "suite"
    stand: str = "postgres"
    root: Path

    @property
    def data(self) -> Path:
        raise NotImplementedError

    def task_names(self) -> list[str]:
        raise NotImplementedError

    def runnable(self) -> list[str]:
        return self.task_names()

    def load(self, name: str) -> tuple[dict, dict]:
        raise NotImplementedError

    def mutation(self, oracle: dict) -> str:
        raise NotImplementedError

    def base(self, oracle: dict) -> str | None:
        return None

    def private_dirs(self) -> list[Path]:
        return []

    def prompt(self, task: dict, oracle: dict) -> str:
        raise NotImplementedError

    def hide(self, task: dict, oracle: dict) -> list[str]:
        return []

    def reference_files(self, oracle: dict) -> list[str]:
        return []

    def secret_strings(self, oracle: dict) -> list[str]:
        return []

    def expected_failures(self, oracle: dict) -> set[str]:
        return set(oracle.get("failing_tests") or [])

    def test_names(self, oracle: dict) -> list[str]:
        return []

    check_names: tuple[str, ...] = ()

    def checks(self, task: dict, stand) -> dict:
        return {}

    def specification(self, task: dict) -> str:
        return self.prompt(task, {})

    def reference(self, oracle: dict) -> str:
        return ""

    def record_verification(self, name: str, status: str, check: dict) -> None:
        import json

        path = self.root / "data" / "oracle" / f"{name}.json"
        oracle = json.loads(path.read_text())
        oracle["failing_tests"] = (
            check.get("failed", []) if status in ("usable", "no_coverage") else None
        )
        oracle["usable"] = status == "usable"
        oracle["verify_status"] = status

        oracle["oracle_diff_lines"] = check.get("diff_lines", 0)
        oracle["oracle_diff_by_file"] = check.get("diff_by_file", {})
        path.write_text(
            json.dumps(oracle, indent=2, ensure_ascii=False), encoding="utf-8"
        )

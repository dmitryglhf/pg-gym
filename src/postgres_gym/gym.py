from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core import data, registry
from postgres_gym.execution import TaskRequest, load_backend
from postgres_gym.execution import payload as task_payload
from postgres_gym.execution.base import ExecutionBackend, TaskResult


@dataclass(frozen=True)
class TaskSpec:
    suite: str
    name: str
    prompt: str
    task_hash: str
    data: dict


@dataclass(frozen=True)
class EpisodeResult:
    suite: str
    task: str
    agent: str
    execution: TaskResult
    record: dict | None

    @property
    def ok(self) -> bool:
        return self.execution.ok and self.record is not None

    @property
    def reward(self) -> float | None:
        if self.record is None:
            return None
        value = self.record.get("reward")
        return float(value) if value is not None else None


class Gym:
    def __init__(
        self, suite: str | None = None, backend: str | ExecutionBackend | None = None
    ):
        settings.use_suite(suite)
        self.suite = registry.load(settings.SUITE_ID)
        self.backend = (
            load_backend(backend)
            if isinstance(backend, str) or backend is None
            else backend
        )

    def tasks(self, split: str | None = None) -> list[str]:
        return data.apply_split(self.suite.data, self.suite.runnable(), split)

    def task(self, name: str) -> TaskSpec:
        if name not in set(self.suite.runnable()):
            raise SystemExit(
                f"task {name!r} is not runnable in suite {self.suite.id!r}"
            )
        public, oracle = self.suite.load(name)
        return TaskSpec(
            suite=self.suite.id,
            name=name,
            prompt=self.suite.prompt(public, oracle),
            task_hash=data.task_hash(self.suite.data, name),
            data=public,
        )

    def run(
        self,
        task: str,
        agent: str,
        *,
        completion: str | None = None,
        level: str = "L0",
        judge: bool = False,
        judge_model: str | None = None,
        judge_base_url: str | None = None,
    ) -> EpisodeResult:
        self.task(task)
        return self._execute(
            task,
            agent,
            completion=completion,
            level=level,
            judge=judge,
            judge_model=judge_model,
            judge_base_url=judge_base_url,
        )

    def verify(self, task: str) -> dict:
        if task not in set(self.suite.task_names()):
            raise SystemExit(f"unknown task {task!r} in suite {self.suite.id!r}")

        fixed = self._execute(task, "replay")
        fixed_status = _fixed_status(fixed)
        if fixed_status != "fixed":
            check = (fixed.record or {}).get("check") or {}
            self.suite.record_verification(task, fixed_status, check)
            return {
                "func": task,
                "status": fixed_status,
                "usable": False,
                "fixed": _episode_summary(fixed),
            }

        mutated = self._execute(task, "noop")
        _, oracle = self.suite.load(task)
        status = _mutation_status(mutated, set(oracle.get("expected_tests") or []))
        check = (mutated.record or {}).get("check") or {}
        self.suite.record_verification(task, status, check)
        return {
            "func": task,
            "status": status,
            "usable": status == "usable",
            "fixed": _episode_summary(fixed),
            "mutation": _episode_summary(mutated),
        }

    def _execute(
        self,
        task: str,
        agent: str,
        *,
        completion: str | None = None,
        level: str = "L0",
        judge: bool = False,
        judge_model: str | None = None,
        judge_base_url: str | None = None,
    ) -> EpisodeResult:
        if agent.startswith("cli:") and not settings.PROVIDER_KEY:
            raise SystemExit("MARKOV_API_KEY or PGPRO_API_KEY is not set")
        if reason := self.backend.available():
            raise SystemExit(reason)

        execution = {"backend": self.backend.name}
        image_id = getattr(self.backend, "image_id", lambda: "")()
        if image_id:
            execution["image_id"] = image_id

        args = list(("--judge",) if judge else ())
        if judge_model:
            args += ["--judge-model", judge_model]
        if judge_base_url:
            args += ["--judge-base-url", judge_base_url]
        request = TaskRequest(
            suite=self.suite.id,
            task=task,
            agent=agent,
            level=level,
            payload=task_payload.build(self.suite, task, execution, completion, judge=judge),
            extra_args=tuple(args),
        )
        result = self.backend.run(request)
        record = self._read_record(result.records, task, agent)
        return EpisodeResult(self.suite.id, task, agent, result, record)

    @staticmethod
    def _read_record(paths: tuple[Path, ...], task: str, agent: str) -> dict | None:
        for path in reversed(paths):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("func") == task and record.get("agent") == agent:
                return record
        return None


def _fixed_status(result: EpisodeResult) -> str:
    record = result.record
    if not result.execution.ok or record is None:
        return "fixed_infrastructure_failed"
    if record.get("error"):
        return "fixed_setup_failed"
    if not (record.get("agent_meta") or {}).get("applied"):
        return "fixed_reference_failed"
    if not (record.get("build") or {}).get("ok"):
        return "fixed_build_failed"
    if not (record.get("install") or {}).get("ok"):
        return "fixed_install_failed"
    check = record.get("check") or {}
    if not check.get("total"):
        return "fixed_check_did_not_run"
    if check.get("failed") or check.get("diverged"):
        return "fixed_regression_failed"
    return "fixed"


def _mutation_status(result: EpisodeResult, expected: set[str]) -> str:
    record = result.record
    if not result.execution.ok or record is None:
        return "infrastructure_failed"
    if record.get("error"):
        return "mutation_failed"
    if not (record.get("build") or {}).get("ok"):
        return "build_failed"
    if not (record.get("install") or {}).get("ok"):
        return "install_failed"
    check = record.get("check") or {}
    if not check.get("total"):
        return "check_did_not_run"
    failed = set(check.get("failed") or [])
    if not failed:
        return "no_coverage"
    if expected and not expected <= failed:
        return "unexpected_coverage"
    return "usable"


def _episode_summary(result: EpisodeResult) -> dict:
    record = result.record or {}
    check = record.get("check") or {}
    return {
        "backend_ok": result.execution.ok,
        "error": record.get("error"),
        "build_ok": (record.get("build") or {}).get("ok"),
        "install_ok": (record.get("install") or {}).get("ok"),
        "tests_run": check.get("total", 0),
        "failed": check.get("failed") or [],
        "seconds": record.get("seconds"),
    }

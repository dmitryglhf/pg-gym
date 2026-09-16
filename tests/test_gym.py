import json
from pathlib import Path

from postgres_gym.execution.base import TaskRequest, TaskResult
from postgres_gym.gym import EpisodeResult, Gym, _fixed_status, _mutation_status


class FakeBackend:
    name = "fake"
    scored = False

    def __init__(self, root: Path):
        self.root = root
        self.request: TaskRequest | None = None

    def available(self) -> str | None:
        return None

    def build(self, args=None) -> int:
        return 0

    def run(self, request: TaskRequest) -> TaskResult:
        self.request = request
        path = self.root / "record.json"
        path.write_text(json.dumps({"func": request.task, "agent": request.agent, "reward": 1.0}))
        return TaskResult(0, "", "", (path,), self.name)


def test_task_spec_exposes_prompt_without_oracle(tmp_path: Path):
    gym = Gym("sql-function-set", FakeBackend(tmp_path))
    task = gym.task("area")

    assert task.name == "area"
    assert task.prompt
    assert task.task_hash
    assert "oracle" not in task.data


def test_run_uses_backend_and_reads_record(tmp_path: Path):
    backend = FakeBackend(tmp_path)
    gym = Gym("sql-function-set", backend)
    result = gym.run("area", "noop")

    assert result.ok
    assert result.reward == 1.0
    assert backend.request is not None
    assert backend.request.suite == "sql-function-set"


def test_run_sends_completion_in_the_task_payload(tmp_path: Path):
    backend = FakeBackend(tmp_path)
    gym = Gym("sql-function-set", backend)
    gym.run("area", "patch", completion="diff --git a/x b/x")

    assert backend.request is not None
    assert json.loads(backend.request.payload)["completion"] == "diff --git a/x b/x"


def test_patch_task_receives_no_judge_secret(tmp_path, monkeypatch):
    from postgres_gym import settings

    monkeypatch.setenv(settings.JUDGE_KEY_ENV, "operator-secret")
    backend = FakeBackend(tmp_path)
    Gym("sql-function-set", backend).run("area", "patch", completion="patch")
    assert backend.request is not None
    assert json.loads(backend.request.payload)["secrets"] == {}


def episode(record: dict | None, returncode: int = 0) -> EpisodeResult:
    result = TaskResult(returncode, "", "", (Path("record.json"),), "fake")
    return EpisodeResult("commit", "task", "noop", result, record)


def test_fixed_status_accepts_green_regression_run():
    record = {
        "agent_meta": {"applied": True},
        "build": {"ok": True},
        "install": {"ok": True},
        "check": {"total": 10, "failed": [], "diverged": []},
    }

    assert _fixed_status(episode(record)) == "fixed"


def test_mutation_status_requires_expected_failure():
    record = {
        "build": {"ok": True},
        "install": {"ok": True},
        "check": {"total": 10, "failed": ["other"]},
    }

    assert _mutation_status(episode(record), {"wanted"}) == "unexpected_coverage"

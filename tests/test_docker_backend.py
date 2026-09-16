import subprocess

import pytest

from postgres_gym.execution.base import TaskRequest
from postgres_gym.execution.docker import DockerBackend


def request() -> TaskRequest:
    return TaskRequest(
        suite="sql-function-set",
        task="area",
        agent="cli:markov",
        level="L0",
        payload=b"{}",
    )


def test_task_container_uses_no_bind_mounts():
    backend = DockerBackend(image="task:test", context="", network="")
    command = backend.create_command(request(), "task-1")

    assert "-v" not in command
    assert "--volume" not in command
    assert "task:test" in command
    assert "worker" in command
    assert "--suite" in command


def test_docker_context_changes_connection_only():
    backend = DockerBackend(context="remote", network="")
    assert backend._docker("version")[:3] == ["docker", "--context", "remote"]


def test_patch_container_does_not_receive_operator_secrets(monkeypatch):
    backend = DockerBackend(context="", network="")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "container", ""),
    )
    monkeypatch.setattr(
        backend,
        "_copy_secret_env",
        lambda *args: (_ for _ in ()).throw(AssertionError("secrets copied")),
    )
    monkeypatch.setattr(
        backend, "_start", lambda *args: subprocess.CompletedProcess([], 0, "", "")
    )
    monkeypatch.setattr(backend, "_copy_results", lambda *args: ())
    result = backend.run(
        TaskRequest(
            suite="commit", task="test", agent="patch", level="L0", payload=b"{}"
        )
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_platform_cancellation_propagates_through_task_backend(monkeypatch):
    from postgres_gym_platform.execute import Cancelled

    backend = DockerBackend(context="", network="")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "container", ""),
    )
    monkeypatch.setattr(
        backend, "_start", lambda *args: (_ for _ in ()).throw(Cancelled())
    )
    with pytest.raises(Cancelled):
        backend.run(
            TaskRequest(
                suite="commit", task="test", agent="patch", level="L0", payload=b"{}"
            )
        )

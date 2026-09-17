import subprocess
from dataclasses import replace

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


def test_acp_container_publishes_its_port_on_loopback_and_is_labelled():
    backend = DockerBackend(image="task:test", context="", network="")
    acp = replace(
        request(), agent="acp:markov", ports=(3284,), labels={"pg-gym.episode": "e1"}
    )
    command = backend.create_command(acp, "task-1")

    assert command[command.index("--publish") + 1] == "127.0.0.1:0:3284"
    label = command.index("pg-gym.episode=e1")
    assert command[label - 1] == "--label"
    assert "--publish" not in backend.create_command(request(), "task-2")


def test_acp_container_receives_the_provider_key(monkeypatch):
    backend = DockerBackend(context="", network="")
    copied: list[str] = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "container", ""),
    )
    monkeypatch.setattr(backend, "_copy_secret_env", copied.append)
    monkeypatch.setattr(
        backend, "_start", lambda *args: subprocess.CompletedProcess([], 0, "", "")
    )
    monkeypatch.setattr(backend, "_copy_results", lambda *args: ())
    backend.run(replace(request(), agent="acp:markov"))

    assert copied == ["container"]


def test_published_port_reads_the_loopback_binding(monkeypatch):
    backend = DockerBackend(context="", network="")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "127.0.0.1:55000\n[::1]:55000\n", ""
        ),
    )
    assert backend.published_port("abc", 3284) == 55000

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "", "no such"),
    )
    assert backend.published_port("abc", 3284) is None


def test_containers_lists_ids_by_label(monkeypatch):
    backend = DockerBackend(context="", network="")
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, "abc\ndef\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert backend.containers("pg-gym.episode=e1") == ["abc", "def"]
    assert seen["command"][-2:] == ["--filter", "label=pg-gym.episode=e1"]


def test_write_streams_data_into_the_container(monkeypatch):
    backend = DockerBackend(context="", network="")
    seen: dict = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs.get("input")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend.write("abc", "/work/acp/done", b"x")

    assert seen["command"][:4] == ["docker", "exec", "-i", "abc"]
    assert seen["command"][-1] == "/work/acp/done"
    assert seen["input"] == b"x"

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, b"", b"denied"),
    )
    with pytest.raises(RuntimeError, match="denied"):
        backend.write("abc", "/work/acp/done", b"x")

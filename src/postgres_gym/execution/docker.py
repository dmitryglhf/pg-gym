from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core.agents import external
from postgres_gym.execution.base import TaskRequest, TaskResult

FORWARDED_ENV = (
    "POSTGRES_GYM_EVENTS",
    "POSTGRES_GYM_HARNESS_CONFIG",
    "PG_GYM_JOB_ID",
    "PGPRO_HOST",
    "PGPRO_BASE_PATH",
    "PGPRO_TIMEOUT",
    "GOOSE_PROVIDER",
    "GOOSE_MODEL",
    "LANGFUSE_URL",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_HOST",
    "POSTGRES_GYM_REQUIRE_LANGFUSE",
    "POSTGRES_GYM_AGENT_TIMEOUT",
)

SECRET_ENV = (
    "MARKOV_API_KEY",
    "PGPRO_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


class DockerBackend:
    name = "docker"
    scored = True

    def __init__(
        self,
        image: str | None = None,
        context: str | None = None,
        network: str | None = None,
    ):
        self.image = image or settings.TASK_IMAGE
        self.context = settings.DOCKER_CONTEXT if context is None else context
        self.network = settings.DOCKER_NETWORK if network is None else network

    def _docker(self, *args: str) -> list[str]:
        command = ["docker"]
        if self.context:
            command += ["--context", self.context]
        return [*command, *args]

    def available(self) -> str | None:
        try:
            result = subprocess.run(
                self._docker("version", "--format", "{{.Server.Version}}"),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"docker is not usable: {exc}"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            return detail or "docker daemon is not reachable"
        return None

    def build(self, args: list[str] | None = None) -> int:
        command = self._docker(
            "build",
            "-f",
            "deploy/task/Dockerfile",
            "-t",
            self.image,
            *(args or []),
            ".",
        )
        return subprocess.run(command, cwd=settings.ROOT, check=False).returncode

    def image_id(self) -> str:
        result = subprocess.run(
            self._docker("image", "inspect", self.image, "--format", "{{.Id}}"),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def run(self, request: TaskRequest) -> TaskResult:
        container_name = f"postgres-gym-{request.task[:32]}-{uuid.uuid4().hex[:10]}"
        created = subprocess.run(
            self.create_command(request, container_name),
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            return TaskResult(
                created.returncode, created.stdout, created.stderr, (), self.name
            )

        container_id = created.stdout.strip()
        try:
            if external(request.agent):
                self._copy_secret_env(container_id)
            started = self._start(container_id, request.payload)
            records = self._copy_results(container_id)
            stdout = (
                started.stdout.decode("utf-8", "replace")
                if isinstance(started.stdout, bytes)
                else started.stdout or ""
            )
            stderr = (
                started.stderr.decode("utf-8", "replace")
                if isinstance(started.stderr, bytes)
                else started.stderr or ""
            )
            return TaskResult(
                started.returncode, stdout, stderr, records, self.name, container_id
            )
        except Exception as exc:  # noqa: BLE001
            return TaskResult(
                1, "", f"{type(exc).__name__}: {exc}", (), self.name, container_id
            )
        finally:
            subprocess.run(
                self._docker("rm", "-f", container_id), capture_output=True, check=False
            )

    def create_command(self, request: TaskRequest, container_name: str) -> list[str]:
        command = self._docker(
            "create",
            "--init",
            "-i",
            "--name",
            container_name,
            "--label",
            "postgres-gym.task=true",
        )
        if identifier := os.environ.get("PG_GYM_JOB_ID"):
            command += ["--label", f"pg-gym.job={identifier}"]
        command += [
            "--cpus",
            os.environ.get("PG_GYM_TASK_CPUS", "4"),
            "--memory",
            os.environ.get("PG_GYM_TASK_MEMORY", "8g"),
            "--pids-limit",
            "1024",
        ]
        if self.network:
            command += ["--network", self.network]
        for key, value in request.labels.items():
            command += ["--label", f"{key}={value}"]
        for port in request.ports:
            command += ["--publish", f"127.0.0.1:0:{port}"]
        for key, value in self._environment(request).items():
            command += ["--env", f"{key}={value}"]
        command += [
            self.image,
            "worker",
            request.task,
            "--suite",
            request.suite,
            "--agent",
            request.agent,
            "--level",
            request.level,
            *request.extra_args,
        ]
        return command

    def _environment(self, request: TaskRequest) -> dict[str, str]:
        environment = {
            "POSTGRES_GYM_ROOT": "/opt/postgres-gym",
            "POSTGRES_GYM_SUITE": request.suite,
            "POSTGRES_GYM_SRC": "/bench/pg",
            "POSTGRES_GYM_PREFIX": "/bench/pg-install",
            "POSTGRES_GYM_GIT_DIR": "/bench/pg.git",
            "POSTGRES_GYM_RUNS": "/work/runs",
            "POSTGRES_GYM_DISPOSABLE_GIT": "1",
            "POSTGRES_GYM_PAYLOAD_STDIN": "1",
        }
        for key in FORWARDED_ENV:
            if value := os.environ.get(key):
                environment[key] = value
        environment.update(request.environment)
        return environment

    def _copy_secret_env(self, container_id: str) -> None:
        lines = [
            f"{key}={os.environ[key]}" for key in SECRET_ENV if os.environ.get(key)
        ]
        with tempfile.TemporaryDirectory(prefix="postgres-gym-secret-") as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )
            path.chmod(0o600)
            result = subprocess.run(
                self._docker("cp", str(path), f"{container_id}:/work/.env"),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    (result.stderr or result.stdout).strip()
                    or "failed to copy task secrets"
                )

    def _start(self, container_id: str, payload: bytes) -> subprocess.CompletedProcess:
        proc = subprocess.Popen(
            self._docker("start", "-a", "-i", container_id),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        output = bytearray()

        def drain():
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, b""):
                output.extend(line)
                if len(output) > 4 * 1024 * 1024:
                    del output[: -2 * 1024 * 1024]
                if os.environ.get("POSTGRES_GYM_EVENTS") == "1":
                    sys.stdout.write(line.decode("utf-8", "replace"))
                    sys.stdout.flush()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        try:
            assert proc.stdin is not None
            proc.stdin.write(payload)
            proc.stdin.close()
            code = proc.wait(timeout=settings.CONTAINER_TIMEOUT)
        except subprocess.TimeoutExpired:
            subprocess.run(
                self._docker("kill", container_id), capture_output=True, check=False
            )
            proc.wait(timeout=30)
            code = 124
        except BaseException:
            subprocess.run(
                self._docker("kill", container_id), capture_output=True, check=False
            )
            proc.kill()
            proc.wait()
            raise
        finally:
            reader.join(timeout=30)
        return subprocess.CompletedProcess(
            [], code, bytes(output), b"container timeout" if code == 124 else b""
        )

    def containers(self, label: str) -> list[str]:
        """Ids of running task containers carrying `label` (`key=value`)."""
        result = subprocess.run(
            self._docker("ps", "--quiet", "--no-trunc", "--filter", "label=" + label),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.split() if result.returncode == 0 else []

    def published_port(self, container_id: str, port: int) -> int | None:
        """The loopback port `docker create --publish 127.0.0.1:0:<port>` chose."""
        result = subprocess.run(
            self._docker("port", container_id, f"{port}/tcp"),
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            host, _, number = line.strip().rpartition(":")
            if host.strip("[]") in ("127.0.0.1", "0.0.0.0") and number.isdigit():
                return int(number)
        return None

    def write(self, container_id: str, path: str, data: bytes) -> None:
        """Create `path` inside the running container with `data`."""
        script = 'mkdir -p "$(dirname "$1")" && cat > "$1"'
        result = subprocess.run(
            self._docker("exec", "-i", container_id, "sh", "-c", script, "sh", path),
            input=data,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(detail or f"could not write {path} into the container")

    def _copy_results(self, container_id: str) -> tuple[Path, ...]:
        with tempfile.TemporaryDirectory(prefix="postgres-gym-results-") as directory:
            target = Path(directory) / "runs"
            target.mkdir()
            result = subprocess.run(
                self._docker("cp", f"{container_id}:/work/runs/.", str(target)),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return ()
            files = tuple(sorted(target.rglob("*.json")))
            if not files:
                return ()
            settings.RUNS_ROOT.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, settings.RUNS_ROOT, dirs_exist_ok=True)
            return tuple(
                settings.RUNS_ROOT / path.relative_to(target) for path in files
            )

from __future__ import annotations

import importlib.util
import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx2
import psutil

from .runtime import atomic_json, resources
from .security import private_file

LOG = logging.getLogger(__name__)


def alive(state: dict) -> bool:
    try:
        process = psutil.Process(state.get("proc_pid", state["pid"]))
        return (
            abs(process.create_time() - state["created"]) < 0.01
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except (psutil.Error, KeyError):
        return False


def run_worker(api_url: str, token: str, directory: Path, identifier: str):
    if not token:
        raise ValueError("Worker token is required")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl

    lock = (directory / "worker.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with httpx2.Client(
        base_url=api_url,
        headers={"Authorization": "Bearer " + token},
        timeout=20,
        trust_env=False,
    ) as client:
        while not stopping:
            try:
                sample = resources()
                capabilities = ["model_import", "chat"]
                docker = False
                try:
                    docker = (
                        subprocess.run(
                            [
                                "docker",
                                "image",
                                "inspect",
                                os.environ.get(
                                    "POSTGRES_GYM_TASK_IMAGE", "postgres-gym-task:17.11"
                                ),
                            ],
                            capture_output=True,
                            check=False,
                            timeout=10,
                        ).returncode
                        == 0
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
                if docker:
                    capabilities.append("benchmark")
                if sample["gpus"]:
                    if docker and all(
                        importlib.util.find_spec(name)
                        for name in ("torch", "trl", "peft")
                    ):
                        capabilities.extend(["training", "evaluation"])
                    if docker:
                        capabilities.append("deployment")
                report = {
                    "id": identifier,
                    "capabilities": capabilities,
                    "resources": sample,
                }
                client.post(
                    "/internal/workers/heartbeat", json=report
                ).raise_for_status()
                for job_dir in sorted(directory.glob("jobs/*")):
                    if (job_dir / "acknowledged").exists() or not (
                        job_dir / "assignment.json"
                    ).is_file():
                        continue
                    sync_job(client, job_dir)
                claim_path = directory / "pending-claim.json"
                if not claim_path.exists():
                    atomic_json(claim_path, {"claim_id": uuid.uuid4().hex})
                claimed = client.post(
                    "/internal/workers/claim",
                    json={**report, **json.loads(claim_path.read_text())},
                )
                claimed.raise_for_status()
                assignment = claimed.json()
                if assignment.get("job"):
                    job_dir = directory / "jobs" / assignment["job"]["id"]
                    job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if not (job_dir / "assignment.json").exists():
                        assignment["api_url"] = api_url
                        assignment["task_api_url"] = os.environ.get(
                            "PG_GYM_TASK_API_URL", api_url
                        )
                        atomic_json(job_dir / "assignment.json", assignment)
                        with (job_dir / "process.log").open("ab") as log:
                            process = subprocess.Popen(
                                [
                                    sys.executable,
                                    "-m",
                                    "postgres_gym_platform.execute",
                                    str(job_dir),
                                ],
                                stdin=subprocess.DEVNULL,
                                stdout=log,
                                stderr=subprocess.STDOUT,
                                start_new_session=True,
                            )
                        process.poll()
                claim_path.unlink()
            except (httpx2.HTTPError, OSError, ValueError, psutil.Error) as exc:
                LOG.warning("Worker reconnecting: %s", type(exc).__name__)
            for _ in range(20):
                if stopping:
                    break
                time.sleep(0.1)
    lock.close()


def sync_job(client: httpx2.Client, directory: Path):
    assignment = json.loads((directory / "assignment.json").read_text())
    identifier = assignment["job"]["id"]
    headers = {"Authorization": "Bearer " + assignment["attempt_token"]}
    heartbeat = client.post(f"/internal/jobs/{identifier}/heartbeat", headers=headers)
    heartbeat.raise_for_status()
    status = heartbeat.json()
    state_path = directory / "process.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    running = alive(state)
    if status["cancel_requested"] and running:
        cancel_at = directory / "cancel-requested"
        if not cancel_at.exists():
            private_file(cancel_at, str(time.time()).encode())
            os.killpg(state["pid"], signal.SIGTERM)
        elif time.time() - float(cancel_at.read_text()) > 30:
            os.killpg(state["pid"], signal.SIGKILL)
    cursor_path = directory / "cursor.json"
    cursor = (
        json.loads(cursor_path.read_text())["offset"] if cursor_path.exists() else 0
    )
    events_path = directory / "events.jsonl"
    if events_path.exists():
        with events_path.open("rb") as source:
            source.seek(cursor)
            batch = []
            for _ in range(100):
                line = source.readline()
                if not line.endswith(b"\n"):
                    break
                batch.append(json.loads(line))
                cursor = source.tell()
        if batch:
            response = client.post(
                f"/internal/jobs/{identifier}/events",
                json={"events": batch},
                headers=headers,
            )
            response.raise_for_status()
            atomic_json(cursor_path, {"offset": cursor})
        if cursor < events_path.stat().st_size:
            if running or batch:
                return
            atomic_json(cursor_path, {"offset": events_path.stat().st_size})
    final_path = directory / "result.json"
    if not running and not final_path.exists():
        if (
            not state
            and time.time() - (directory / "assignment.json").stat().st_mtime < 30
        ):
            return
        atomic_json(
            final_path,
            {
                "status": "cancelled" if status["cancel_requested"] else "failed",
                "error": "Execution process was interrupted",
                "result": None,
            },
        )
    if final_path.exists() and not running:
        if assignment["job"].get("kind") not in {
            "chat",
            "model_import",
        } and not cleanup_containers(identifier):
            return
        response = client.post(
            f"/internal/jobs/{identifier}/finish",
            json=json.loads(final_path.read_text()),
            headers=headers,
        )
        response.raise_for_status()
        private_file(directory / "acknowledged", b"1")


def cleanup_containers(identifier: str):
    try:
        result = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=pg-gym.job=" + identifier],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if result.returncode:
            return False
        for container in result.stdout.splitlines():
            if subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                check=False,
                timeout=30,
            ).returncode:
                return False
        volumes = subprocess.run(
            [
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                "label=pg-gym.job=" + identifier,
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        )
        for volume in volumes.stdout.splitlines():
            if subprocess.run(
                ["docker", "volume", "rm", volume],
                capture_output=True,
                check=False,
                timeout=30,
            ).returncode:
                return False
        return True
    except FileNotFoundError:
        return True
    except (OSError, subprocess.SubprocessError):
        LOG.warning("Container cleanup requires reconciliation for job %s", identifier)
        return False

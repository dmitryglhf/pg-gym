from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx


def atomic_json(path: Path, value):
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        temporary.chmod(0o600)
        json.dump(value, output, ensure_ascii=False, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def process_identity() -> dict:
    import psutil
    pid = os.getpid()
    proc = Path("/proc/self/stat")
    proc_pid = int(proc.read_text().split(" ", 1)[0]) if proc.exists() else pid
    return {"pid": pid, "proc_pid": proc_pid, "created": psutil.Process(proc_pid).create_time()}


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class Emitter:
    def __init__(self, directory: Path):
        self.path = directory / "events.jsonl"
        self.sequence = 0
        self.lock = threading.Lock()

    def emit(self, event_kind: str, **payload):
        with self.lock:
            self.sequence += 1
            if event_kind == "log" and self.path.exists() and self.path.stat().st_size > 100 * 1024**2:
                return
            value = {"source_id": f"process-{self.sequence}", "kind": event_kind, "payload": payload}
            with self.path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
                output.flush()

    def line(self, line: str):
        if line.startswith("@pg-gym "):
            try:
                item = json.loads(line[8:])
                self.emit(item["kind"], **item["payload"])
                return
            except (ValueError, KeyError, TypeError):
                pass
        self.emit("log", text=line[-6000:])


class Runtime:
    def __init__(self, directory: Path):
        self.directory = directory
        self.settings = json.loads((directory / "assignment.json").read_text())
        self.job = self.settings["job"]
        self.config = self.job["config"]
        self.id = self.job["id"]
        self.events = Emitter(directory)
        self.client = httpx.Client(base_url=self.settings["api_url"], headers={"Authorization": "Bearer " + self.settings["attempt_token"]}, timeout=60, trust_env=False)

    def request(self, method: str, path: str, **kwargs):
        for retry in range(4):
            try:
                response = self.client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                if retry == 3:
                    raise
                time.sleep(2 ** retry)
        raise RuntimeError("Request retries exhausted")

    def materialize(self, artifact_id: str) -> tuple[Path, dict]:
        metadata = self.request("GET", f"/internal/jobs/{self.id}/artifacts/{artifact_id}")
        if metadata["status"] != "ready":
            raise ValueError("Artifact is not ready")
        directory = self.directory / "inputs" / artifact_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.events.emit("phase", phase="downloading", artifact_id=artifact_id)
        for item in metadata["files"]:
            from .artifacts import safe_relative
            relative = safe_relative(item["path"])
            path = directory / relative
            if path.is_file() and path.stat().st_size == item["size"] and sha256(path) == item["sha256"]:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".part")
            with self.client.stream("GET", f"/internal/jobs/{self.id}/artifacts/{artifact_id}/files/" + quote(item["path"], safe="/")) as response:
                response.raise_for_status()
                with temporary.open("wb") as output:
                    for chunk in response.iter_bytes(1024**2):
                        output.write(chunk)
            if temporary.stat().st_size != item["size"] or sha256(temporary) != item["sha256"]:
                raise RuntimeError("Downloaded artifact failed checksum verification")
            temporary.replace(path)
        return directory, metadata

    def publish(self, directory: Path, name: str, kind: str, metadata: dict) -> str:
        files: list[dict] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink() or any(p.startswith(".") for p in path.relative_to(directory).parts):
                continue
            files.append({"path": path.relative_to(directory).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)})
        self.events.emit("phase", phase="saving", files=len(files))
        artifact = self.request("POST", "/internal/artifacts", json={"job_id": self.id, "name": name, "kind": kind, "metadata": metadata, "files": files})
        identifier = artifact["id"]
        if artifact.get("status") == "ready":
            return identifier
        for item in files:
            with (directory / item["path"]).open("rb") as source:
                response = self.client.put(f"/internal/artifacts/{identifier}/files/" + quote(item["path"], safe="/"), content=iter(lambda: source.read(1024**2), b""), headers={"content-length": str(item["size"])}, timeout=3600)
                response.raise_for_status()
        self.request("POST", f"/internal/artifacts/{identifier}/complete")
        self.events.emit("artifact", id=identifier, name=name, kind=kind)
        return identifier


def resources() -> dict:
    import subprocess

    import psutil
    memory = psutil.virtual_memory()
    result = {"cpu_percent": psutil.cpu_percent(), "ram_used": memory.used, "ram_total": memory.total, "gpus": [], "at": time.time()}
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, check=False, text=True, timeout=5)
        if query.returncode == 0:
            for line in query.stdout.splitlines():
                index, name, used, total, utilization = [value.strip() for value in line.split(",")]
                result["gpus"].append({"index": int(index), "name": name, "memory_used": int(used) * 1024**2, "memory_total": int(total) * 1024**2, "utilization": float(utilization)})
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return result

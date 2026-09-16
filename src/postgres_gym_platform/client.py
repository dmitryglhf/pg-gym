from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_failed"):
        super().__init__(message)
        self.status = status
        self.code = code


class Client:
    def __init__(self, url: str, token: str = "", timeout: float = 60):
        self.http = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": "Bearer " + token} if token else {}, timeout=timeout, trust_env=False, follow_redirects=False)

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.http.request(method, "/api/v1" + path, **kwargs)
        if not response.is_success:
            try:
                error = response.json()["error"]
                message, code = error["message"], error["code"]
            except (ValueError, KeyError, TypeError):
                message, code = f"API returned HTTP {response.status_code}", "request_failed"
            raise ApiError(response.status_code, message, code)
        return response.json()

    def close(self) -> None:
        self.http.close()


def config_dir() -> Path:
    if value := os.environ.get("PG_GYM_CONFIG_DIR"):
        return Path(value).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "pg-gym"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "pg-gym"


def read_contexts() -> dict:
    path = config_dir() / "contexts.json"
    return json.loads(path.read_text()) if path.exists() else {"active": None, "contexts": {}}


def write_contexts(value: dict):
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "contexts.json"
    descriptor, name = tempfile.mkstemp(prefix="contexts-", suffix=".tmp", dir=directory)
    temporary = Path(name)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import httpx2

from . import Client


def config_dir() -> Path:
    if value := os.environ.get("PG_GYM_CONFIG_DIR"):
        return Path(value).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "pg-gym"
    home = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(home) / "pg-gym"


def read_contexts() -> dict:
    path = config_dir() / "contexts.json"
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"active": None, "contexts": {}}
    )


def write_contexts(value: dict) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "contexts.json"
    descriptor, name = tempfile.mkstemp(
        prefix="contexts-", suffix=".tmp", dir=directory
    )
    temporary = Path(name)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def public(contexts: dict) -> dict:
    return {
        "active": contexts.get("active"),
        "contexts": {
            name: {"url": value["url"], "authenticated": bool(value.get("token"))}
            for name, value in contexts.get("contexts", {}).items()
        },
    }


def listing() -> dict:
    return public(read_contexts())


def add(name: str, url: str) -> dict:
    parsed = httpx2.URL(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.host
        or parsed.userinfo
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Use an HTTP(S) API URL without credentials, query or fragment"
        )
    values = read_contexts()
    if name in values["contexts"]:
        raise ValueError("Context already exists; remove it before changing its server")
    values["contexts"][name] = {"url": url.rstrip("/")}
    values["active"] = values.get("active") or name
    write_contexts(values)
    return public(values)


def use(name: str) -> dict:
    values = read_contexts()
    if name not in values["contexts"]:
        raise ValueError("Unknown context: " + name)
    values["active"] = name
    write_contexts(values)
    return public(values)


def remove(name: str) -> dict:
    values = read_contexts()
    if name not in values["contexts"]:
        raise ValueError("Unknown context: " + name)
    del values["contexts"][name]
    if values.get("active") == name:
        values["active"] = None
    write_contexts(values)
    return public(values)


def connect(selected: str | None, timeout: float) -> tuple[Client, dict, str | None]:
    """Client for the selected or active context. An explicit context wins over the environment."""
    contexts = read_contexts()
    name = selected or contexts.get("active")
    configured = contexts.get("contexts", {}).get(name, {}) if name else {}
    if selected and not configured:
        raise ValueError("Unknown context: " + selected)
    if not selected and os.environ.get("PG_GYM_URL"):
        url, token, name = (
            os.environ["PG_GYM_URL"],
            os.environ.get("PG_GYM_TOKEN", ""),
            None,
        )
    else:
        url, token = configured.get("url"), configured.get("token", "")
        if os.environ.get("PG_GYM_TOKEN") and not selected:
            raise ValueError("PG_GYM_TOKEN requires PG_GYM_URL or use a named context")
    if not url:
        raise ValueError("Configure a context or set PG_GYM_URL")
    return Client(url, token, timeout), contexts, name


def login(
    client: Client,
    contexts: dict,
    name: str | None,
    username: str | None,
    password: str | None,
    token: str | None,
) -> dict:
    if not name:
        raise ValueError("Select --context NAME before saving a login")
    if token is not None:
        if not token:
            raise ValueError("Token must not be empty")
        client.http.headers["Authorization"] = "Bearer " + token
        user = client.request("GET", "/me")
    else:
        issued = client.request(
            "POST", "/auth/token", json={"username": username, "password": password}
        )
        token, user = issued["token"], issued["user"]
    contexts["contexts"][name]["token"] = token
    write_contexts(contexts)
    return user


def logout(client: Client, contexts: dict, name: str | None) -> dict:
    client.request("POST", "/auth/logout")
    if name:
        contexts["contexts"][name].pop("token", None)
        write_contexts(contexts)
    return {"ok": True}

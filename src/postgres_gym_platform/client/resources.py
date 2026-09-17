from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from . import Client

PATHS = {
    "connections": "/connections",
    "credentials": "/secrets",
    "profiles": "/harness-profiles",
}


def list_resources(client: Client, kind: str) -> list[dict]:
    return client.request("GET", PATHS[kind])


def create_resource(client: Client, kind: str, config: Path) -> dict:
    from .specs import read_mapping

    return client.request("POST", PATHS[kind], json=read_mapping(config))


def delete_resource(client: Client, kind: str, identifier: str) -> dict:
    return client.request("DELETE", PATHS[kind] + "/" + quote(identifier, safe=""))

from pathlib import Path
from urllib.parse import quote

from .http import request
from .specs import read_mapping

PATHS = {
    "connections": "/connections",
    "credentials": "/secrets",
    "profiles": "/harness-profiles",
}


def list_resources(kind: str):
    return request("GET", PATHS[kind])


def create_resource(kind: str, config: Path):
    return request("POST", PATHS[kind], json=read_mapping(config))


def delete_resource(kind: str, identifier: str):
    return request("DELETE", PATHS[kind] + "/" + quote(identifier, safe=""))

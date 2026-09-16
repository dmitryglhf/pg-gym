from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .db import encode
from .security import principal

Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]
Value = Annotated[SecretStr, Field(max_length=8192)]


class Environment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    variables: dict[Name, Value | None] = Field(max_length=100)


router = APIRouter(prefix="/api/v1/environment")
USER = Depends(principal)


def read_environment(db, vault, owner: str) -> tuple[int, dict[str, str]]:
    row = db.execute("SELECT revision,value FROM environment WHERE owner_id=?", (owner,)).fetchone()
    if row is None:
        return 0, {}
    return row["revision"], json.loads(vault.decrypt(row["value"].encode()))


def variable(db, vault, owner: str, name: str) -> str:
    _, values = read_environment(db, vault, owner)
    if name not in values:
        raise HTTPException(422, "Selected environment variable is missing")
    return values[name]


def connection_key(db, vault, row, config: dict | None = None) -> str:
    cfg = config if config is not None else json.loads(row["config"])
    if name := cfg.get("api_key_env"):
        return variable(db, vault, row["owner_id"], name)
    return vault.decrypt(row["secret"].encode()).decode() if row["secret"] else ""


@router.get("")
def metadata(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        revision, variables = read_environment(db, request.app.state.vault, user["id"])
    return {"revision": revision, "names": sorted(variables)}


@router.post("/reveal")
def reveal(request: Request, user=USER):
    with request.app.state.db.connect() as db:
        revision, variables = read_environment(db, request.app.state.vault, user["id"])
    return {"revision": revision, "variables": variables}


@router.put("")
def save(body: Environment, request: Request, user=USER):
    with request.app.state.db.connect(write=True) as db:
        revision, previous = read_environment(db, request.app.state.vault, user["id"])
        if body.revision != revision:
            raise HTTPException(409, "Environment changed in another session. Reload before saving.")
        variables = {}
        for name, value in body.variables.items():
            if value is None:
                if name not in previous:
                    raise HTTPException(422, "A new variable needs a value")
                variables[name] = previous[name]
            else:
                plain = value.get_secret_value()
                if "\x00" in plain:
                    raise HTTPException(422, "Variable values cannot contain NUL characters")
                variables[name] = plain
        removed = previous.keys() - variables.keys()
        if removed:
            configs = [json.loads(row["config"]) for row in db.execute("SELECT config FROM connections WHERE owner_id=? UNION ALL SELECT config FROM jobs WHERE owner_id=? AND status NOT IN ('succeeded','failed','cancelled')", (user["id"], user["id"]))]
            for config in configs:
                names = {config.get("api_key_env"), config.get("credential_env"), (config.get("connection") or {}).get("api_key_env")}
                names.update(connection.get("api_key_env") for connection in config.get("connections", {}).values())
                if names & removed:
                    raise HTTPException(409, "A variable is used by a connection or active job. Update that connection or finish the job before removing it.")
        encrypted = request.app.state.vault.encrypt(encode(variables).encode()).decode()
        db.execute("INSERT INTO environment VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET revision=excluded.revision,value=excluded.value", (user["id"], revision + 1, encrypted))
    return {"revision": revision + 1, "names": sorted(variables)}

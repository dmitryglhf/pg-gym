from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from postgres_gym import settings

PG_MIRROR = "https://git.postgresql.org/git/postgresql.git"
PRISTINE_COMMIT = "aa14281fdde6b2cc7a794dd02bc128dd0cb20b45"


def checked(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, stdout=sys.stderr, check=True)


def fetch_stand(source: Path) -> dict:
    path = source.resolve() / "stand" / "pg.git"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        mirror = os.environ.get("POSTGRES_GYM_PG_MIRROR", PG_MIRROR)
        checked(["git", "clone", "--bare", mirror, str(path)])
    checked(
        [
            "git",
            "--git-dir=" + str(path),
            "update-ref",
            "refs/postgres-gym/pristine",
            PRISTINE_COMMIT,
        ]
    )
    return {"ok": True, "stand": str(path)}


def build_args(pairs: list[str]) -> dict[str, str]:
    arguments = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key or not key.replace("_", "").isalnum():
            raise ValueError("expected NAME=VALUE, got " + pair)
        arguments[key] = value
    return arguments


def build_task_image(
    source: Path,
    *,
    dockerfile: Path = Path("deploy/task/Dockerfile"),
    tag: str | None = None,
    build_args: dict[str, str] | None = None,
) -> dict:
    tag = tag or settings.TASK_IMAGE
    arguments = dict(build_args or {})
    if checksum := os.environ.get("MARKOV_SHA256"):
        arguments.setdefault("MARKOV_SHA256", checksum)
    command = ["docker", "build", "-f", str(dockerfile), "-t", tag]
    for key, value in arguments.items():
        command += ["--build-arg", key + "=" + value]
    checked([*command, "."], cwd=source.resolve())
    return {"ok": True, "image": tag}

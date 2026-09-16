import os
from pathlib import Path

from .platform import checked


def stand_fetch(source):
    path = source.resolve() / "stand" / "pg.git"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        checked(
            [
                "git",
                "clone",
                "--bare",
                os.environ.get(
                    "POSTGRES_GYM_PG_MIRROR",
                    "https://git.postgresql.org/git/postgresql.git",
                ),
                str(path),
            ]
        )
    checked(
        [
            "git",
            "--git-dir=" + str(path),
            "update-ref",
            "refs/postgres-gym/pristine",
            "aa14281fdde6b2cc7a794dd02bc128dd0cb20b45",
        ]
    )
    return {"ok": True}


def image(source: Path, build_args: list[str] | None = None) -> dict:
    command = [
        "docker",
        "build",
        "-f",
        "deploy/task/Dockerfile",
        "-t",
        os.environ.get("POSTGRES_GYM_TASK_IMAGE", "postgres-gym-task:17.11"),
    ]
    arguments = {}
    if checksum := os.environ.get("MARKOV_SHA256"):
        arguments["MARKOV_SHA256"] = checksum
    for argument in build_args or []:
        key, separator, value = argument.partition("=")
        if not separator or not key or not key.replace("_", "").isalnum():
            raise ValueError("--build-arg expects NAME=VALUE")
        arguments[key] = value
    for key, value in arguments.items():
        command += ["--build-arg", key + "=" + value]
    checked([*command, "."], cwd=source.resolve())
    return {"ok": True}


def platform_images(source: Path, gpu: bool) -> dict:
    from .platform import build_platform_images

    return build_platform_images(source, gpu)

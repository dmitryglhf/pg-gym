from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .. import __version__
from . import CommandError, Instance


def checked(command: list[str], *, cwd: Path | None = None):
    result = subprocess.run(command, cwd=cwd, stdout=sys.stderr, check=False)
    if result.returncode:
        raise CommandError(
            f"Command failed with exit code {result.returncode}: {command[0]}"
        )


def templates() -> Path:
    source = Path(__file__).resolve().parents[3] / "deploy"
    return (
        source
        if source.is_dir()
        else Path(__file__).parent.parent / "templates" / "deploy"
    )


def initialize_instance(
    directory: Path, origin: str, open_registration: bool = False
) -> dict:
    origin_parts = urlsplit(origin)
    if (
        origin_parts.scheme not in {"http", "https"}
        or not origin_parts.hostname
        or origin_parts.path not in {"", "/"}
        or origin_parts.username
        or origin_parts.password
        or origin_parts.query
        or origin_parts.fragment
        or "\n" in origin
    ):
        raise ValueError(
            "--origin must be an HTTP(S) origin without a path or credentials"
        )
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(directory.iterdir()):
        raise ValueError("An instance already exists in this directory")
    import yaml

    instance_name = "pg-gym-" + uuid.uuid4().hex
    template = yaml.safe_load((templates() / "platform" / "compose.yaml").read_text())
    if not isinstance(template, dict) or not isinstance(template.get("services"), dict):
        raise ValueError("Invalid Compose template")  # noqa: TRY004
    replacements = {}
    for category in ("networks", "volumes", "configs", "secrets"):
        for key, resource in template.get(category, {}).items():
            if not isinstance(resource, dict):
                continue
            if resource.get("external"):
                raise ValueError(
                    "Instance templates cannot contain shared external resources"
                )
            if old_name := resource.get("name"):
                replacements[old_name] = instance_name + "-" + key

    def rewrite(value):
        if isinstance(value, str):
            if value in replacements:
                return replacements[value]
            # Compose environment supports both mapping and NAME=value forms.
            key, separator, payload = value.partition("=")
            if separator and payload in replacements:
                return key + "=" + replacements[payload]
            return value
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        return value

    template = rewrite(template)
    template["name"] = instance_name
    for service in template["services"].values():
        service.pop("container_name", None)
    (directory / "compose.yaml").write_text(yaml.safe_dump(template, sort_keys=False))
    (directory / "instance.json").write_text(
        json.dumps({"version": 1, "name": instance_name}, indent=2) + "\n"
    )
    for name in ("secrets", "data", "worker-data", "gpu-worker-data"):
        (directory / name).mkdir(mode=0o700)
    for name, value in (
        ("master.key", base64.urlsafe_b64encode(os.urandom(32))),
        ("worker-token", secrets.token_urlsafe(32).encode()),
        ("registration-token", secrets.token_urlsafe(24).encode()),
    ):
        path = directory / "secrets" / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    socket_path = Path("/var/run/docker.sock")
    docker_gid = socket_path.stat().st_gid if socket_path.exists() else 0
    config = (
        f"PG_GYM_DOCKER_GID={docker_gid}\nPG_GYM_VERSION={__version__}\n"
        f"PG_GYM_ORIGIN={origin}\nPG_GYM_OPEN_REGISTRATION={'1' if open_registration else '0'}\n"
        f"PG_GYM_SECURE_COOKIE={'1' if origin.startswith('https://') else '0'}\n"
        f"PG_GYM_INSTANCE={instance_name}\nPG_GYM_UID={uid}\nPG_GYM_GID={gid}\n"
    )
    (directory / "platform.env").write_text(config)
    result = {
        "instance": instance_name,
        "directory": str(directory),
        "next": f"Run pg-gym platform start --directory {directory}",
    }
    if not open_registration:
        result["registration_code"] = (
            f"pg-gym platform registration-code --directory {directory}"
        )
    return result


def build_platform_images(source: Path, gpu: bool = False) -> dict:
    source = source.expanduser().resolve()
    if not (source / "web" / "deno.json").is_file():
        raise ValueError("--source must point to the complete release repository")
    checked(
        [
            "docker",
            "build",
            "-f",
            "deploy/platform/Dockerfile.api",
            "-t",
            "pg-gym-api:" + __version__,
            ".",
        ],
        cwd=source,
    )
    checked(
        [
            "docker",
            "build",
            "-f",
            "deploy/platform/Dockerfile.web",
            "-t",
            "pg-gym-web:" + __version__,
            ".",
        ],
        cwd=source,
    )
    if gpu:
        checked(
            [
                "docker",
                "build",
                "--build-arg",
                "TRAINING=1",
                "-f",
                "deploy/platform/Dockerfile.api",
                "-t",
                "pg-gym-gpu:" + __version__,
                ".",
            ],
            cwd=source,
        )
        checked(
            [
                "docker",
                "pull",
                os.environ.get("PG_GYM_VLLM_IMAGE", "vllm/vllm-openai:v0.27.0"),
            ]
        )
    return {"images": ["pg-gym-api:" + __version__, "pg-gym-web:" + __version__]}


def compose_platform(
    directory: Path,
    action: str,
    *,
    gpu: bool = False,
    service: str | None = None,
    follow: bool = False,
    timeout: float = 60.0,
) -> dict:
    instance = Instance.load(directory)
    directory = instance.directory
    command = [
        "docker",
        "compose",
        "--project-name",
        instance.name,
        "--env-file",
        str(directory / "platform.env"),
        "-f",
        str(directory / "compose.yaml"),
    ]
    if action == "up":
        if gpu:
            command += ["--profile", "gpu"]
        command += ["up", "-d", "--wait", "--wait-timeout", str(int(timeout))]
    elif action == "down":
        command += ["--profile", "gpu", "down"]
    elif action == "status":
        command += ["ps", "--format", "json"]
    elif action == "logs":
        command += ["logs", "--tail", "200"]
        if follow:
            command.append("--follow")
        if service:
            command.append(service)
    else:
        raise ValueError("Unknown compose action")
    if action == "status":
        result = subprocess.run(
            command, cwd=directory, text=True, capture_output=True, check=False
        )
        if result.returncode:
            raise CommandError("Compose status failed: " + result.stderr.strip())
        text = result.stdout.strip()
        try:
            services = json.loads(text) if text else []
        except json.JSONDecodeError:
            services = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(services, dict):
            services = [services]
        return {"instance": instance.name, "services": services}
    checked(command, cwd=directory)
    return {"ok": True, "instance": instance.name}


def start_platform(
    source: Path,
    directory: Path,
    origin: str = "http://localhost:8000",
    gpu: bool = False,
    open_registration: bool = False,
    timeout: float = 60.0,
) -> dict:
    source = source.expanduser().resolve()
    directory = directory.expanduser().resolve()
    if not (source / "web" / "deno.json").is_file():
        raise ValueError("--source must point to the complete release repository")
    if not (directory / "compose.yaml").exists():
        initialize_instance(directory, origin, open_registration)
    elif not (directory / "platform.env").is_file():
        raise ValueError("Instance is incomplete: platform.env is missing")
    values = dict(
        line.split("=", 1)
        for line in (directory / "platform.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    if open_registration and values.get("PG_GYM_OPEN_REGISTRATION") != "1":
        raise ValueError(
            "For an existing instance, configure PG_GYM_OPEN_REGISTRATION in platform.env and its Compose API environment."
        )
    Instance.load(directory)
    build_platform_images(source, gpu)
    compose_platform(directory, "up", gpu=gpu, timeout=timeout)
    result = {
        "ok": True,
        "directory": str(directory),
        "url": values.get("PG_GYM_ORIGIN", origin),
    }
    if values.get("PG_GYM_OPEN_REGISTRATION") != "1":
        result["registration_code"] = (
            f"pg-gym platform registration-code --directory {directory}"
        )
    return result

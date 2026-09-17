from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

import httpx2

from .. import __version__
from ..config import DEFAULT_API_PORT, DEFAULT_ORIGIN, DEFAULT_PORT
from . import Instance

VLLM_IMAGE = "vllm/vllm-openai:v0.27.0"


def checked(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, stdout=sys.stderr, check=True)


def templates() -> Path:
    source = Path(__file__).resolve().parents[3] / "deploy"
    return (
        source
        if source.is_dir()
        else Path(__file__).parent.parent / "templates" / "deploy"
    )


def origin(value: str) -> str:
    url = httpx2.URL(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.path not in {"", "/"}
        or url.userinfo
        or url.query
        or url.fragment
        or "\n" in value
    ):
        raise ValueError(
            "--origin must be an HTTP(S) origin without a path or credentials"
        )
    return value


def isolated_template(instance_name: str) -> dict:
    """The Compose template with every named resource owned by this instance alone."""
    import yaml

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
    template = renamed(template, replacements)
    template["name"] = instance_name
    for service in template["services"].values():
        service.pop("container_name", None)
    return template


def renamed(value, replacements: dict[str, str]):
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        # Compose environment supports both mapping and NAME=value forms.
        key, separator, payload = value.partition("=")
        if separator and payload in replacements:
            return key + "=" + replacements[payload]
        return value
    if isinstance(value, list):
        return [renamed(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: renamed(item, replacements) for key, item in value.items()}
    return value


def write_secrets(directory: Path) -> None:
    for name, value in (
        ("master.key", base64.urlsafe_b64encode(os.urandom(32))),
        ("worker-token", secrets.token_urlsafe(32).encode()),
        ("registration-token", secrets.token_urlsafe(24).encode()),
    ):
        descriptor = os.open(
            directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)


def docker_gid() -> int:
    """The group the workers join to reach the Docker socket.

    Docker Desktop mounts the socket into its VM as root:root, so the group of
    the macOS socket file means nothing inside the containers; the root group
    is the one that works there.
    """
    socket_path = Path("/var/run/docker.sock")
    if sys.platform == "darwin" or not socket_path.exists():
        return 0
    return socket_path.stat().st_gid


def environment(instance_name: str, origin: str, open_registration: bool) -> str:
    uid = os.getuid() if hasattr(os, "getuid") else 1000
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    return (
        f"PG_GYM_DOCKER_GID={docker_gid()}\nPG_GYM_VERSION={__version__}\n"
        f"PG_GYM_PORT={DEFAULT_PORT}\nPG_GYM_API_PORT={DEFAULT_API_PORT}\n"
        f"PG_GYM_ORIGIN={origin}\nPG_GYM_OPEN_REGISTRATION={'1' if open_registration else '0'}\n"
        f"PG_GYM_SECURE_COOKIE={'1' if origin.startswith('https://') else '0'}\n"
        f"PG_GYM_INSTANCE={instance_name}\nPG_GYM_UID={uid}\nPG_GYM_GID={gid}\n"
    )


def read_environment(directory: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in (directory / "platform.env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def refresh_instance(instance: Instance) -> list[str]:
    """Bring the files a release derives for an instance up to date.

    `compose.yaml` is rendered from the release template, so a newer CLI
    rewrites it. `platform.env` keeps the operator's values and only gains the
    keys a newer template reads; on macOS the Docker group is always root.
    Returns the names of the files that changed.
    """
    import yaml

    changed = []
    template = isolated_template(instance.name)
    if yaml.safe_load(instance.compose.read_text()) != template:
        instance.compose.write_text(yaml.safe_dump(template, sort_keys=False))
        changed.append("compose.yaml")
    values = read_environment(instance.directory)
    defaults = dict(
        line.split("=", 1)
        for line in environment(
            instance.name,
            values.get("PG_GYM_ORIGIN", DEFAULT_ORIGIN),
            values.get("PG_GYM_OPEN_REGISTRATION") == "1",
        ).splitlines()
    )
    before = instance.environment.read_text()
    lines = before.splitlines()
    if sys.platform == "darwin" and values.get("PG_GYM_DOCKER_GID") not in (None, "0"):
        lines = [
            "PG_GYM_DOCKER_GID=0" if line.startswith("PG_GYM_DOCKER_GID=") else line
            for line in lines
        ]
    lines += [f"{key}={value}" for key, value in defaults.items() if key not in values]
    after = "\n".join(lines) + "\n"
    if after != before:
        instance.environment.write_text(after)
        changed.append("platform.env")
    return changed


def initialize_instance(
    directory: Path, url: str, open_registration: bool = False
) -> dict:
    url = origin(url)
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(directory.iterdir()):
        raise ValueError("An instance already exists in this directory")
    import yaml

    instance_name = "pg-gym-" + uuid.uuid4().hex
    template = isolated_template(instance_name)
    (directory / "compose.yaml").write_text(yaml.safe_dump(template, sort_keys=False))
    (directory / "instance.json").write_text(
        json.dumps({"version": 1, "name": instance_name}, indent=2) + "\n"
    )
    for name in ("secrets", "data", "worker-data", "gpu-worker-data"):
        (directory / name).mkdir(mode=0o700)
    write_secrets(directory / "secrets")
    (directory / "platform.env").write_text(
        environment(instance_name, url, open_registration)
    )
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


def build_image(source: Path, dockerfile: str, tag: str, *build_args: str) -> None:
    command = ["docker", "build", "-f", dockerfile, "-t", tag]
    for argument in build_args:
        command += ["--build-arg", argument]
    checked([*command, "."], cwd=source)


def build_platform_images(source: Path, gpu: bool = False) -> dict:
    source = source.expanduser().resolve()
    if not (source / "web" / "deno.json").is_file():
        raise ValueError("--source must point to the complete release repository")
    api, web = "pg-gym-api:" + __version__, "pg-gym-web:" + __version__
    build_image(source, "deploy/platform/Dockerfile.api", api)
    build_image(source, "deploy/platform/Dockerfile.web", web)
    if gpu:
        build_image(
            source,
            "deploy/platform/Dockerfile.api",
            "pg-gym-gpu:" + __version__,
            "TRAINING=1",
        )
        checked(["docker", "pull", os.environ.get("PG_GYM_VLLM_IMAGE", VLLM_IMAGE)])
    return {"images": [api, web]}


def compose_command(instance: Instance) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        instance.name,
        "--env-file",
        str(instance.environment),
        "-f",
        str(instance.compose),
    ]


def compose_status(directory: Path) -> dict:
    instance = Instance.load(directory)
    result = subprocess.run(
        [*compose_command(instance), "ps", "--format", "json"],
        cwd=instance.directory,
        text=True,
        capture_output=True,
        check=True,
    )
    text = result.stdout.strip()
    try:
        services = json.loads(text) if text else []
    except json.JSONDecodeError:
        services = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(services, dict):
        services = [services]
    return {"instance": instance.name, "services": services}


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
    command = compose_command(instance)
    if action == "up":
        if gpu:
            command += ["--profile", "gpu"]
        command += ["up", "-d", "--wait", "--wait-timeout", str(int(timeout))]
    elif action == "down":
        command += ["--profile", "gpu", "down"]
    elif action == "logs":
        command += ["logs", "--tail", "200"]
        if follow:
            command.append("--follow")
        if service:
            command.append(service)
    else:
        raise ValueError("Unknown compose action")
    checked(command, cwd=instance.directory)
    return {"ok": True, "instance": instance.name}


def start_platform(
    source: Path,
    directory: Path,
    url: str = DEFAULT_ORIGIN,
    gpu: bool = False,
    open_registration: bool = False,
    timeout: float = 60.0,
) -> dict:
    source = source.expanduser().resolve()
    directory = directory.expanduser().resolve()
    if not (source / "web" / "deno.json").is_file():
        raise ValueError("--source must point to the complete release repository")
    if not (directory / "compose.yaml").exists():
        initialize_instance(directory, url, open_registration)
    elif not (directory / "platform.env").is_file():
        raise ValueError("Instance is incomplete: platform.env is missing")
    values = read_environment(directory)
    if open_registration and values.get("PG_GYM_OPEN_REGISTRATION") != "1":
        raise ValueError(
            "For an existing instance, configure PG_GYM_OPEN_REGISTRATION in platform.env "
            "and its Compose API environment."
        )
    refreshed = refresh_instance(Instance.load(directory))
    build_platform_images(source, gpu)
    compose_platform(directory, "up", gpu=gpu, timeout=timeout)
    result = {
        "ok": True,
        "directory": str(directory),
        "url": values.get("PG_GYM_ORIGIN", url),
    }
    if refreshed:
        result["refreshed"] = refreshed
    if values.get("PG_GYM_OPEN_REGISTRATION") != "1":
        result["registration_code"] = (
            f"pg-gym platform registration-code --directory {directory}"
        )
    return result

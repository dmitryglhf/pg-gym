from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from postgres_gym.cli import emit, runtime

from ..config import DEFAULT_ORIGIN
from ..instance import Instance, compose, storage

app = typer.Typer(help="Manage an isolated local platform instance.")
Directory = Annotated[
    Path,
    typer.Option(
        "--directory", help="Instance directory for Compose, data and secrets."
    ),
]
Source = Annotated[
    Path, typer.Option("--source", help="Release repository to build images from.")
]
Origin = Annotated[
    str,
    typer.Option(
        "--origin", envvar="PG_GYM_ORIGIN", help="Public HTTP(S) origin of the web UI."
    ),
]
OpenRegistration = Annotated[
    bool,
    typer.Option(
        "--open-registration", help="Allow sign-up without a registration code."
    ),
]
Gpu = Annotated[
    bool, typer.Option("--gpu", help="Include the GPU worker and vLLM images.")
]
INSTANCE = Path("pg-gym-instance")


@app.command("init")
def init(
    ctx: typer.Context,
    directory: Directory = INSTANCE,
    origin: Origin = DEFAULT_ORIGIN,
    open_registration: OpenRegistration = False,
) -> None:
    """Create an instance directory with Compose files and fresh secrets."""
    emit(ctx, compose.initialize_instance(directory, origin, open_registration))


@app.command("start")
def start(
    ctx: typer.Context,
    directory: Directory = INSTANCE,
    source: Source = Path("."),
    origin: Origin = DEFAULT_ORIGIN,
    gpu: Gpu = False,
    open_registration: OpenRegistration = False,
) -> None:
    """Initialize if needed, build images and start the instance."""
    result = compose.start_platform(
        source, directory, origin, gpu, open_registration, runtime(ctx).wait_timeout
    )
    emit(ctx, result)


@app.command("stop")
def stop(ctx: typer.Context, directory: Directory = INSTANCE) -> None:
    """Stop the instance containers."""
    emit(
        ctx,
        compose.compose_platform(directory, "down", timeout=runtime(ctx).wait_timeout),
    )


@app.command("status")
def status(ctx: typer.Context, directory: Directory = INSTANCE) -> None:
    """Show instance services."""
    emit(ctx, compose.compose_status(directory))


@app.command("logs")
def logs(
    ctx: typer.Context,
    directory: Directory = INSTANCE,
    service: Annotated[
        str | None, typer.Option("--service", help="Only this service.")
    ] = None,
    follow: Annotated[bool, typer.Option("--follow", help="Keep streaming.")] = False,
) -> None:
    """Print service logs."""
    emit(
        ctx, compose.compose_platform(directory, "logs", service=service, follow=follow)
    )


@app.command("images")
def images(ctx: typer.Context, source: Source = Path("."), gpu: Gpu = False) -> None:
    """Build the API and web images without starting anything."""
    emit(ctx, compose.build_platform_images(source, gpu))


@app.command("backup")
def backup(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Zip archive to create.")],
    directory: Directory = INSTANCE,
) -> None:
    """Archive the database, secrets and artifacts."""
    emit(ctx, storage.backup(Instance.load(directory), path))


@app.command("restore")
def restore(
    ctx: typer.Context,
    path: Annotated[Path, typer.Argument(help="Backup archive.")],
    directory: Directory = INSTANCE,
    origin: Origin = DEFAULT_ORIGIN,
    open_registration: OpenRegistration = False,
) -> None:
    """Restore a backup into a new instance directory."""
    emit(ctx, storage.restore(path, directory, origin, open_registration))


@app.command("registration-code")
def registration_code(ctx: typer.Context, directory: Directory = INSTANCE) -> None:
    """Print the code new accounts need."""
    code = (Instance.load(directory).secrets / "registration-token").read_text().strip()
    emit(ctx, {"registration_code": code})


@app.command("reset-password")
def reset_password(
    ctx: typer.Context,
    username: Annotated[str, typer.Argument(help="Account name.")],
    directory: Directory = INSTANCE,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the new password from stdin.")
    ] = False,
) -> None:
    """Set a new password and revoke the account's sessions."""
    password = (
        sys.stdin.readline().rstrip("\n")
        if password_stdin
        else typer.prompt("New password", hide_input=True)
    )
    emit(ctx, storage.reset_password(Instance.load(directory), username, password))

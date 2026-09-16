import sys
from pathlib import Path
from typing import Annotated

import typer
from postgres_gym.cli.prompts import prompt_value

from .. import platform, storage
from ..instance import Instance
from ..output import show
from ..runtime import current

app = typer.Typer(help="Manage an isolated local instance.")
Directory = Annotated[
    Path,
    typer.Option(
        "--directory", help="Instance directory for Compose, data and secrets."
    ),
]


@app.command("init")
def init(
    directory: Directory = Path("pg-gym-instance"),
    origin: Annotated[str, typer.Option("--origin")] = "http://localhost:8000",
    open_registration: Annotated[bool, typer.Option("--open-registration")] = False,
) -> None:
    show(platform.initialize_instance(directory, origin, open_registration))


@app.command("start")
def start(
    directory: Directory = Path("pg-gym-instance"),
    source: Annotated[Path, typer.Option("--source")] = Path("."),
    origin: Annotated[str, typer.Option("--origin")] = "http://localhost:8000",
    gpu: Annotated[bool, typer.Option("--gpu")] = False,
    open_registration: Annotated[bool, typer.Option("--open-registration")] = False,
) -> None:
    show(
        platform.start_platform(
            source, directory, origin, gpu, open_registration, current().wait_timeout
        )
    )


@app.command("stop")
def stop(directory: Directory = Path("pg-gym-instance")) -> None:
    show(platform.compose_platform(directory, "down", timeout=current().wait_timeout))


@app.command("status")
def status(directory: Directory = Path("pg-gym-instance")) -> None:
    show(platform.compose_platform(directory, "status"))


@app.command("logs")
def logs(
    directory: Directory = Path("pg-gym-instance"),
    service: Annotated[str | None, typer.Option("--service")] = None,
    follow: Annotated[bool, typer.Option("--follow")] = False,
) -> None:
    show(platform.compose_platform(directory, "logs", service=service, follow=follow))


@app.command("backup")
def backup(path: Path, directory: Directory = Path("pg-gym-instance")) -> None:
    show(storage.backup(Instance.load(directory), path))


@app.command("restore")
def restore(
    path: Path,
    directory: Directory = Path("pg-gym-instance"),
    origin: Annotated[str, typer.Option("--origin")] = "http://localhost:8000",
    open_registration: Annotated[bool, typer.Option("--open-registration")] = False,
) -> None:
    show(storage.restore(path, directory, origin, open_registration))


@app.command("registration-code")
def registration_code(directory: Directory = Path("pg-gym-instance")) -> None:
    show(
        {
            "registration_code": (
                Instance.load(directory).secrets / "registration-token"
            )
            .read_text()
            .strip()
        }
    )


@app.command("reset-password")
def reset_password(
    username: str,
    directory: Directory = Path("pg-gym-instance"),
    password_stdin: Annotated[bool, typer.Option("--password-stdin")] = False,
) -> None:
    password = (
        sys.stdin.readline().rstrip("\n")
        if password_stdin
        else prompt_value("New password", secret=True)
    )
    show(storage.reset_password(Instance.load(directory), username, password))

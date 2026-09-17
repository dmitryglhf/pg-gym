from __future__ import annotations

import math
from typing import Annotated

import typer

from postgres_gym import __version__

from . import benchmark, dev
from ._errors import Group
from ._output import OutputMode, Runtime, emit


def create_app() -> typer.Typer:
    from postgres_gym_platform.cli import groups

    application = typer.Typer(
        name="pg-gym",
        cls=Group,
        help="Local Postgres Gym and remote platform commands.",
        no_args_is_help=True,
        pretty_exceptions_enable=False,
    )
    application.callback()(root)
    application.command("doctor")(doctor)
    local = {"benchmark": benchmark.app, "dev": dev.app}
    for name, group in local.items():
        application.add_typer(group, name=name)
    for name, group in groups():
        if name in local:
            local[name].add_typer(group)
        else:
            application.add_typer(group, name=name)
    return application


def show_version(value: bool) -> None:
    if value:
        typer.echo(f"pg-gym {__version__}")
        raise typer.Exit()


def positive(value: float, option: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise typer.BadParameter("must be finite and positive", param_hint=option)
    return value


def root(
    ctx: typer.Context,
    output: Annotated[
        OutputMode,
        typer.Option("--output", help="Result format: table, json or jsonl."),
    ] = OutputMode.table,
    json_output: Annotated[
        bool, typer.Option("--json", help="Shorthand for --output json.")
    ] = False,
    jsonl_output: Annotated[
        bool, typer.Option("--jsonl", help="Shorthand for --output jsonl.")
    ] = False,
    no_color: Annotated[
        bool, typer.Option("--no-color", help="Plain tables without color.")
    ] = False,
    context: Annotated[
        str | None,
        typer.Option(
            "--context", help="Platform context to use instead of the active one."
        ),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Seconds to wait for one platform request."),
    ] = 60.0,
    wait_timeout: Annotated[
        float,
        typer.Option(
            "--wait-timeout", help="Seconds to wait for a remote job with --wait."
        ),
    ] = 600.0,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=show_version, is_eager=True, help="Print the version."
        ),
    ] = False,
) -> None:
    if json_output and jsonl_output:
        raise typer.BadParameter(
            "--json and --jsonl cannot be used together", param_hint="--jsonl"
        )
    if json_output:
        output = OutputMode.json
    elif jsonl_output:
        output = OutputMode.jsonl
    ctx.obj = Runtime(
        output,
        no_color,
        context,
        positive(timeout, "--timeout"),
        positive(wait_timeout, "--wait-timeout"),
    )


def doctor(ctx: typer.Context) -> None:
    """Report the local toolchain: version, Python, Docker and installed suites."""
    import shutil
    import sys

    from postgres_gym import settings
    from postgres_gym.core import registry

    emit(
        ctx,
        {
            "version": __version__,
            "python": sys.version.split()[0],
            "root": str(settings.ROOT),
            "docker": shutil.which("docker"),
            "nvidia_smi": shutil.which("nvidia-smi"),
            "suites": registry.names(),
        },
    )


app = create_app()


def main() -> None:
    app(prog_name="pg-gym")

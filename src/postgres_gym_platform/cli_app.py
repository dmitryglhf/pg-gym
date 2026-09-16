"""Composition root: command registration and invocation-wide options only."""

from __future__ import annotations

import math
from typing import Annotated

import typer

from . import __version__
from .cli.commands import (
    artifacts,
    auth,
    benchmark,
    catalog,
    context,
    dev,
    inference,
    jobs,
    models,
    platform,
    rl,
    server,
)
from .cli.commands.doctor import doctor
from .cli.commands.resources import resource_group
from .cli.errors import CliGroup, execute
from .cli.output import OutputMode
from .cli.runtime import CliRuntime


def create_app() -> typer.Typer:
    application = typer.Typer(
        name="pg-gym",
        cls=CliGroup,
        help="Local Postgres Gym and remote platform commands.",
        no_args_is_help=True,
        add_completion=False,
        pretty_exceptions_enable=False,
    )
    for name, group in (
        ("platform", platform.app),
        ("benchmark", benchmark.app),
        ("jobs", jobs.app),
        ("context", context.app),
        ("auth", auth.app),
        ("suites", catalog.suites),
        ("tasks", catalog.tasks),
        ("models", models.app),
        ("artifacts", artifacts.app),
        ("inference", inference.app),
        ("rl", rl.app),
        ("dev", dev.app),
        ("server", server.app),
    ):
        application.add_typer(group, name=name)
    for kind in ("connections", "credentials", "profiles"):
        application.add_typer(resource_group(kind), name=kind)
    application.callback(invoke_without_command=True)(root)
    application.command("doctor")(doctor)
    return application


def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", is_eager=True)] = False,
    context: Annotated[str | None, typer.Option("--context")] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.table,
    json_output: Annotated[
        bool, typer.Option("--json", help="Shorthand for --output json.")
    ] = False,
    jsonl_output: Annotated[
        bool, typer.Option("--jsonl", help="Shorthand for --output jsonl.")
    ] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 60.0,
    wait_timeout: Annotated[float, typer.Option("--wait-timeout")] = 600.0,
    no_color: Annotated[bool, typer.Option("--no-color")] = False,
) -> None:
    if version:
        typer.echo(f"pg-gym {__version__}")
        raise typer.Exit()
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("--timeout must be finite and positive")
    if json_output and jsonl_output:
        raise ValueError("--json and --jsonl cannot be used together")
    if json_output:
        output = OutputMode.json
    elif jsonl_output:
        output = OutputMode.jsonl
    if not math.isfinite(wait_timeout) or wait_timeout <= 0:
        raise ValueError("--wait-timeout must be finite and positive")
    ctx.obj = CliRuntime(output, no_color, context, timeout, wait_timeout)


app = create_app()


def main(argv: list[str] | None = None) -> None:
    execute(app, argv)


if __name__ == "__main__":
    main()

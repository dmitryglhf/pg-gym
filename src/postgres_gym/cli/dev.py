from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ._errors import ExitCode
from ._output import emit

app = typer.Typer(help="Build the task image and exercise suites locally.")

Source = Annotated[
    Path, typer.Option("--source", help="Repository checkout to build from.")
]
Suite = Annotated[str, typer.Option("--suite", help="Suite identifier.")]
Task = Annotated[str, typer.Option("--task", help="Task name inside the suite.")]


@app.command("stand-fetch")
def stand_fetch(ctx: typer.Context, source: Source = Path(".")) -> None:
    """Clone the PostgreSQL mirror into stand/pg.git and pin the pristine ref."""
    from postgres_gym.execution.image import fetch_stand

    emit(ctx, fetch_stand(source))


@app.command("image")
def image(
    ctx: typer.Context,
    source: Source = Path("."),
    dockerfile: Annotated[
        Path, typer.Option("--dockerfile", help="Dockerfile relative to --source.")
    ] = Path("deploy/task/Dockerfile"),
    tag: Annotated[
        str | None,
        typer.Option("--tag", help="Image tag; defaults to POSTGRES_GYM_TASK_IMAGE."),
    ] = None,
    build_arg: Annotated[
        list[str] | None,
        typer.Option("--build-arg", help="NAME=VALUE passed to docker build."),
    ] = None,
) -> None:
    """Build the task image used for scored runs."""
    from postgres_gym.execution.image import build_args, build_task_image

    try:
        arguments = build_args(build_arg or [])
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--build-arg") from None
    emit(
        ctx,
        build_task_image(source, dockerfile=dockerfile, tag=tag, build_args=arguments),
    )


@app.command("suite-check")
def suite_check(ctx: typer.Context, suite: Suite = "sql-function-set") -> None:
    """Validate suite data and report the first problems found."""
    from postgres_gym.core import data, registry

    issues = data.validate(registry.load(suite))
    if issues:
        raise ValueError("\n".join(issues))
    emit(ctx, {"ok": True, "suite": suite})


@app.command("verify")
def verify(
    ctx: typer.Context, suite: Suite = "sql-function-set", task: Task = "area"
) -> None:
    """Check that the oracle solution of one task passes its grader."""
    from postgres_gym import Gym

    emit(ctx, Gym(suite).verify(task))


@app.command("selftest")
def selftest(
    ctx: typer.Context, suite: Suite = "sql-function-set", task: Task = "area"
) -> None:
    """Run the replay, noop, cheat and probe agents on one task."""
    from postgres_gym import Gym

    results = {
        agent: Gym(suite).run(task, agent)
        for agent in ("replay", "noop", "cheat", "probe")
    }
    emit(
        ctx,
        {
            agent: {"record": result.record, "execution_ok": result.ok}
            for agent, result in results.items()
        },
    )
    if any(not result.ok for result in results.values()):
        raise typer.Exit(ExitCode.FAILURE)

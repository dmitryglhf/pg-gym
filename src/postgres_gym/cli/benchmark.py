from __future__ import annotations

import sys
from contextlib import redirect_stdout
from typing import Annotated

import typer

from ._errors import CliError, ExitCode
from ._output import emit

app = typer.Typer(help="Run benchmarks locally or on the platform.")


@app.command("run")
def run(
    ctx: typer.Context,
    suite: Annotated[
        str, typer.Argument(help="Suite identifier, for example sql-function-set.")
    ],
    task: Annotated[
        list[str] | None,
        typer.Option("--task", help="Task to run; repeat for several."),
    ] = None,
    split: Annotated[
        str | None,
        typer.Option(
            "--split", help="Run only tasks of this split, for example train."
        ),
    ] = None,
    agent: Annotated[
        str,
        typer.Option(
            "--agent", help="Agent name: cli:markov, cli:opencode, replay, noop."
        ),
    ] = "cli:markov",
    level: Annotated[
        str, typer.Option("--level", help="Prompt level, L0 to L2.")
    ] = "L0",
    since: Annotated[
        str | None,
        typer.Option("--since", help="Skip tasks recorded since this ISO timestamp."),
    ] = None,
    judge: Annotated[
        bool, typer.Option("--judge", help="Score submissions with the LLM judge.")
    ] = False,
    judge_model: Annotated[
        str | None, typer.Option("--judge-model", help="Judge model name.")
    ] = None,
    judge_base_url: Annotated[
        str | None,
        typer.Option("--judge-base-url", help="OpenAI-compatible judge endpoint."),
    ] = None,
) -> None:
    """Run tasks in disposable containers and report the tasks whose execution failed."""
    from postgres_gym import Gym
    from postgres_gym.benchmark import run as execute

    gym = Gym(suite)
    names = gym.tasks(split)
    unknown = [name for name in task or [] if name not in names]
    if unknown:
        raise typer.BadParameter(
            "not in the requested split: " + ", ".join(unknown), param_hint="--task"
        )
    if not (task or names):
        raise CliError("No runnable tasks", ExitCode.INVALID_INPUT)
    # Progress lines belong on stderr so that stdout carries only the result.
    with redirect_stdout(sys.stderr):
        errors = execute(
            gym,
            agent,
            level,
            tasks=task,
            split=split,
            since=since,
            judge=judge,
            judge_model=judge_model,
            judge_base_url=judge_base_url,
        )
    emit(ctx, {"suite": suite, "execution_errors": errors})
    if errors:
        raise typer.Exit(ExitCode.FAILURE)

import sys
from contextlib import redirect_stdout
from typing import Annotated

import typer

from .output import emit
from .runtime import context

app = typer.Typer(help="Local benchmark commands.")


def run_local(suite: str, agent: str, level: str, **options) -> dict:
    from postgres_gym import Gym
    from postgres_gym.benchmark import run as execute

    gym = Gym(suite)
    selected = options.get("tasks")
    if selected and any(
        task not in gym.tasks(options.get("split")) for task in selected
    ):
        raise ValueError("Select tasks within the requested split")
    if not (selected or gym.tasks(options.get("split"))):
        raise ValueError("No runnable tasks")
    with redirect_stdout(sys.stderr):
        errors = execute(gym, agent, level, **options)
    return {"suite": suite, "execution_errors": errors}


@app.command("run")
def run(
    suite: str,
    task: Annotated[list[str] | None, typer.Option("--task")] = None,
    split: Annotated[str | None, typer.Option("--split")] = None,
    agent: Annotated[str, typer.Option("--agent")] = "cli:markov",
    level: Annotated[str, typer.Option("--level")] = "L0",
    since: Annotated[str | None, typer.Option("--since")] = None,
    judge: Annotated[bool, typer.Option("--judge")] = False,
    judge_model: Annotated[str | None, typer.Option("--judge-model")] = None,
    judge_base_url: Annotated[str | None, typer.Option("--judge-base-url")] = None,
) -> None:
    result = run_local(
        suite,
        agent,
        level,
        tasks=task,
        split=split,
        since=since,
        judge=judge,
        judge_model=judge_model,
        judge_base_url=judge_base_url,
    )
    emit(result, context())
    if result["execution_errors"]:
        raise typer.Exit(1)

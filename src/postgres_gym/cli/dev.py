from typing import Annotated

import typer

from .output import emit
from .runtime import context

app = typer.Typer(help="Inspect and exercise local Gym suites.")


@app.command("suite-check")
def suite_check(
    suite: Annotated[str, typer.Option("--suite")] = "sql-function-set",
) -> None:
    from postgres_gym.core import data, registry

    issues = data.validate(registry.load(suite))
    if issues:
        raise ValueError("\n".join(issues))
    emit({"ok": True, "suite": suite}, context())


@app.command("verify")
def verify(
    suite: Annotated[str, typer.Option("--suite")] = "sql-function-set",
    task: Annotated[str, typer.Option("--task")] = "area",
) -> None:
    from postgres_gym import Gym

    emit(Gym(suite).verify(task), context())


@app.command("selftest")
def selftest(
    suite: Annotated[str, typer.Option("--suite")] = "sql-function-set",
    task: Annotated[str, typer.Option("--task")] = "area",
) -> None:
    from postgres_gym import Gym

    results = {
        agent: Gym(suite).run(task, agent)
        for agent in ("replay", "noop", "cheat", "probe")
    }
    emit(
        {
            agent: {"record": result.record, "execution_ok": result.ok}
            for agent, result in results.items()
        },
        context(),
    )
    if any(not result.ok for result in results.values()):
        raise typer.Exit(1)

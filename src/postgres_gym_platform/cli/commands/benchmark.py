from pathlib import Path
from typing import Annotated

import typer

from postgres_gym.cli.benchmark import run as run_local

from ...client import specs
from ..http import request
from ..jobs import submit_remote
from ..output import show

app = typer.Typer(help="Run locally or submit a remote benchmark.")


@app.command("submit")
def submit(
    suite: Annotated[str | None, typer.Argument()] = None,
    task: Annotated[list[str] | None, typer.Option("--task")] = None,
    split: Annotated[str | None, typer.Option("--split")] = None,
    harness: Annotated[str | None, typer.Option("--harness")] = None,
    connection: Annotated[str | None, typer.Option("--connection")] = None,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    min_solve_rate: Annotated[
        float | None, typer.Option("--min-solve-rate", min=0, max=1)
    ] = None,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    if min_solve_rate is not None and not wait:
        raise ValueError("--min-solve-rate requires --wait")
    body = specs.build(
        "benchmark",
        config,
        suite=suite,
        tasks=task,
        split=split,
        harness=harness,
        connection_id=connection,
        profile_id=profile,
        name=name,
    )
    result = submit_remote("/benchmarks", body, wait, idempotency_key)
    show(result)
    if (
        min_solve_rate is not None
        and (result.get("result") or {}).get("solve_rate", 0) < min_solve_rate
    ):
        raise typer.Exit(6)


@app.command("inspect")
def inspect(identifier: str) -> None:
    show(request("GET", "/jobs/" + identifier))


app.command("run")(run_local)

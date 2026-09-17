from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import ExitCode, emit

from ._http import Config, IdempotencyKey, Wait, request, submit

app = typer.Typer()


@app.command("submit")
def submit_benchmark(
    ctx: typer.Context,
    suite: Annotated[str | None, typer.Argument(help="Suite identifier.")] = None,
    task: Annotated[
        list[str] | None,
        typer.Option("--task", help="Task to run; repeat for several."),
    ] = None,
    split: Annotated[
        str | None, typer.Option("--split", help="Run only this split.")
    ] = None,
    harness: Annotated[
        str | None, typer.Option("--harness", help="Agent harness: markov or opencode.")
    ] = None,
    connection: Annotated[
        str | None, typer.Option("--connection", help="Model connection id.")
    ] = None,
    profile: Annotated[
        str | None, typer.Option("--profile", help="Harness profile id.")
    ] = None,
    config: Config = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Display name of the run.")
    ] = None,
    wait: Wait = False,
    min_solve_rate: Annotated[
        float | None,
        typer.Option(
            "--min-solve-rate",
            min=0,
            max=1,
            help="Exit 6 below this solve rate; needs --wait.",
        ),
    ] = None,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Submit a benchmark run to the platform."""
    from ..client.specs import build

    if min_solve_rate is not None and not wait:
        raise typer.BadParameter("requires --wait", param_hint="--min-solve-rate")
    body = build(
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
    result = submit(ctx, "/benchmarks", body, wait, idempotency_key)
    emit(ctx, result)
    if (
        min_solve_rate is not None
        and (result.get("result") or {}).get("solve_rate", 0) < min_solve_rate
    ):
        raise typer.Exit(ExitCode.THRESHOLD)


@app.command("inspect")
def inspect(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="Benchmark job id.")],
) -> None:
    """Show a submitted benchmark job."""
    emit(ctx, request(ctx, "GET", "/jobs/" + identifier))

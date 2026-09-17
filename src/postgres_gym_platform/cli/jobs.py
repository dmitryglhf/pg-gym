from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import CliError, emit, runtime

from ..client.jobs import logs as job_logs
from ..client.jobs import wait_for_terminal_job
from ._http import (
    AllPages,
    Cursor,
    IdempotencyKey,
    Limit,
    Wait,
    connection,
    listing,
    request,
    submit,
)

app = typer.Typer(help="Inspect jobs, wait, stream logs, cancel and retry.")
Job = Annotated[str, typer.Argument(help="Job id.")]


@app.command("list")
def list_jobs(
    ctx: typer.Context,
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Only jobs of this kind, for example benchmark."),
    ] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    all_pages: AllPages = False,
) -> None:
    """List jobs, newest first."""
    emit(ctx, listing(ctx, "/jobs", limit, cursor, all_pages, kind=kind))


@app.command("show")
def show(ctx: typer.Context, identifier: Job) -> None:
    """Show one job."""
    emit(ctx, request(ctx, "GET", "/jobs/" + identifier))


@app.command("wait")
def wait(ctx: typer.Context, identifier: Job) -> None:
    """Block until the job reaches a terminal status; exit 1 unless it succeeded."""
    with connection(ctx) as client:
        result = wait_for_terminal_job(client, identifier, runtime(ctx).wait_timeout)
    emit(ctx, result)
    if result.get("status") != "succeeded":
        raise CliError("Job did not succeed: " + identifier)


@app.command("logs")
def logs(
    ctx: typer.Context,
    identifier: Job,
    follow: Annotated[
        bool, typer.Option("--follow", help="Keep streaming until the job ends.")
    ] = False,
    after: Annotated[
        int, typer.Option("--after", min=0, help="Start after this event number.")
    ] = 0,
) -> None:
    """Print job events."""
    with connection(ctx) as client:
        for event in job_logs(client, identifier, follow=follow, after=after):
            emit(ctx, event)


@app.command("cancel")
def cancel(ctx: typer.Context, identifier: Job) -> None:
    """Request cancellation of a running job."""
    emit(ctx, request(ctx, "POST", f"/jobs/{identifier}/cancel"))


@app.command("retry")
def retry(
    ctx: typer.Context,
    identifier: Job,
    wait: Wait = False,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Submit a new job with the same specification."""
    emit(ctx, submit(ctx, f"/jobs/{identifier}/retries", {}, wait, idempotency_key))

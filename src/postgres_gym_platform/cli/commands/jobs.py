from typing import Annotated

import typer

from .. import jobs
from ..errors import JobFailure
from ..http import connection, listing, request
from ..output import show
from ..runtime import current

app = typer.Typer(help="Inspect jobs, wait, stream logs, cancel and retry.")


@app.command("list")
def list_jobs(
    kind: Annotated[str | None, typer.Option("--kind")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    all_pages: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    show(listing("/jobs", limit, cursor, all_pages, kind=kind))


@app.command("show")
def show_job(identifier: str) -> None:
    show(request("GET", "/jobs/" + identifier))


@app.command("wait")
def wait(identifier: str) -> None:
    with connection() as client:
        result = jobs.wait_for_terminal_job(client, identifier, current().wait_timeout)
    show(result)
    if result.get("status") != "succeeded":
        raise JobFailure("Job did not succeed: " + identifier)


@app.command("logs")
def logs(
    identifier: str,
    follow: Annotated[bool, typer.Option("--follow")] = False,
    after: Annotated[int, typer.Option("--after", min=0)] = 0,
) -> None:
    with connection() as client:
        for event in jobs.logs(client, identifier, follow=follow, after=after):
            show(event)


@app.command("cancel")
def cancel(identifier: str) -> None:
    show(request("POST", f"/jobs/{identifier}/cancel"))


@app.command("retry")
def retry(
    identifier: str,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    show(jobs.submit_remote(f"/jobs/{identifier}/retries", {}, wait, idempotency_key))

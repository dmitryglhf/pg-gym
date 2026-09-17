from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import httpx2
import typer

from postgres_gym.cli import CliError, ExitCode, runtime

from ..client import ApiError, Client, JobError, contexts
from ..client.jobs import submit as submit_job

Limit = Annotated[int, typer.Option("--limit", min=1, max=200, help="Items per page.")]
Cursor = Annotated[
    str | None, typer.Option("--cursor", help="Continue from this page cursor.")
]
AllPages = Annotated[
    bool, typer.Option("--all", help="Follow cursors until the last page.")
]
Wait = Annotated[bool, typer.Option("--wait", help="Block until the job finishes.")]
IdempotencyKey = Annotated[
    str | None,
    typer.Option("--idempotency-key", help="Reuse to retry a submission safely."),
]
Config = Annotated[
    Path | None,
    typer.Option("--config", help="JSON or YAML file with the full job specification."),
]


def exit_code(error: ApiError) -> ExitCode:
    if error.status in {401, 403}:
        return ExitCode.AUTH
    return ExitCode.INVALID_INPUT if error.status in {400, 422} else ExitCode.FAILURE


@contextmanager
def failures() -> Iterator[None]:
    """Maps client failures onto the CLI exit codes."""
    try:
        yield
    except ApiError as exc:
        raise CliError(str(exc), exit_code(exc)) from None
    except httpx2.HTTPError as exc:
        raise CliError(type(exc).__name__, ExitCode.TRANSPORT) from None
    except TimeoutError as exc:
        raise CliError(str(exc), ExitCode.WAIT_TIMEOUT) from None
    except JobError as exc:
        raise CliError(str(exc)) from None


@contextmanager
def session(ctx: typer.Context) -> Iterator[tuple[Client, dict, str | None]]:
    """Client for the invocation's context together with the stored contexts and the context name."""
    settings = runtime(ctx)
    with failures():
        client, values, name = contexts.connect(settings.context, settings.timeout)
        try:
            yield client, values, name
        finally:
            client.close()


@contextmanager
def connection(ctx: typer.Context) -> Iterator[Client]:
    with session(ctx) as (client, _, _):
        yield client


def request(ctx: typer.Context, method: str, path: str, **kwargs: Any) -> Any:
    with connection(ctx) as client:
        return client.request(method, path, **kwargs)


def page(
    client: Client, path: str, *, limit: int, cursor: str | None, **filters: Any
) -> dict:
    params = {key: value for key, value in filters.items() if value is not None}
    params["limit"] = limit
    if path == "/jobs":
        if cursor:
            params["before"] = cursor
    else:
        params["paginated"] = "true"
        if cursor:
            params["cursor"] = cursor
    body = client.request("GET", path, params=params)
    if not isinstance(body, dict) or "items" not in body or "next" not in body:
        raise CliError(
            "Server does not support this pagination contract; update the platform"
        )
    return body


def listing(
    ctx: typer.Context,
    path: str,
    limit: int,
    cursor: str | None,
    all_pages: bool,
    **filters: Any,
) -> dict:
    with connection(ctx) as client:
        items: list[dict] = []
        seen: set[str] = set()
        while True:
            result = page(client, path, limit=limit, cursor=cursor, **filters)
            items.extend(result["items"])
            if not all_pages or result["next"] is None:
                return {"items": items, "next": result["next"]}
            if result["next"] in seen:
                raise CliError("Server returned a repeated pagination cursor")
            seen.add(result["next"])
            cursor = result["next"]


def submit(
    ctx: typer.Context, path: str, body: dict, wait: bool, key: str | None
) -> dict:
    with connection(ctx) as client:
        return submit_job(client, path, body, wait, runtime(ctx).wait_timeout, key)

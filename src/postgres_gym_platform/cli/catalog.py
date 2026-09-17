from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import emit

from ._http import AllPages, Cursor, Limit, listing, request

suites = typer.Typer(help="Browse suites installed on the platform.")
tasks = typer.Typer(help="Browse runnable tasks of a suite.")
Suite = Annotated[str, typer.Argument(help="Suite identifier.")]


@suites.command("list")
def list_suites(
    ctx: typer.Context,
    limit: Limit = 50,
    cursor: Cursor = None,
    all_pages: AllPages = False,
) -> None:
    """List suites."""
    emit(ctx, listing(ctx, "/suites", limit, cursor, all_pages))


@tasks.command("list")
def list_tasks(
    ctx: typer.Context,
    suite: Suite,
    split: Annotated[
        str | None, typer.Option("--split", help="Only tasks of this split.")
    ] = None,
) -> None:
    """List tasks of a suite."""
    params = {"split": split} if split else {}
    emit(ctx, request(ctx, "GET", f"/suites/{suite}/tasks", params=params))


@tasks.command("show")
def show_task(
    ctx: typer.Context,
    suite: Suite,
    task: Annotated[str, typer.Argument(help="Task name.")],
) -> None:
    """Show one task with its prompt levels."""
    emit(ctx, request(ctx, "GET", f"/suites/{suite}/tasks/{task}"))

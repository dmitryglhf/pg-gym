from typing import Annotated

import typer

from ..http import listing, request
from ..output import show

suites = typer.Typer(help="Browse installed suites.")
tasks = typer.Typer(help="Browse runnable tasks.")


@suites.command("list")
def list_suites(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    all_pages: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    show(listing("/suites", limit, cursor, all_pages))


@tasks.command("list")
def list_tasks(
    suite: str, split: Annotated[str | None, typer.Option("--split")] = None
) -> None:
    show(
        request(
            "GET", f"/suites/{suite}/tasks", params={"split": split} if split else {}
        )
    )


@tasks.command("show")
def show_task(suite: str, task: str) -> None:
    show(request("GET", f"/suites/{suite}/tasks/{task}"))

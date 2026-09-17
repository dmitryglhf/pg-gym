from pathlib import Path
from typing import Annotated

import typer

from ...client.artifacts import download_artifact
from ..http import connection, listing, request
from ..output import show

app = typer.Typer(help="Inspect and download artifacts.")


@app.command("list")
def list_artifacts(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    all_pages: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    show(listing("/artifacts", limit, cursor, all_pages))


@app.command("show")
def show_artifact(identifier: str) -> None:
    show(request("GET", "/artifacts/" + identifier))


@app.command("download")
def download(
    identifier: str, directory: Annotated[Path, typer.Option("--directory")]
) -> None:
    with connection() as client:
        show(download_artifact(client, identifier, directory))

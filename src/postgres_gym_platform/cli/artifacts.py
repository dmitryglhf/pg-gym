from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from postgres_gym.cli import emit

from ..client.artifacts import download_artifact
from ._http import AllPages, Cursor, Limit, connection, listing, request

app = typer.Typer(help="Inspect and download artifacts.")
Artifact = Annotated[str, typer.Argument(help="Artifact id.")]


@app.command("list")
def list_artifacts(
    ctx: typer.Context,
    limit: Limit = 50,
    cursor: Cursor = None,
    all_pages: AllPages = False,
) -> None:
    """List artifacts of every kind."""
    emit(ctx, listing(ctx, "/artifacts", limit, cursor, all_pages))


@app.command("show")
def show(ctx: typer.Context, identifier: Artifact) -> None:
    """Show an artifact and its files."""
    emit(ctx, request(ctx, "GET", "/artifacts/" + identifier))


@app.command("download")
def download(
    ctx: typer.Context,
    identifier: Artifact,
    directory: Annotated[
        Path, typer.Option("--directory", help="Destination directory.")
    ],
) -> None:
    """Download every file of a ready artifact, verifying checksums."""
    with connection(ctx) as client:
        emit(ctx, download_artifact(client, identifier, directory))

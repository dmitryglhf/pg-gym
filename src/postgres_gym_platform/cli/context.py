from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import emit

from ..client import contexts

app = typer.Typer(help="Manage saved platform addresses and their tokens.")
Name = Annotated[str, typer.Argument(help="Context name.")]


@app.command("add")
def add(
    ctx: typer.Context,
    name: Name,
    url: Annotated[
        str,
        typer.Option(
            "--url", help="Platform API address, for example http://localhost:9432."
        ),
    ],
) -> None:
    """Save a platform address; the first context becomes active."""
    emit(ctx, contexts.add(name, url))


@app.command("list")
def list_contexts(ctx: typer.Context) -> None:
    """List saved contexts without their tokens."""
    emit(ctx, contexts.listing())


@app.command("use")
def use(ctx: typer.Context, name: Name) -> None:
    """Make a context the default for later commands."""
    emit(ctx, contexts.use(name))


@app.command("remove")
def remove(ctx: typer.Context, name: Name) -> None:
    """Forget a context and its token."""
    emit(ctx, contexts.remove(name))

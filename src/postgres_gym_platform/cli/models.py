from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import emit

from ._http import (
    AllPages,
    Config,
    Cursor,
    IdempotencyKey,
    Limit,
    Wait,
    listing,
    submit,
)
from .artifacts import COLUMNS

app = typer.Typer(help="Import and list model artifacts.")


@app.command("pull")
def pull(
    ctx: typer.Context,
    repository: Annotated[
        str | None,
        typer.Argument(
            help="Hugging Face repository, for example Qwen/Qwen2.5-Coder-3B-Instruct."
        ),
    ] = None,
    revision: Annotated[
        str | None, typer.Option("--revision", help="Git revision to import.")
    ] = None,
    credential: Annotated[
        str | None,
        typer.Option("--credential", help="Saved Hugging Face credential id."),
    ] = None,
    config: Config = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Display name of the artifact.")
    ] = None,
    wait: Wait = False,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Import a model from Hugging Face into the platform."""
    from ..client.specs import build

    body = build(
        "model",
        config,
        repository=repository,
        revision=revision,
        credential_id=credential,
        name=name,
    )
    emit(ctx, submit(ctx, "/models/imports", body, wait, idempotency_key))


@app.command("list")
def list_models(
    ctx: typer.Context,
    limit: Limit = 50,
    cursor: Cursor = None,
    all_pages: AllPages = False,
) -> None:
    """List model artifacts."""
    emit(
        ctx,
        listing(ctx, "/artifacts", limit, cursor, all_pages, kind="model"),
        columns=COLUMNS,
    )

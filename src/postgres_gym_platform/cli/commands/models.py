from pathlib import Path
from typing import Annotated

import typer

from ...client.specs import build
from ..http import listing
from ..jobs import submit_remote
from ..output import show

app = typer.Typer(help="Import and list model artifacts.")


@app.command("pull")
def pull(
    repository: Annotated[str | None, typer.Argument()] = None,
    revision: Annotated[str | None, typer.Option("--revision")] = None,
    credential: Annotated[str | None, typer.Option("--credential")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    body = build(
        "model",
        config,
        repository=repository,
        revision=revision,
        credential_id=credential,
        name=name,
    )
    show(submit_remote("/models/imports", body, wait, idempotency_key))


@app.command("list")
def list_models(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 50,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    all_pages: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    show(listing("/artifacts", limit, cursor, all_pages, kind="model"))

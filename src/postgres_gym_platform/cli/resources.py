from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from postgres_gym.cli import emit

from ..client import resources
from ._http import connection


def group(kind: str) -> typer.Typer:
    """One list, create and delete group per resource kind; the kind is bound here, never a parameter."""
    app = typer.Typer(help=f"Manage {kind}.")

    @app.command("list")
    def list_resources(ctx: typer.Context) -> None:
        with connection(ctx) as client:
            emit(ctx, resources.list_resources(client, kind))

    @app.command("create")
    def create(
        ctx: typer.Context,
        config: Annotated[
            Path, typer.Option("--config", help="JSON or YAML file with the resource.")
        ],
    ) -> None:
        with connection(ctx) as client:
            emit(ctx, resources.create_resource(client, kind, config))

    @app.command("delete")
    def delete(
        ctx: typer.Context,
        identifier: Annotated[str, typer.Argument(help="Resource id.")],
    ) -> None:
        with connection(ctx) as client:
            emit(ctx, resources.delete_resource(client, kind, identifier))

    list_resources.__doc__ = f"List {kind}."
    create.__doc__ = f"Create one of the {kind} from a file."
    delete.__doc__ = f"Delete one of the {kind}."
    return app

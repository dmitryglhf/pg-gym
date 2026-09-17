from pathlib import Path
from typing import Annotated

import typer

from ...client import resources
from ..http import connection
from ..output import show


def resource_group(kind: str) -> typer.Typer:
    """Bind the resource kind in a closure, never in a command parameter."""
    app = typer.Typer(help=f"Manage {kind}.")

    @app.command("list")
    def list_resources() -> None:
        with connection() as client:
            show(resources.list_resources(client, kind))

    @app.command("create")
    def create(config: Annotated[Path, typer.Option("--config")]) -> None:
        with connection() as client:
            show(resources.create_resource(client, kind, config))

    @app.command("delete")
    def delete(identifier: str) -> None:
        with connection() as client:
            show(resources.delete_resource(client, kind, identifier))

    return app

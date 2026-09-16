from pathlib import Path
from typing import Annotated

import typer

from .. import resources
from ..output import show


def resource_group(kind: str) -> typer.Typer:
    """Bind the resource kind in a closure, never in a command parameter."""
    app = typer.Typer(help=f"Manage {kind}.")

    @app.command("list")
    def list_resources() -> None:
        show(resources.list_resources(kind))

    @app.command("create")
    def create(config: Annotated[Path, typer.Option("--config")]) -> None:
        show(resources.create_resource(kind, config))

    @app.command("delete")
    def delete(identifier: str) -> None:
        show(resources.delete_resource(kind, identifier))

    return app

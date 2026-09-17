from typing import Annotated

import typer

from ...client import contexts
from ..output import show

app = typer.Typer(help="Manage paired platform addresses and credentials.")


@app.command("add")
def add(name: str, url: Annotated[str, typer.Option("--url")]) -> None:
    show(contexts.add(name, url))


@app.command("list")
def listing() -> None:
    show(contexts.listing())


@app.command("use")
def use(name: str) -> None:
    show(contexts.use(name))


@app.command("remove")
def remove(name: str) -> None:
    show(contexts.remove(name))

from pathlib import Path
from typing import Annotated

import typer

from .. import development
from ..output import show

_DEFAULT_SOURCE = Path(".")
app = typer.Typer(help="Build images and maintain the development environment.")


@app.command("stand-fetch")
def dev_stand_fetch(
    source: Annotated[Path, typer.Option("--source")] = _DEFAULT_SOURCE,
) -> None:
    show(development.stand_fetch(source))


@app.command("image")
def dev_image(
    source: Annotated[Path, typer.Option("--source")] = _DEFAULT_SOURCE,
    build_arg: Annotated[list[str] | None, typer.Option("--build-arg")] = None,
) -> None:
    show(development.image(source, build_arg))


@app.command("platform-images")
def platform_images(
    source: Annotated[Path, typer.Option("--source")] = Path("."),
    gpu: Annotated[bool, typer.Option("--gpu")] = False,
) -> None:
    show(development.platform_images(source, gpu))


from postgres_gym.cli.dev import selftest, suite_check, verify

app.command("suite-check")(suite_check)
app.command("verify")(verify)
app.command("selftest")(selftest)

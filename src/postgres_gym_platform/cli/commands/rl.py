from pathlib import Path
from typing import Annotated

import typer

from ...client.specs import build
from ..jobs import submit_remote
from ..output import show

app = typer.Typer(help="Submit training and evaluation jobs.")


@app.command("train")
def train(
    artifact: Annotated[str | None, typer.Argument()] = None,
    suite: Annotated[str | None, typer.Option("--suite")] = None,
    split: Annotated[str | None, typer.Option("--split")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    body = build(
        "training", config, artifact_id=artifact, suite=suite, split=split, name=name
    )
    show(submit_remote("/training-runs", body, wait, idempotency_key))


@app.command("evaluate")
def evaluate(
    artifact: Annotated[str | None, typer.Argument()] = None,
    suite: Annotated[str | None, typer.Option("--suite")] = None,
    split: Annotated[str | None, typer.Option("--split")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    body = build(
        "evaluation", config, artifact_id=artifact, suite=suite, split=split, name=name
    )
    show(submit_remote("/evaluations", body, wait, idempotency_key))

from __future__ import annotations

from typing import Annotated

import typer

from postgres_gym.cli import emit

from ._http import Config, IdempotencyKey, Wait, submit

app = typer.Typer(help="Submit training and evaluation jobs.")
Artifact = Annotated[str | None, typer.Argument(help="Model or adapter artifact id.")]
Suite = Annotated[str | None, typer.Option("--suite", help="Suite identifier.")]
Split = Annotated[
    str | None, typer.Option("--split", help="Task split, for example train or test.")
]
Name = Annotated[str | None, typer.Option("--name", help="Display name of the job.")]


@app.command("train")
def train(
    ctx: typer.Context,
    artifact: Artifact = None,
    suite: Suite = None,
    split: Split = None,
    name: Name = None,
    config: Config = None,
    wait: Wait = False,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Start a GRPO training run."""
    from ..client.specs import build

    body = build(
        "training", config, artifact_id=artifact, suite=suite, split=split, name=name
    )
    emit(ctx, submit(ctx, "/training-runs", body, wait, idempotency_key))


@app.command("evaluate")
def evaluate(
    ctx: typer.Context,
    artifact: Artifact = None,
    suite: Suite = None,
    split: Split = None,
    name: Name = None,
    config: Config = None,
    wait: Wait = False,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Evaluate an artifact on a suite split."""
    from ..client.specs import build

    body = build(
        "evaluation", config, artifact_id=artifact, suite=suite, split=split, name=name
    )
    emit(ctx, submit(ctx, "/evaluations", body, wait, idempotency_key))

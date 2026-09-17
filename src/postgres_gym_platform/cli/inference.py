from __future__ import annotations

import sys
from typing import Annotated

import typer

from postgres_gym.cli import emit, runtime

from ..client import inference
from ._http import Config, IdempotencyKey, Wait, connection, request, submit

app = typer.Typer(help="Deploy models and chat with inference servers.")
Deployment = Annotated[str, typer.Argument(help="Deployment job id.")]


@app.command("deploy")
def deploy(
    ctx: typer.Context,
    artifact: Annotated[str | None, typer.Argument(help="Model artifact id.")] = None,
    config: Config = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Display name of the deployment.")
    ] = None,
    wait: Wait = False,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Start an inference server for a model artifact."""
    from ..client.specs import build

    body = build("deployment", config, artifact_id=artifact, name=name)
    emit(ctx, submit(ctx, "/deployments", body, wait, idempotency_key))


@app.command("status")
def status(ctx: typer.Context, identifier: Deployment) -> None:
    """Show a deployment job."""
    with connection(ctx) as client:
        emit(ctx, inference.deployment(client, identifier))


@app.command("stop")
def stop(ctx: typer.Context, identifier: Deployment) -> None:
    """Stop an inference server."""
    emit(ctx, request(ctx, "POST", f"/deployments/{identifier}/stop"))


@app.command("chat")
def chat(
    ctx: typer.Context,
    connection_id: Annotated[
        list[str] | None,
        typer.Option("--connection", help="Model connection id; repeat to compare."),
    ] = None,
    conversation: Annotated[
        str | None,
        typer.Option("--conversation", help="Continue an existing conversation."),
    ] = None,
    prompt: Annotated[
        str | None, typer.Option("--prompt", help="Message text.")
    ] = None,
    prompt_stdin: Annotated[
        bool, typer.Option("--prompt-stdin", help="Read the message from stdin.")
    ] = False,
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", min=1, help="Completion length limit.")
    ] = 2048,
    temperature: Annotated[
        float, typer.Option("--temperature", min=0, max=2, help="Sampling temperature.")
    ] = 0.7,
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Send one message and wait for the reply."""
    if prompt_stdin and prompt is not None:
        raise typer.BadParameter(
            "choose --prompt or --prompt-stdin", param_hint="--prompt-stdin"
        )
    text = sys.stdin.read() if prompt_stdin else prompt
    if text is None:
        if not sys.stdin.isatty():
            raise typer.BadParameter(
                "provide --prompt or --prompt-stdin", param_hint="--prompt"
            )
        text = typer.prompt("Message")
    if idempotency_key and not conversation:
        raise typer.BadParameter(
            "requires --conversation", param_hint="--idempotency-key"
        )
    with connection(ctx) as client:
        result = inference.chat(
            client,
            connection_id,
            conversation,
            text,
            max_tokens,
            temperature,
            runtime(ctx).wait_timeout,
            idempotency_key,
        )
    emit(ctx, result)

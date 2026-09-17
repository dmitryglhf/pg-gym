import sys
from pathlib import Path
from typing import Annotated

import typer

from ...client import inference
from ...client.specs import build
from ..http import connection as connect
from ..http import request
from ..jobs import submit_remote
from ..output import show

app = typer.Typer(help="Deploy models and chat with inference servers.")


@app.command("deploy")
def deploy(
    artifact: Annotated[str | None, typer.Argument()] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    wait: Annotated[bool, typer.Option("--wait")] = False,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    show(
        submit_remote(
            "/deployments",
            build("deployment", config, artifact_id=artifact, name=name),
            wait,
            idempotency_key,
        )
    )


@app.command("status")
def status(identifier: str) -> None:
    with connect() as client:
        show(inference.deployment(client, identifier))


@app.command("stop")
def stop(identifier: str) -> None:
    show(request("POST", f"/deployments/{identifier}/stop"))


@app.command("chat")
def chat(
    connection: Annotated[list[str] | None, typer.Option("--connection")] = None,
    conversation: Annotated[str | None, typer.Option("--conversation")] = None,
    prompt: Annotated[str | None, typer.Option("--prompt")] = None,
    prompt_stdin: Annotated[bool, typer.Option("--prompt-stdin")] = False,
    max_tokens: Annotated[int, typer.Option("--max-tokens", min=1)] = 2048,
    temperature: Annotated[float, typer.Option("--temperature", min=0, max=2)] = 0.7,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    if prompt_stdin and prompt is not None:
        raise ValueError("Choose --prompt or --prompt-stdin")
    text = sys.stdin.read() if prompt_stdin else prompt
    if text is None:
        if not sys.stdin.isatty():
            raise ValueError("Provide --prompt or --prompt-stdin")
        text = typer.prompt("Message")
    if idempotency_key and not conversation:
        raise ValueError("Reusable chat idempotency requires --conversation")
    from ..runtime import current

    with connect() as client:
        show(
            inference.chat(
                client,
                connection,
                conversation,
                text,
                max_tokens,
                temperature,
                current().wait_timeout,
                idempotency_key,
            )
        )

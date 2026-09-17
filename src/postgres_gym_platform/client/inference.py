from __future__ import annotations

import sys

from . import Client, JobError
from .jobs import submit, wait_for_terminal_job


def chat(
    client: Client,
    connections: list[str] | None,
    conversation: str | None,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
    key: str | None,
) -> dict:
    if not conversation and not connections:
        raise ValueError("--connection or --conversation is required")
    if not conversation:
        conversation = client.request(
            "POST",
            "/conversations",
            json={
                "connection_ids": connections,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )["id"]
    job = submit(
        client,
        f"/conversations/{conversation}/turns",
        {"prompt": prompt},
        False,
        timeout,
        key,
    )
    print(f"Conversation: {conversation}; job: {job['id']}", file=sys.stderr)
    result = wait_for_terminal_job(client, job["id"], timeout)
    if result.get("status") != "succeeded":
        raise JobError("Chat job did not succeed: " + job["id"])
    return {"conversation_id": conversation, "job": result}


def deployment(client: Client, identifier: str) -> dict:
    job = client.request("GET", "/jobs/" + identifier)
    if job.get("kind") != "deployment":
        raise ValueError("Select a deployment job")
    return job

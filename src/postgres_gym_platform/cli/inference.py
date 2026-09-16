import sys

from .errors import JobFailure
from .http import connection, request
from .jobs import submit, wait_for_terminal_job
from .runtime import current


def chat(
    connections: list[str] | None,
    conversation: str | None,
    prompt: str,
    max_tokens: int,
    temperature: float,
    key: str | None,
) -> dict:
    if not conversation and not connections:
        raise ValueError("--connection or --conversation is required")
    with connection() as client:
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
            current().wait_timeout,
            key,
        )
        print(f"Conversation: {conversation}; job: {job['id']}", file=sys.stderr)
        result = wait_for_terminal_job(client, job["id"], current().wait_timeout)
        if result.get("status") != "succeeded":
            raise JobFailure("Chat job did not succeed: " + job["id"])
        return {"conversation_id": conversation, "job": result}


def status(identifier: str) -> dict:
    job = request("GET", "/jobs/" + identifier)
    if job.get("kind") != "deployment":
        raise ValueError("Select a deployment job")
    return job

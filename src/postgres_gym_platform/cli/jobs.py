import sys
import time
import uuid

import httpx

from .errors import JobFailure

TERMINAL = {"succeeded", "failed", "cancelled"}


def wait_for_terminal_job(client, identifier: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        job = client.request("GET", "/jobs/" + identifier)
        if job.get("status") in TERMINAL:
            return job
        pause(deadline, identifier)


def pause(deadline: float, identifier: str) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Waiting timed out; remote job continues: " + identifier)
    time.sleep(min(2, remaining))


def wait_for_ready_deployment(client, identifier: str, timeout: float) -> dict:
    deadline, cursor = time.monotonic() + timeout, 0
    while True:
        job = client.request("GET", "/jobs/" + identifier)
        if job.get("status") in TERMINAL or job.get("status") == "cancelling":
            raise JobFailure("Deployment stopped before readiness: " + identifier)
        page = client.request(
            "GET", f"/jobs/{identifier}/events", params={"after": cursor}
        )
        cursor = page["next"]
        if any(
            event.get("payload", {}).get("phase") == "ready" for event in page["items"]
        ):
            job = client.request("GET", "/jobs/" + identifier)
            if job.get("status") in TERMINAL or job.get("status") == "cancelling":
                raise JobFailure("Deployment stopped: " + identifier)
            return {**job, "ready": True}
        if not page["items"]:
            pause(deadline, identifier)
        elif time.monotonic() >= deadline:
            raise TimeoutError(
                "Waiting timed out; remote deployment continues: " + identifier
            )


def submit(
    client, path: str, body: dict, wait: bool, timeout: float, key: str | None = None
) -> dict:
    key = key or uuid.uuid4().hex
    if len(key) > 200:
        raise ValueError("--idempotency-key must contain at most 200 characters")
    try:
        job = client.request("POST", path, json=body, headers={"Idempotency-Key": key})
    except httpx.HTTPError:
        print(
            "Submission unconfirmed. Repeat with --idempotency-key " + key,
            file=sys.stderr,
        )
        raise
    if wait:
        print("Job: " + job["id"], file=sys.stderr)
        if path == "/deployments" or job.get("kind") == "deployment":
            return wait_for_ready_deployment(client, job["id"], timeout)
        job = wait_for_terminal_job(client, job["id"], timeout)
        if job.get("status") != "succeeded":
            raise JobFailure(f"Job {job['id']}: {job.get('status')}")
    return job


def logs(client, identifier: str, *, follow: bool = False, after: int = 0):
    cursor = after
    while True:
        page = client.request(
            "GET", f"/jobs/{identifier}/events", params={"after": cursor}
        )
        yield from page["items"]
        cursor = page["next"]
        if not follow:
            return
        if page["items"]:
            continue
        if not follow:
            return
        job = client.request("GET", "/jobs/" + identifier)
        if job.get("status") in TERMINAL:
            # Drain events committed between the last event read and terminal status.
            page = client.request(
                "GET", f"/jobs/{identifier}/events", params={"after": cursor}
            )
            yield from page["items"]
            if not page["items"]:
                return
            cursor = page["next"]
        else:
            time.sleep(1)


def submit_remote(path: str, body: dict, wait: bool, key: str | None = None) -> dict:
    from .http import connection
    from .runtime import current

    with connection() as client:
        return submit(client, path, body, wait, current().wait_timeout, key)

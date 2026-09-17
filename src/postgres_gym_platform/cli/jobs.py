from ..client.jobs import logs, wait_for_terminal_job


def submit_remote(path: str, body: dict, wait: bool, key: str | None = None) -> dict:
    from ..client.jobs import submit
    from .http import connection
    from .runtime import current

    with connection() as client:
        return submit(client, path, body, wait, current().wait_timeout, key)


__all__ = ["logs", "submit_remote", "wait_for_terminal_job"]

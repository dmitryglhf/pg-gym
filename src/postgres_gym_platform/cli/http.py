"""API access and page traversal for CLI services."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from ..client import Client
from .runtime import CliRuntime, current, remote


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"items": self.items, "next": self.next}


@contextmanager
def connection(runtime: CliRuntime | None = None) -> Iterator[Client]:
    client, _, _ = remote(runtime or current())
    try:
        yield client
    finally:
        client.close()


def page(
    client: Client,
    path: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
    **filters: Any,
) -> Page:
    params = {key: value for key, value in filters.items() if value is not None}
    params["limit"] = limit
    if path == "/jobs":
        if cursor:
            params["before"] = cursor
    else:
        params["paginated"] = "true"
        if cursor:
            params["cursor"] = cursor
    body = client.request("GET", path, params=params)
    if not isinstance(body, dict) or "items" not in body or "next" not in body:
        raise ValueError(
            "Server does not support this pagination contract; update the platform"
        )
    return Page(body["items"], body["next"])


def listing(
    path: str, limit: int, cursor: str | None, all_pages: bool, **filters: Any
) -> dict:
    with connection() as client:
        items, seen = [], set()
        while True:
            result = page(client, path, limit=limit, cursor=cursor, **filters)
            items.extend(result.items)
            if not all_pages or result.next is None:
                return Page(items, result.next).as_dict()
            if result.next in seen:
                raise ValueError("Server returned a repeated pagination cursor")
            seen.add(result.next)
            cursor = result.next


def request(method: str, path: str, **kwargs: Any) -> Any:
    with connection() as client:
        return client.request(method, path, **kwargs)

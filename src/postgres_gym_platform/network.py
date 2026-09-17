from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx2


def endpoint(
    value: str, allowed_hosts: tuple[str, ...], *, resolve: bool = True
) -> str:
    url = urlsplit(value)
    host = url.hostname or ""
    if (
        url.scheme not in {"http", "https"}
        or not host
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Use an HTTP(S) endpoint without credentials, query or fragment"
        )
    if host in {"169.254.169.254", "metadata.google.internal"}:
        raise ValueError("Infrastructure metadata endpoints are not allowed")
    if host not in allowed_hosts and resolve:
        try:
            addresses = socket.getaddrinfo(
                host,
                url.port or (443 if url.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError("Endpoint hostname could not be resolved") from exc
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise ValueError(
                "Private endpoints must be explicitly listed in PG_GYM_ALLOWED_HOSTS"
            )
    path = url.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def connection_endpoint(config: dict, allowed_hosts: tuple[str, ...]) -> str:
    if config.get("managed_job_id"):
        allowed_hosts += (urlsplit(config["base_url"]).hostname or "",)
    return endpoint(config["base_url"], allowed_hosts)


def upstream_request(
    client: httpx2.AsyncClient,
    config: dict,
    allowed_hosts: tuple[str, ...],
    method: str,
    path: str,
    **kwargs,
) -> httpx2.Request:
    url = endpoint(config["base_url"], allowed_hosts, resolve=False) + path
    request = client.build_request(method, url, **kwargs)
    host = request.url.host
    if host in allowed_hosts or config.get("managed_job_id"):
        return request
    try:
        rows = socket.getaddrinfo(
            host,
            request.url.port or (443 if request.url.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("Endpoint hostname could not be resolved") from exc
    addresses = [row[4][0] for row in rows]
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError(
            "Private endpoints must be explicitly listed in PG_GYM_ALLOWED_HOSTS"
        )
    request.headers["Host"] = request.url.netloc.decode()
    request.extensions["sni_hostname"] = host
    request.url = request.url.copy_with(host=addresses[0])
    return request

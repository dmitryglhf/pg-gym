from urllib.parse import urlsplit

from ..client import read_contexts, write_contexts


def public(contexts: dict) -> dict:
    return {
        "active": contexts.get("active"),
        "contexts": {
            name: {"url": value["url"], "authenticated": bool(value.get("token"))}
            for name, value in contexts.get("contexts", {}).items()
        },
    }


def listing() -> dict:
    return public(read_contexts())


def add(name: str, url: str) -> dict:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Use an HTTP(S) API URL without credentials, query or fragment"
        )
    values = read_contexts()
    if name in values["contexts"]:
        raise ValueError("Context already exists; remove it before changing its server")
    values["contexts"][name] = {"url": url.rstrip("/")}
    values["active"] = values.get("active") or name
    write_contexts(values)
    return public(values)


def use(name: str) -> dict:
    values = read_contexts()
    if name not in values["contexts"]:
        raise ValueError("Unknown context: " + name)
    values["active"] = name
    write_contexts(values)
    return public(values)


def remove(name: str) -> dict:
    values = read_contexts()
    if name not in values["contexts"]:
        raise ValueError("Unknown context: " + name)
    del values["contexts"][name]
    if values.get("active") == name:
        values["active"] = None
    write_contexts(values)
    return public(values)

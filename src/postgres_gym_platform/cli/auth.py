from ..client import write_contexts
from .runtime import current, remote


def login(username: str | None, password: str | None, token: str | None) -> dict:
    client, contexts, name = remote(current())
    try:
        if not name:
            raise ValueError("Select --context NAME before saving a login")
        if token is not None:
            if not token:
                raise ValueError("Token must not be empty")
            client.http.headers["Authorization"] = "Bearer " + token
            user = client.request("GET", "/me")
        else:
            issued = client.request(
                "POST", "/auth/token", json={"username": username, "password": password}
            )
            token, user = issued["token"], issued["user"]
        contexts["contexts"][name]["token"] = token
        write_contexts(contexts)
        return user
    finally:
        client.close()


def logout() -> dict:
    client, contexts, name = remote(current())
    try:
        client.request("POST", "/auth/logout")
        if name:
            contexts["contexts"][name].pop("token", None)
            write_contexts(contexts)
        return {"ok": True}
    finally:
        client.close()

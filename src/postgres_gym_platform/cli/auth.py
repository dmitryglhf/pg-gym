from ..client import contexts
from .runtime import current


def login(username: str | None, password: str | None, token: str | None) -> dict:
    client, values, name = contexts.connect(current().context, current().timeout)
    try:
        return contexts.login(client, values, name, username, password, token)
    finally:
        client.close()


def logout() -> dict:
    client, values, name = contexts.connect(current().context, current().timeout)
    try:
        return contexts.logout(client, values, name)
    finally:
        client.close()

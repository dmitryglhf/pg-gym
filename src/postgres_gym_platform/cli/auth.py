from __future__ import annotations

import os
import sys
from typing import Annotated

import typer

from postgres_gym.cli import emit

from ..client import contexts
from ._http import request, session

app = typer.Typer(help="Authenticate against the selected platform context.")
Username = Annotated[
    str | None, typer.Option("--username", help="Account name; prompted if omitted.")
]
PasswordStdin = Annotated[
    bool,
    typer.Option(
        "--password-stdin", help="Read the password from the first line of stdin."
    ),
]


def secret(label: str, from_stdin: bool) -> str:
    return (
        sys.stdin.readline().rstrip("\n")
        if from_stdin
        else typer.prompt(label, hide_input=True)
    )


@app.command("login")
def login(
    ctx: typer.Context,
    username: Username = None,
    password_stdin: PasswordStdin = False,
    token_stdin: Annotated[
        bool,
        typer.Option(
            "--token-stdin", help="Store an existing API token read from stdin."
        ),
    ] = False,
) -> None:
    """Obtain a session token and store it in the context."""
    if token_stdin and (username or password_stdin):
        raise typer.BadParameter(
            "cannot be combined with username or password options",
            param_hint="--token-stdin",
        )
    with session(ctx) as (client, values, name):
        if token_stdin:
            user = contexts.login(
                client, values, name, None, None, sys.stdin.read().strip()
            )
        else:
            username = username or typer.prompt("Username")
            password = secret("Password", password_stdin)
            user = contexts.login(client, values, name, username, password, None)
    emit(ctx, user)


@app.command("register")
def register(
    ctx: typer.Context,
    username: Username = None,
    password_stdin: PasswordStdin = False,
    invitation_stdin: Annotated[
        bool,
        typer.Option(
            "--invitation-stdin", help="Read the registration code from stdin."
        ),
    ] = False,
    open_registration: Annotated[
        bool,
        typer.Option(
            "--open-registration", help="Register without a code on an open instance."
        ),
    ] = False,
) -> None:
    """Create an account. The code comes from --invitation-stdin, PG_GYM_REGISTRATION_TOKEN or a prompt."""
    if invitation_stdin and open_registration:
        raise typer.BadParameter(
            "choose invitation or open registration", param_hint="--open-registration"
        )
    username = username or typer.prompt("Username")
    password = secret("Password", password_stdin)
    if open_registration:
        invitation = ""
    elif invitation_stdin:
        invitation = sys.stdin.readline().strip()
    else:
        invitation = os.environ.get("PG_GYM_REGISTRATION_TOKEN") or secret(
            "Registration code", False
        )
    body = {"username": username, "password": password, "invitation": invitation}
    emit(ctx, request(ctx, "POST", "/auth/register", json=body))


@app.command("logout")
def logout(ctx: typer.Context) -> None:
    """Revoke the session and forget the stored token."""
    with session(ctx) as (client, values, name):
        result = contexts.logout(client, values, name)
    emit(ctx, result)


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Show the account behind the current token."""
    emit(ctx, request(ctx, "GET", "/me"))

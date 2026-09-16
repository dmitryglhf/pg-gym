import os
import sys
from typing import Annotated

import typer
from postgres_gym.cli.prompts import prompt_value

from .. import auth
from ..http import request
from ..output import show

app = typer.Typer(help="Authenticate against a selected platform context.")


@app.command("login")
def login(
    username: Annotated[str | None, typer.Option("--username")] = None,
    password_stdin: Annotated[bool, typer.Option("--password-stdin")] = False,
    token_stdin: Annotated[bool, typer.Option("--token-stdin")] = False,
) -> None:
    if token_stdin:
        if username or password_stdin:
            raise ValueError(
                "--token-stdin cannot be combined with username/password options"
            )
        show(auth.login(None, None, sys.stdin.read().strip()))
    else:
        username = username or prompt_value("Username")
        password = (
            sys.stdin.readline().rstrip("\n")
            if password_stdin
            else prompt_value("Password", secret=True)
        )
        show(auth.login(username, password, None))


@app.command("register")
def register(
    username: Annotated[str | None, typer.Option("--username")] = None,
    password_stdin: Annotated[bool, typer.Option("--password-stdin")] = False,
    invitation_stdin: Annotated[bool, typer.Option("--invitation-stdin")] = False,
    open_registration: Annotated[bool, typer.Option("--open-registration")] = False,
) -> None:
    if invitation_stdin and open_registration:
        raise ValueError("Choose invitation or open registration")
    username = username or prompt_value("Username")
    password = (
        sys.stdin.readline().rstrip("\n")
        if password_stdin
        else prompt_value("Password", secret=True)
    )
    invitation = (
        ""
        if open_registration
        else (
            sys.stdin.readline().strip()
            if invitation_stdin
            else os.environ.get("PG_GYM_REGISTRATION_TOKEN")
            or prompt_value("Registration code", secret=True)
        )
    )
    show(
        request(
            "POST",
            "/auth/register",
            json={"username": username, "password": password, "invitation": invitation},
        )
    )


@app.command("logout")
def logout() -> None:
    show(auth.logout())


@app.command("status")
def status() -> None:
    show(request("GET", "/me"))

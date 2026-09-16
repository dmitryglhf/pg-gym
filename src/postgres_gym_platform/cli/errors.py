import json
import sys
from collections.abc import Callable
from typing import Any

import httpx
import typer
from postgres_gym.cli.framework import Abort, ClickException, Exit
from typer.core import TyperGroup

from ..client import ApiError

EXIT_CODES = {
    0: "success",
    1: "job/server failure",
    2: "invalid input",
    3: "auth",
    4: "transport",
    6: "unmet threshold",
    124: "wait timeout",
    130: "interrupted",
}


class JobFailure(Exception):
    pass


def handle_errors(invoke: Callable[[], Any]) -> Any:
    try:
        return invoke()
    except Exit as exc:
        raise SystemExit(exc.exit_code) from None
    except ClickException as exc:
        code, message = 2, exc.format_message()
    except ApiError as exc:
        code = 3 if exc.status in {401, 403} else 2 if exc.status in {400, 422} else 1
        message = str(exc)
    except httpx.HTTPError as exc:
        code, message = 4, type(exc).__name__
    except TimeoutError as exc:
        code, message = 124, str(exc)
    except JobFailure as exc:
        code, message = 1, str(exc)
    except (ValueError, OSError, KeyError) as exc:
        code, message = 2, str(exc)
    except (KeyboardInterrupt, Abort):
        code, message = 130, "Client interrupted. Remote jobs continue."
    except Exception as exc:
        code, message = 1, "Internal error: " + type(exc).__name__
    print(json.dumps({"error": {"code": code, "message": message}}), file=sys.stderr)
    raise SystemExit(code)


class CliGroup(TyperGroup):
    """Use the same error policy for installed CLI and Typer's CliRunner."""

    def invoke(self, ctx):
        invoke = super().invoke
        return handle_errors(lambda: invoke(ctx))


def execute(app: typer.Typer, argv: list[str] | None = None) -> None:
    code = handle_errors(
        lambda: app(args=argv, prog_name="pg-gym", standalone_mode=False)
    )
    if isinstance(code, int) and code:
        raise SystemExit(code)

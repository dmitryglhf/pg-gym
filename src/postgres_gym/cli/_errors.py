from __future__ import annotations

import json
import subprocess
import sys
from enum import IntEnum

import typer
from typer.core import TyperGroup


class ExitCode(IntEnum):
    SUCCESS = 0
    FAILURE = 1
    INVALID_INPUT = 2
    AUTH = 3
    TRANSPORT = 4
    THRESHOLD = 6
    WAIT_TIMEOUT = 124


class CliError(Exception):
    """An expected failure reported to the user as JSON on stderr with an exit code."""

    def __init__(self, message: str, code: ExitCode = ExitCode.FAILURE):
        super().__init__(message)
        self.code = code


def report(message: str, code: ExitCode) -> typer.Exit:
    print(
        json.dumps({"error": {"code": int(code), "message": message}}), file=sys.stderr
    )
    return typer.Exit(int(code))


class Group(TyperGroup):
    """Root group: expected failures become one stderr line, anything else keeps its traceback."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except CliError as exc:
            raise report(str(exc), exc.code) from None
        except ValueError as exc:
            raise report(str(exc), ExitCode.INVALID_INPUT) from None
        except subprocess.CalledProcessError as exc:
            raise report(
                f"{exc.cmd[0]} exited with {exc.returncode}", ExitCode.FAILURE
            ) from None

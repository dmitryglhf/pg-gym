"""Presentation context shared by local command modules."""

from .framework import get_current_context
from .output import CliContext


def context() -> CliContext:
    runtime = get_current_context().find_root().obj
    return CliContext(runtime.output, runtime.no_color) if runtime else CliContext()

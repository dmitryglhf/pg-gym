from dataclasses import dataclass

from postgres_gym.cli.framework import get_current_context
from postgres_gym.cli.output import OutputMode

from ..client import Client, contexts


@dataclass(frozen=True)
class CliRuntime:
    output: OutputMode = OutputMode.table
    no_color: bool = False
    context: str | None = None
    timeout: float = 60.0
    wait_timeout: float = 600.0


def current() -> CliRuntime:
    return get_current_context().find_root().obj


def remote(runtime: CliRuntime) -> tuple[Client, dict, str | None]:
    return contexts.connect(runtime.context, runtime.timeout)

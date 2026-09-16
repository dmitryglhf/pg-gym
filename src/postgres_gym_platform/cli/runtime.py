import os
from dataclasses import dataclass

from postgres_gym.cli.framework import get_current_context
from postgres_gym.cli.output import OutputMode

from ..client import Client, read_contexts


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
    contexts = read_contexts()
    name = runtime.context or contexts.get("active")
    configured = contexts.get("contexts", {}).get(name, {}) if name else {}
    if runtime.context and not configured:
        raise ValueError("Unknown context: " + runtime.context)
    # Explicit context wins. Environment credentials only accompany an environment URL.
    if not runtime.context and os.environ.get("PG_GYM_URL"):
        url, token, name = (
            os.environ["PG_GYM_URL"],
            os.environ.get("PG_GYM_TOKEN", ""),
            None,
        )
    else:
        url, token = configured.get("url"), configured.get("token", "")
        if os.environ.get("PG_GYM_TOKEN") and not runtime.context:
            raise ValueError("PG_GYM_TOKEN requires PG_GYM_URL or use a named context")
    if not url:
        raise ValueError("Configure a context or set PG_GYM_URL")
    return Client(url, token, runtime.timeout), contexts, name

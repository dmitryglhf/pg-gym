from postgres_gym.cli.output import CliContext, OutputMode, emit

from .runtime import current


def show(value) -> None:
    runtime = current()
    emit(value, CliContext(runtime.output, runtime.no_color))


__all__ = ["show", "OutputMode"]

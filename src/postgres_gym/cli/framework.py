"""Small boundary for Typer releases with external or bundled Click."""

from typer import Abort, Exit

try:
    from typer._click.exceptions import ClickException
    from typer._click.globals import get_current_context
except ImportError:
    from click import ClickException, get_current_context

__all__ = ["Abort", "Exit", "ClickException", "get_current_context"]

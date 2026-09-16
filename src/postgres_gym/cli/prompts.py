import getpass
import sys


def prompt_value(label: str, *, secret: bool = False) -> str:
    if not sys.stdin.isatty():
        raise ValueError(f"{label} is required in non-interactive mode")
    return getpass.getpass(label + ": ") if secret else input(label + ": ")

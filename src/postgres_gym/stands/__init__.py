from __future__ import annotations

import importlib


def load(name: str):
    try:
        module = importlib.import_module(f"postgres_gym.stands.{name}")
    except ModuleNotFoundError as exc:
        raise SystemExit(f"no stand {name!r}: {exc}") from None
    return module.STAND

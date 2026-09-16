from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from postgres_gym import settings
from postgres_gym.core.protocol import Suite


def suites_dir() -> Path:
    return settings.ROOT / "suites"


def names() -> list[str]:
    return sorted(p.parent.parent.name for p in suites_dir().glob("*/src/__init__.py"))


def package(suite_id: str | None = None) -> ModuleType:
    suite_id = suite_id or settings.SUITE_ID
    name = "postgres_gym_suite_" + suite_id.replace("-", "_")
    if name in sys.modules:
        return sys.modules[name]

    init = suites_dir() / suite_id / "src" / "__init__.py"
    if not init.is_file():
        known = ", ".join(names()) or "none"
        raise SystemExit(f"no suite {suite_id!r} under {suites_dir()}. Known: {known}")

    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(init.parent)]
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"{init} is not importable as a package")
    module = importlib.util.module_from_spec(spec)

    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


def load(suite_id: str | None = None) -> Suite:
    module = package(suite_id)
    found = getattr(getattr(module, "suite", None), "SUITE", None)
    if found is None:
        raise SystemExit(f"{module.__file__}: src/suite.py has to export SUITE")
    return found


def available() -> list[Suite]:
    return [load(name) for name in names()]

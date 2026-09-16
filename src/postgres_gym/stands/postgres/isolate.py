from __future__ import annotations

import contextlib
import os
import re
import subprocess
from dataclasses import dataclass, field

from postgres_gym import settings

TEST_ROOT = "src/test"

_TEST_SOURCE_SUFFIXES = (".sql", ".out", ".spec")
_TEST_SOURCE_DIRS = ("/sql/", "/expected/", "/specs/")


def is_test_source(rel: str) -> bool:
    return rel.endswith(_TEST_SOURCE_SUFFIXES) and any(
        part in rel for part in _TEST_SOURCE_DIRS
    )


_TEST_PLAN_NAMES = ("Makefile", "GNUmakefile", "meson.build")
_TEST_PLAN_SUFFIXES = (".pl", ".pm", ".py", ".sh")


def is_test_plan(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (
        name.endswith("_schedule")
        or name in _TEST_PLAN_NAMES
        or rel.endswith(_TEST_PLAN_SUFFIXES)
    )


def reference_tests(failing_tests: list[str] | None) -> list[str]:
    found = []
    for name in failing_tests or []:
        for rel in (
            f"src/test/regress/sql/{name}.sql",
            f"src/test/regress/expected/{name}.out",
        ):
            if (settings.PG_SRC / rel).is_file():
                found.append(rel)

        for alt in sorted(
            (settings.PG_SRC / "src/test/regress/expected").glob(f"{name}_[0-9].out")
        ):
            found.append(f"src/test/regress/expected/{alt.name}")
    return found


def leaking_tests(
    needles: list[str], failing_tests: list[str] | None = None
) -> list[str]:
    found: set[str] = set()
    for needle in needles:
        proc = subprocess.run(
            ["grep", "-rlwFI", "--", needle, TEST_ROOT],
            cwd=settings.PG_SRC,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
            check=False,
        )
        found.update(p for p in proc.stdout.split() if p and is_test_source(p))
    found.update(reference_tests(failing_tests))
    return sorted(found)


@dataclass
class Hidden:
    files: list[str] = field(default_factory=list)

    recreated: list[str] = field(default_factory=list)


_VARIANT_RE = re.compile(r"_\d+\.out$")


def with_variants(paths: list[str]) -> list[str]:
    out = list(paths)
    for rel in paths:
        if not rel.endswith(".out") or _VARIANT_RE.search(rel):
            continue
        stem = rel[: -len(".out")]
        for n in range(1, 10):
            variant = f"{stem}_{n}.out"
            if (settings.PG_SRC / variant).is_file() and variant not in out:
                out.append(variant)
    return out


@contextlib.contextmanager
def tests_hidden(paths: list[str]):
    stash: dict[str, tuple[bytes, int]] = {}
    state = Hidden()
    try:
        for rel in with_variants(paths):
            src = settings.PG_SRC / rel
            if not src.is_file():
                continue
            stash[rel] = (src.read_bytes(), src.stat().st_mode)
            src.unlink()
            state.files.append(rel)
        yield state
    finally:
        for rel in state.files:
            src = settings.PG_SRC / rel
            if src.exists():
                state.recreated.append(rel)
                src.unlink()
            src.parent.mkdir(parents=True, exist_ok=True)
            data, mode = stash[rel]
            src.write_bytes(data)
            os.chmod(src, mode)

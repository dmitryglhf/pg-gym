from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from postgres_gym import settings
from postgres_gym.core import langfuse as lf
from postgres_gym.core import tree
from postgres_gym.stands.postgres import build as pgbuild

OK, BAD, WARN = "ok  ", "FAIL", "warn"


def _run(argv: list[str], timeout: int = 20) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:
        return False, f"{argv[0]} not found"
    except subprocess.TimeoutExpired:
        return False, f"{argv[0]} timed out after {timeout}s"
    out = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (out[0] if out else "")


_ALLOWED_EXTENSIONS = {"developer"}


def _enabled_extensions(text: str) -> set[str]:
    block = re.search(r"^extensions:\n((?:[ \t].*\n|\n)*)", text, re.MULTILINE)
    if not block:
        return set()
    enabled, name = set(), None
    for line in block.group(1).splitlines():
        if m := re.match(r"^  ([\w-]+):\s*$", line):
            name = m.group(1)
        elif name and re.match(r"^    enabled:\s*true\s*$", line):
            enabled.add(name)
    return enabled


def _markov_config() -> list[tuple[str, str, str]]:
    path = (
        pathlib.Path(os.environ.get("HOME", "~")).expanduser()
        / ".config/markov/config.yaml"
    )
    if not path.is_file():
        return [
            (
                BAD,
                "markov config",
                (f"{path} missing -- the agent would run on its own defaults"),
            )
        ]
    text = path.read_text(encoding="utf-8", errors="replace")

    strict = settings.DISPOSABLE_GIT
    extra = sorted(_enabled_extensions(text) - _ALLOWED_EXTENSIONS)
    out = [
        (
            OK if not extra else (BAD if strict else WARN),
            "markov extensions",
            "developer only"
            if not extra
            else f"also enabled: {', '.join(extra)}"
            + ("" if strict else " (this stand's own config, not the image's)"),
        )
    ]

    provider = re.search(r"^active_provider:\s*(\S+)", text, re.MULTILINE)
    named = provider.group(1) if provider else None
    out.append(
        (
            OK if named == settings.AGENT_PROVIDER else WARN,
            "markov provider",
            (f"config says {named!r}, run will record {settings.AGENT_PROVIDER!r}"),
        )
    )

    secrets = path.with_name("secrets.yaml")
    has_key = (
        "PGPRO_API_KEY" in secrets.read_text(errors="replace")
        if secrets.is_file()
        else False
    )
    out.append(
        (
            OK if (has_key or os.environ.get("PGPRO_API_KEY")) else BAD,
            "markov secrets",
            "PGPRO_API_KEY in secrets.yaml"
            if has_key
            else "PGPRO_API_KEY in the environment"
            if os.environ.get("PGPRO_API_KEY")
            else "markov will find no PGPRO_API_KEY",
        )
    )
    return out


def _opencode_config() -> list[tuple[str, str, str]]:
    home = pathlib.Path(os.environ.get("HOME", "~")).expanduser()
    path = home / ".config/opencode/opencode.jsonc"
    if not path.is_file():
        return [
            (
                BAD,
                "opencode config",
                (
                    f"{path} missing -- the agent would run "
                    f"on its own defaults, web included"
                ),
            )
        ]
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []

    disabled = re.search(r'"webfetch"\s*:\s*false', text)
    denied = re.search(r'"webfetch"\s*:\s*"deny"', text)
    out.append(
        (
            OK if (disabled and denied) else BAD,
            "opencode webfetch",
            "off, and denied"
            if (disabled and denied)
            else "tools only -- no deny rule"
            if disabled
            else "denied, but still in the tool list"
            if denied
            else "REACHABLE -- the agent can fetch the reference",
        )
    )

    out.append(
        (
            OK
            if re.search(rf'"{re.escape(settings.AGENT_PROVIDER)}"\s*:\s*{{', text)
            else WARN,
            "opencode provider",
            f"config declares {settings.AGENT_PROVIDER!r}"
            if re.search(rf'"{re.escape(settings.AGENT_PROVIDER)}"\s*:\s*{{', text)
            else f"no {settings.AGENT_PROVIDER!r} block, run would record it anyway",
        )
    )

    declared = f'"{settings.AGENT_MODEL}"' in text
    out.append(
        (
            OK if declared else BAD,
            "opencode model",
            f"{settings.AGENT_MODEL} declared"
            if declared
            else f"{settings.AGENT_MODEL} not declared -- first call returns "
            f"UnknownError and exits 0",
        )
    )

    var = re.search(r'"apiKey"\s*:\s*"\{env:([A-Z0-9_]+)\}"', text)
    name = var.group(1) if var else None
    if name is None:
        out.append((BAD, "opencode key", "apiKey is not an {env:...} reference"))
    elif os.environ.get(name):
        out.append((OK, "opencode key", f"{name} set"))
    else:
        out.append(
            (
                OK if settings.PROVIDER_KEY else BAD,
                "opencode key",
                f"{name} unset here; the entrypoint sets it from "
                f"{settings.MARKOV_KEY_ENV} for an opencode run"
                if settings.PROVIDER_KEY
                else f"{name} unset and no {settings.MARKOV_KEY_ENV} to derive "
                f"it from -- opencode would send no key",
            )
        )

    store = settings.OPENCODE_DATA
    if not store.exists():
        out.append(
            (
                OK,
                "opencode store",
                f"{store} not created yet -- opencode makes it on first run",
            )
        )
    else:
        out.append(
            (
                OK if os.access(store, os.W_OK) else BAD,
                "opencode store",
                f"{store} writable"
                if os.access(store, os.W_OK)
                else f"{store} not writable -- the WAL would read as empty "
                f"and the run would report no calls",
            )
        )
    return out


def checks() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []

    def add(cond: bool, name: str, detail: str, soft: bool = False) -> None:
        out.append((OK if cond else (WARN if soft else BAD), name, detail))

    add(
        os.geteuid() != 0,
        "user",
        f"uid {os.geteuid()}"
        + (" -- postgres will refuse to start" if os.geteuid() == 0 else ""),
    )

    add(
        settings.TASKS_DIR.is_dir(),
        "tasks",
        f"{len(list(settings.TASKS_DIR.glob('*.json'))) if settings.TASKS_DIR.is_dir() else 0}"
        f" under {settings.TASKS_DIR}",
    )

    usable = 0
    if settings.ORACLE_DIR.is_dir():
        import json

        for path in settings.ORACLE_DIR.glob("*.json"):
            try:
                usable += bool(json.loads(path.read_text()).get("usable"))
            except (OSError, json.JSONDecodeError):
                pass
    add(usable > 0, "oracle", f"{usable} usable")

    writable = (
        os.access(settings.RUNS_DIR, os.W_OK) if settings.RUNS_DIR.is_dir() else False
    )
    if not settings.RUNS_DIR.is_dir():
        try:
            settings.RUNS_DIR.mkdir(parents=True, exist_ok=True)
            writable = os.access(settings.RUNS_DIR, os.W_OK)
        except OSError:
            writable = False
    add(
        writable,
        "runs",
        f"{settings.RUNS_DIR} writable"
        if writable
        else f"{settings.RUNS_DIR} is not writable -- results would be lost",
    )

    add(settings.PG_GIT_DIR.is_dir(), "git dir", str(settings.PG_GIT_DIR))

    saved = tree.saved_git_dir()
    add(
        not saved.is_dir(),
        "history",
        "no interrupted run"
        if not saved.is_dir()
        else f"{saved} left behind -- a run died mid-task; move it back over "
        f"{settings.PG_GIT_DIR} before trusting anything",
    )

    try:
        sha = tree._git(
            "rev-parse", "--verify", "--quiet", tree.PRISTINE_REF
        ).stdout.strip()
        add(
            bool(sha),
            "pristine",
            sha[:12]
            if sha
            else f"{tree.PRISTINE_REF} is not set -- the first "
            f"run will pin whatever HEAD happens to be",
        )
    except Exception as exc:  # noqa: BLE001
        sha = ""
        out.append((BAD, "pristine", f"{type(exc).__name__}: {exc}"))
    if sha:
        dirty = tree._git("status", "--porcelain").stdout.strip().splitlines()
        add(
            not dirty,
            "tree",
            "clean"
            if not dirty
            else f"{len(dirty)} modified paths left by a previous run",
            soft=True,
        )

    prefix = pgbuild.configured_prefix()
    add(
        prefix == str(settings.PG_PREFIX),
        "configure",
        f"prefix {prefix}"
        if prefix == str(settings.PG_PREFIX)
        else f"prefix is {prefix!r}, harness wants {str(settings.PG_PREFIX)!r} "
        f"-- every task would reconfigure",
    )

    ok, detail = _run([str(settings.PG_PREFIX / "bin" / "postgres"), "--version"])
    add(ok, "postgres", detail)
    add(
        (settings.PG_PREFIX / "bin" / "initdb").is_file(),
        "initdb",
        str(settings.PG_PREFIX / "bin" / "initdb"),
    )

    from postgres_gym.core.cli_agent import PROFILES

    for profile, spec in PROFILES.items():
        binary = spec["cmd"].split()[0]
        path = shutil.which(binary)
        if path is None:
            continue
        ok, detail = _run([binary, "--version"])
        add(ok, f"agent:{profile}", f"{path} {detail}")

    if shutil.which("markov"):
        for status, name, detail in _markov_config():
            out.append((status, name, detail))

    if shutil.which("opencode"):
        for status, name, detail in _opencode_config():
            out.append((status, name, detail))

    reachable, detail = lf.health()
    add(reachable, "langfuse", detail, soft=not settings.REQUIRE_LANGFUSE)

    key = os.environ.get(settings.JUDGE_KEY_ENV)
    add(
        bool(key),
        "judge",
        f"{settings.JUDGE_MODEL} via {settings.JUDGE_BASE_URL}"
        if key
        else f"{settings.JUDGE_KEY_ENV} not set -- runs would be unjudged",
        soft=True,
    )

    add(
        bool(settings.PROVIDER_KEY),
        "markov key",
        f"{settings.MARKOV_KEY_ENV} set"
        if settings.PROVIDER_KEY
        else f"{settings.MARKOV_KEY_ENV} not set -- agent would fail on its first "
        f"call{'; refusing to run' if settings.REQUIRE_MARKOV_KEY else ''}",
        soft=not settings.REQUIRE_MARKOV_KEY,
    )

    for var in ("PGPRO_HOST", "OPENAI_HOST", "OLLAMA_HOST"):
        host = os.environ.get(var)
        if not host:
            continue
        try:
            urllib.request.urlopen(host, timeout=10).read(1)
            add(True, f"provider:{var.lower()}", host)
        except urllib.error.HTTPError:
            add(True, f"provider:{var.lower()}", host)
        except Exception as exc:  # noqa: BLE001
            add(False, f"provider:{var.lower()}", f"{host}: {type(exc).__name__} {exc}")

    return out


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(
        prog="postgres_gym doctor", description="check the stand"
    ).parse_args(argv)
    results = checks()
    width = max(len(name) for _, name, _ in results)
    for status, name, detail in results:
        print(f"{status}  {name.ljust(width)}  {detail}")
    failed = [name for status, name, _ in results if status == BAD]
    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        sys.exit(1)
    print("\nstand is ready")


if __name__ == "__main__":
    main()

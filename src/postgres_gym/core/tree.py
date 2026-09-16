from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

from postgres_gym import settings
from postgres_gym.core.process import Step

PRISTINE_REF = "refs/postgres-gym/pristine"

LEGACY_PRISTINE_REF = "refs/pgfuncbench/pristine"

BRANCH = "refs/heads/postgres-gym"
AUTHOR = ("-c", "user.name=postgres-gym", "-c", "user.email=bench@localhost")

OURS = ("postgres-gym", "postgres_gym", "pgswebench", "pgfuncbench")


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            f"--git-dir={settings.PG_GIT_DIR}",
            f"--work-tree={settings.PG_SRC}",
            *args,
        ],
        cwd=(settings.PG_SRC if settings.PG_SRC.is_dir() else settings.STAND_DIR),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def head_sha() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def pristine_sha() -> str:
    existing = _git("rev-parse", "--verify", "--quiet", PRISTINE_REF).stdout.strip()
    if existing:
        return existing
    legacy = _git(
        "rev-parse", "--verify", "--quiet", LEGACY_PRISTINE_REF
    ).stdout.strip()
    if legacy:
        _git("update-ref", PRISTINE_REF, legacy)
        return legacy

    head = head_sha()

    if _git("log", "-1", "--format=%an", head).stdout.strip() in OURS:
        raise SystemExit(
            "no pristine ref and HEAD is a baseline this harness committed, so "
            "there is no upstream tree left to anchor to. A stand whose git "
            "directory is disposable runs one task per container; use "
            "`postgres-gym bench`, or restore the stand with `just stand-fetch`."
        )
    _git("update-ref", PRISTINE_REF, head)
    return head


def reset_pristine(scratch: tuple[str, ...] = ()) -> str:
    sha = pristine_sha()
    reset_tree(sha, scratch)
    return sha


def reset_tree(sha: str | None = None, scratch: tuple[str, ...] = ()) -> None:
    settings.PG_SRC.mkdir(parents=True, exist_ok=True)
    done = _git("reset", "--hard", sha or "HEAD", timeout=300)
    if done.returncode != 0:
        raise RuntimeError(
            f"cannot put the tree at {sha or 'HEAD'}: {done.stderr.strip()[:300]}"
        )
    _git("clean", "-fdq", timeout=300)
    for path in scratch:
        _git("clean", "-fdxq", path, timeout=300)


def commit_baseline(message: str) -> str:
    _git(*AUTHOR, "commit", "-aqm", message, timeout=300)
    return head_sha()


def saved_git_dir():
    return settings.PG_GIT_DIR.with_name(settings.PG_GIT_DIR.name + ".presever")


def restore_history() -> bool:
    saved = saved_git_dir()
    if not saved.is_dir():
        return False
    shutil.rmtree(settings.PG_GIT_DIR, ignore_errors=True)
    saved.rename(settings.PG_GIT_DIR)
    return True


def sever_history() -> str:
    if settings.DISPOSABLE_GIT:
        shutil.rmtree(settings.PG_GIT_DIR, ignore_errors=True)
    else:
        saved = saved_git_dir()
        shutil.rmtree(saved, ignore_errors=True)
        if settings.PG_GIT_DIR.is_dir():
            settings.PG_GIT_DIR.rename(saved)
    subprocess.run(
        ["git", "init", "-q", "--bare", str(settings.PG_GIT_DIR)],
        check=True,
        capture_output=True,
        timeout=120,
    )

    for key, value in (
        ("core.bare", "false"),
        ("core.ignorecase", "false"),
        ("core.precomposeunicode", "false"),
    ):
        _git("config", key, value)
    _git("symbolic-ref", "HEAD", BRANCH)
    _git("add", "-A", timeout=300)
    _git(*AUTHOR, "commit", "-qm", "postgres_gym: task baseline", timeout=300)
    return head_sha()


def apply_patch_text(text: str, reverse: bool = False) -> Step:
    start = time.time()
    handle, path = tempfile.mkstemp(prefix="pgswe-apply-", suffix=".patch")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
        args = ["apply"] + (["-R"] if reverse else []) + [path]
        proc = _git(*args, timeout=120)
    finally:
        os.unlink(path)
    return Step(proc.returncode == 0, time.time() - start, proc.stdout + proc.stderr)


def tracked_files() -> set[str]:
    return set(_git("ls-files").stdout.split())


def worktree_diff() -> str:
    return _git("diff").stdout


_INSTANCE_MARKER = "PG_VERSION"


def _instance_dirs(paths: list[str]) -> set[str]:
    return {
        p.rsplit("/", 1)[0] + "/"
        for p in paths
        if p.rsplit("/", 1)[-1] == _INSTANCE_MARKER
    }


def _untracked() -> list[str]:
    found = _git("ls-files", "--others", "--exclude-standard").stdout.split()
    roots = _instance_dirs(found)
    return [p for p in found if not any(p.startswith(r) for r in roots)]


def diff() -> str:
    return _git("diff", "HEAD").stdout + "".join(
        f"\n+++ untracked: {f}\n" for f in _untracked()
    )


def changed_files() -> list[str]:
    tracked = _git("diff", "--name-only", "HEAD").stdout.split()
    return sorted(set(tracked) | set(_untracked()))

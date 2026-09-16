from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core.process import Step
from postgres_gym.core.process import run as _run

CONFIGURE_ARGS = [
    f"--prefix={settings.PG_PREFIX}",
    "--enable-cassert",
    "--enable-debug",
    "--with-icu",
    "--without-readline",
]

PG_PROC_DAT = settings.PG_SRC / "src/include/catalog/pg_proc.dat"
REGRESS_DIR = settings.PG_SRC / "src/test/regress"

JOBS = str(os.cpu_count() or 4)

BUILD_TIMEOUT = 3600
CHECK_TIMEOUT = 1800

PASSED, FAILED, SKIPPED = "passed", "failed", "skipped"

@dataclass
class CheckResult:
    ok: bool
    seconds: float
    failed: list[str] = field(default_factory=list)
    total: int = 0
    output: str = ""

    statuses: dict[str, str] = field(default_factory=dict)

    diff_lines: int = 0
    diff_by_file: dict[str, int] = field(default_factory=dict)

_STAMPS = (
    "src/backend/utils/fmgr-stamp",
    "src/include/catalog/bki-stamp",
    "src/include/utils/header-stamp",
)

def invalidate_generated() -> None:
    for rel in _STAMPS:
        (settings.PG_SRC / rel).unlink(missing_ok=True)

def configured_prefix() -> str | None:
    path = settings.PG_SRC / "src/Makefile.global"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("prefix :="):
            return line.split(":=", 1)[1].strip()
    return None

_CONFIGURE_INPUTS = ("configure", "src/include/pg_config.h.in")
_STAMP = "/.pgswe-configured"

def _configure_fingerprint() -> str:
    h = hashlib.sha256()
    for rel in _CONFIGURE_INPUTS:
        path = settings.PG_SRC / rel
        h.update(path.read_bytes() if path.is_file() else b"")
    return h.hexdigest()

def _stamp_path() -> Path:
    return settings.PG_SRC.parent / _STAMP.lstrip("/")

def ensure_configured() -> Step | None:
    stamp, want = _stamp_path(), _configure_fingerprint()
    have = stamp.read_text().strip() if stamp.is_file() else None
    if configured_prefix() == str(settings.PG_PREFIX) and have == want:
        return None
    step = _run(["./configure", *CONFIGURE_ARGS], settings.PG_SRC, BUILD_TIMEOUT)
    if step.ok:
        stamp.write_text(want)
    return step

def build(changed: list[str] | None = None) -> Step:
    reconfigured = ensure_configured()
    if reconfigured is not None and not reconfigured.ok:
        return reconfigured
    if changed:
        cleaned = _run(["make", "clean"], settings.PG_SRC, BUILD_TIMEOUT)
        if not cleaned.ok:
            return cleaned
    invalidate_generated()
    return _run(["make", f"-j{JOBS}"], settings.PG_SRC, BUILD_TIMEOUT)

def install() -> Step:
    return _run(["make", "install"], settings.PG_SRC, BUILD_TIMEOUT)

_FAILED_RE = re.compile(
    r"^not ok\s+\d+\s*[-+]?\s*(\S+)|^(?:test\s+)?(\S+)\s+\.\.\..*\bFAILED\b",
    re.MULTILINE,
)
_SUMMARY_RE = re.compile(r"(\d+) of (\d+) tests failed|All (\d+) tests passed")

_TAP_RE = re.compile(r"^(not )?ok\s+\d+\s*[-+]?\s*(\S+)(.*)$", re.MULTILINE)
_LEGACY_RE = re.compile(r"^(?:test\s+)?(\S+)\s+\.\.\.\s*(ok|FAILED|failed)\b",
                        re.MULTILINE)

def _statuses(output: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for negated, name, rest in _TAP_RE.findall(output):
        if negated:
            found[name] = FAILED
        elif "# SKIP" in rest.upper():
            found[name] = SKIPPED
        else:
            found[name] = PASSED
    for name, verdict in _LEGACY_RE.findall(output):
        found[name] = PASSED if verdict == "ok" else FAILED
    return found

def check(tests: list[str] | None = None) -> CheckResult:
    diffs = REGRESS_DIR / "regression.diffs"
    diffs.unlink(missing_ok=True)

    args = ["make", "check"]
    if tests:
        args.append(f"TESTS={' '.join(tests)}")
    step = _run(args, REGRESS_DIR, CHECK_TIMEOUT)
    failed = sorted({tap or legacy for tap, legacy in _FAILED_RE.findall(step.output)})

    total = 0
    if m := _SUMMARY_RE.search(step.output):
        total = int(m.group(2) or m.group(3) or 0)

    diff_lines, diff_by_file = _diff_volume(diffs)
    return CheckResult(ok=step.ok and not diffs.exists(), seconds=step.seconds,
                       failed=failed, total=total, output=step.output,
                       statuses=_statuses(step.output),
                       diff_lines=diff_lines, diff_by_file=diff_by_file)

_DIFF_HEADER_RE = re.compile(r"^--- .*/expected/([\w.]+)\.out\b", re.MULTILINE)

def _diff_volume(diffs: Path) -> tuple[int, dict[str, int]]:
    if not diffs.is_file():
        return 0, {}

    per_file: dict[str, int] = {}
    current = None
    for line in diffs.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := _DIFF_HEADER_RE.match(line):
            current = m.group(1)
            per_file.setdefault(current, 0)
        elif current and line[:1] in "+-" and not line.startswith(("+++", "---")):
            per_file[current] += 1
    return sum(per_file.values()), per_file

def smoke(sql: str, tag: str = "smoke") -> Step:
    bindir = settings.PG_PREFIX / "bin"
    tmp = Path(tempfile.mkdtemp(prefix=f"pgswe-{tag}-"))
    data = tmp / "data"
    start = time.time()
    try:
        init = _run([str(bindir / "initdb"), "-D", str(data), "-N", "--no-locale",
                     "-U", "bench"], tmp, 600)
        if not init.ok:
            return Step(False, time.time() - start,
                        f"initdb failed:\n{init.output[-4000:]}")

        ctl = _run([str(bindir / "pg_ctl"), "-D", str(data), "-o",
                    f"-k {tmp} -h '' ", "-l", str(tmp / "log"), "-w", "start"], tmp, 300)
        if not ctl.ok:
            log = (tmp / "log").read_text(errors="replace") if (tmp / "log").exists() else ""
            return Step(False, time.time() - start,
                        f"startup failed:\n{ctl.output}\n{log[-4000:]}")

        try:
            q = _run([str(bindir / "psql"), "-h", str(tmp), "-U", "bench",
                      "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAc", sql], tmp, 120)
        finally:
            _run([str(bindir / "pg_ctl"), "-D", str(data), "-m", "immediate",
                  "-w", "stop"], tmp, 120)
        return Step(q.ok, time.time() - start, q.output)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

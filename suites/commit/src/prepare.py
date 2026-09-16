from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from postgres_gym import settings
from postgres_gym.stands.postgres import STAND

PUBLIC = ("name", "area", "goal", "contract")

MESSAGE_CALLS = ("errmsg(", "errmsg_plural(", "errhint(", "errdetail(")

TEST_SUFFIXES = (".sql", ".out", ".spec")
TEST_DIRS = ("/sql/", "/expected/", "/specs/")

def samples_dir() -> Path:
    return settings.DATA_DIR / "samples"

def load_sample(name: str) -> dict:
    path = samples_dir() / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"no sample at {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def git(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", f"--git-dir={settings.PG_GIT_DIR}", *args],
                          capture_output=True, text=True, errors="replace",
                          timeout=timeout, check=False)

def present(sha: str) -> bool:
    return git("cat-file", "-e", f"{sha}^{{commit}}", timeout=60).returncode == 0

def fetch(name: str) -> dict:
    sample = load_sample(name)
    wanted = [sample["sha"], sample["parent"]]
    fetched, failed = [], []
    for sha in wanted:
        if present(sha):
            continue
        proc = git("fetch", "--quiet", "--depth=1", settings.PG_MIRROR, sha)
        (fetched if present(sha) else failed).append(sha)
        if sha in failed:
            return {"sample": name, "ok": False, "sha": sha,
                    "tail": (proc.stdout + proc.stderr)[-2000:]}
    return {"sample": name, "ok": True, "fetched": fetched,
            "already_had": [s for s in wanted if s not in fetched]}

def split(sample: dict) -> tuple[list[str], list[str]]:
    return ([s["path"] for s in sample["solution"]],
            list(sample.get("test_files") or []))

def diff(a: str, b: str, paths: list[str]) -> str:
    proc = git("diff", a, b, "--", *paths)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {a[:12]}..{b[:12]} failed: {proc.stderr[-500:]}")
    return proc.stdout

def prepare(name: str) -> dict:
    sample = load_sample(name)
    sha, parent = sample["sha"], sample["parent"]
    if not (present(sha) and present(parent)):
        raise ValueError(f"{name}: {sha[:12]} or its parent is not in the stand, "
                         f"run `prepare.py fetch {name}` first")

    source, tests = split(sample)

    listed = git("diff", "--name-only", parent, sha).stdout.split()
    unaccounted = sorted(set(listed) - set(source) - set(tests))
    if unaccounted:
        raise ValueError(f"{name}: the commit touches files the sample does not "
                         f"account for: {unaccounted}")

    reference = diff(parent, sha, source)
    test = diff(parent, sha, tests)
    check_contract(name, sample, reference, test)

    patch = diff(sha, parent, source)
    if not patch.strip():
        raise ValueError(f"{name}: reverting {source} changes nothing")

    for directory in (settings.PREP_DIR, settings.TASKS_DIR, settings.ORACLE_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    patch_path = settings.PREP_DIR / f"{name}.patch"
    patch_path.write_text(patch, encoding="utf-8")

    task = {k: sample[k] for k in PUBLIC if k in sample}

    task["func"] = name

    task["graded_by"] = [p for p in tests if _is_test_source(p)]
    (settings.TASKS_DIR / f"{name}.json").write_text(
        json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    oracle = {
        "func": name,
        "sha": sha,
        "parent": parent,
        "source": sample["source"],
        "branch": sample["branch"],
        "patch": str(patch_path.relative_to(settings.DATA_DIR)),
        "test_files": tests,

        "reference": reference,
        "test": test,
        "oracle_command": (sample.get("oracle") or {}).get("command"),
        "expected_tests": (sample.get("oracle") or {}).get("tests") or [],
        "failing_tests": None,
    }
    (settings.ORACLE_DIR / f"{name}.json").write_text(
        json.dumps(oracle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {"sample": name, "sha": sha[:12], "patch_lines": len(patch.splitlines()),
            "source": source, "hidden": task["graded_by"],
            "contract": sample.get("contract") or []}

def solvable(name: str) -> dict:
    sample = load_sample(name)
    STAND.reset()
    STAND.reset_to(sample["sha"])

    built = STAND.build()
    if not built.ok:
        STAND.reset()
        return {"sample": name, "ok": False, "stage": "build",
                "tail": built.output[-3000:]}
    installed = STAND.install()
    if not installed.ok:
        STAND.reset()
        return {"sample": name, "ok": False, "stage": "install",
                "tail": installed.output[-3000:]}

    report = STAND.test()
    STAND.reset()
    return {"sample": name, "ok": report.ok and not report.failed, "stage": "check",
            "total": report.total, "failed": report.failed,
            "seconds": round(report.seconds, 1),
            "tail": "" if report.ok else report.output[-3000:]}

def added_lines(patch_text: str) -> list[str]:
    return [line[1:] for line in patch_text.splitlines()
            if line.startswith("+") and not line.startswith("+++")]

def message_texts(lines: list[str]) -> set[str]:
    found = set()
    for line in lines:
        if any(call in line for call in MESSAGE_CALLS):
            found.update(re.findall(r'"((?:[^"\\]|\\.)*)"', line))
    return found

def literal_parts(message: str) -> list[str]:
    parts = re.split(r"%[#0\- +']*[\d.*]*(?:hh|h|ll|l|L|z|j|t)?[a-zA-Z]", message)
    return sorted((p.strip(' "\\.,;:') for p in parts), key=len, reverse=True)

def check_contract(name: str, sample: dict, reference: str, test: str) -> None:
    contract = [c for c in (sample.get("contract") or []) if c.strip()]

    removed = [line[1:] for line in reference.splitlines()
               if line.startswith("-") and not line.startswith("---")]
    introduces = sorted(message_texts(added_lines(reference))
                        - message_texts(removed))
    if introduces and not contract:
        raise ValueError(
            f"{name}: the fix introduces user-visible text and the sample has no "
            f"`contract`, so the test grades wording the task never states:\n  "
            + "\n  ".join(repr(m) for m in introduces[:5]))

    for message in contract:
        anchor = next((p for p in literal_parts(message) if len(p) >= 8), None)
        if anchor and anchor not in test:
            raise ValueError(f"{name}: contract entry is not in the hidden test, "
                             f"so nothing grades it: {message!r} (looked for "
                             f"{anchor!r})")

def _is_test_source(rel: str) -> bool:
    return rel.endswith(TEST_SUFFIXES) and any(part in rel for part in TEST_DIRS)

if __name__ == "__main__":
    import sys

    verbs = {"fetch": fetch, "prepare": prepare, "solvable": solvable}
    if len(sys.argv) < 3 or sys.argv[1] not in verbs:
        raise SystemExit(f"usage: prepare.py [{'|'.join(verbs)}] <sample>...")
    for sample_name in sys.argv[2:]:
        print(json.dumps(verbs[sys.argv[1]](sample_name), ensure_ascii=False)[:2000])

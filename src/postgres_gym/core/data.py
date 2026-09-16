from __future__ import annotations

import hashlib
from pathlib import Path


def task_names(root: Path) -> list[str]:
    return sorted(path.stem for path in (root / "tasks").glob("*.json"))


def split_names(root: Path) -> list[str]:
    splits = root / "splits"
    if not splits.is_dir():
        return []
    return sorted(path.stem for path in splits.glob("*.txt"))


def apply_split(root: Path, names: list[str], split: str | None) -> list[str]:
    if split is None:
        return names
    path = root / "splits" / f"{split}.txt"
    if not path.is_file():
        known = ", ".join(split_names(root)) or "none"
        raise SystemExit(f"suite has no split {split!r}. Known: {known}")
    wanted = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return [name for name in names if name in wanted]


def task_hash(root: Path, name: str) -> str:
    digest = hashlib.sha256()
    for directory, suffix in (
        ("tasks", ".json"),
        ("oracle", ".json"),
        ("prep", ".patch"),
    ):
        path = root / directory / f"{name}{suffix}"
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate(suite) -> list[str]:
    root = suite.data
    names = task_names(root)
    known = set(names)
    issues: list[str] = []
    if not names:
        return ["no tasks"]

    for name in names:
        if not (root / "oracle" / f"{name}.json").is_file():
            issues.append(f"{name}: missing oracle")
            continue
        try:
            task, oracle = suite.load(name)
            suite.mutation(oracle)
        except Exception as exc:  # noqa: BLE001
            issues.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        identity = task.get("func") or task.get("name")
        if identity and identity != name:
            issues.append(f"{name}: task id is {identity!r}")

    for split in split_names(root):
        path = root / "splits" / f"{split}.txt"
        listed = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = sorted(listed - known)
        if missing:
            issues.append(f"split {split}: unknown tasks {', '.join(missing[:5])}")
    return issues

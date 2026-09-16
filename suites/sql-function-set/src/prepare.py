from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core import tree
from postgres_gym.stands.postgres import STAND
from postgres_gym.stands.postgres import build as pgbuild
from postgres_gym.stands.postgres import csource as source

from . import catalog, docs


def _proc_blocks(dat_text: str) -> list[tuple[int, int]]:
    lines = dat_text.splitlines()
    blocks, start = [], None
    for i, line in enumerate(lines):
        if start is None and line.startswith("{"):
            start = i
        if start is not None and line.rstrip().endswith("},"):
            blocks.append((start, i + 1))
            start = None
    return blocks

def remove_catalog_entries(dat_path: Path, proname: str) -> tuple[str, list[str]]:
    text = dat_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    needle = re.compile(rf"proname\s*=>\s*'{re.escape(proname)}'")

    drop: set[int] = set()
    removed: list[str] = []
    for start, end in _proc_blocks(text):
        block = "".join(lines[start:end])
        if needle.search(block):
            drop.update(range(start, end))
            removed.append(block)

    if not removed:
        raise ValueError(f"no pg_proc.dat entry named {proname}")
    kept = "".join(line for i, line in enumerate(lines) if i not in drop)
    return kept, removed

def find_references(pg_src: Path, symbol: str, defining_file: Path) -> list[str]:
    tracked = tree.tracked_files()
    proc = subprocess.run(
        ["grep", "-rnE", rf"\b{re.escape(symbol)}\b", str(pg_src / "src"),
         "--include=*.c", "--include=*.h"],
        capture_output=True, text=True, timeout=180, check=False,
    )
    hits = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        lineno, _, content = rest.partition(":")
        rel = str(Path(path).relative_to(pg_src))
        if rel not in tracked:
            continue
        stripped = content.lstrip()
        if stripped.startswith(("*", "/*", "//")):
            continue

        if Path(path) == defining_file and re.match(rf"^{re.escape(symbol)}\s*\(", content):
            continue
        if re.search(rf"extern\s+Datum\s+{re.escape(symbol)}\s*\(", content):
            continue
        hits.append(f"{rel}:{lineno}")
    return hits

_DAT_REF_RE = re.compile(r"(\w+) => '([a-zA-Z_]\w*)(?:\([^')]*\))?'")
_DAT_FUNC_KEY_RE = re.compile(
    r"(typinput|typoutput|typreceive|typsend|typmodin|typmodout|typanalyze|"
    r"typsubscript|oprcode|oprrest|oprjoin|amproc|castfunc|agg\w*fn|"
    r"rngsubdiff|rngcanonical|prosupport)$")

def catalog_dependents(proname: str, symbols: list[str]) -> dict[str, list[str]]:
    catalog_dir = settings.PG_SRC / "src/include/catalog"
    named: dict[str, list[str]] = {}

    wanted = {proname, *symbols}
    for path in sorted((settings.PG_SRC / "src/backend/catalog").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for name in wanted:
            if re.search(rf"\b{re.escape(name)}\b", text):
                named.setdefault(name, []).append(f"{path.name}")

    for path in sorted(catalog_dir.glob("*.dat")):
        text = path.read_text(encoding="utf-8")
        for key, value in _DAT_REF_RE.findall(text):
            if not _DAT_FUNC_KEY_RE.match(key):
                continue
            if value == proname or (value in symbols and value != proname):
                named.setdefault(value, []).append(f"{path.name}:{key}")

    entries = catalog.load_pg_proc(pgbuild.PG_PROC_DAT)
    for symbol in symbols:
        others = sorted({e["proname"] for e in entries
                         if e.get("prosrc") == symbol and e.get("proname") != proname})
        if others:
            named.setdefault(symbol, []).extend(f"pg_proc.dat:{n}" for n in others)

    return {k: sorted(set(v)) for k, v in named.items()}

def prepare(proname: str, *, mode: str = "stub",
            allow_referenced: bool = False) -> dict:
    if mode not in ("stub", "full"):
        raise ValueError(f"unknown mode {mode!r}")

    pg = settings.PG_SRC
    STAND.reset()

    entries = catalog.by_name(catalog.load_pg_proc(pgbuild.PG_PROC_DAT), proname)
    if not entries:
        raise ValueError(f"{proname} is not in pg_proc.dat")
    symbols = catalog.symbols_from_entries(entries)

    by_file: dict[Path, list[source.FuncExtent]] = {}
    units, blockers = {}, {}
    for sym in symbols:
        path = source.find_symbol_file(pg, sym)
        if path is None:
            raise ValueError(f"cannot locate a unique definition of {sym}")
        if mode == "full":
            refs = find_references(pg, sym, path)
            if refs:
                blockers[sym] = refs
        extent = source.find_function(path, sym)
        by_file.setdefault(path, []).append(extent)
        units[sym] = {
            "file": str(path.relative_to(pg)),
            "code": source.extract(path, extent),
        }

    dependents = catalog_dependents(proname, symbols) if mode == "full" else {}
    if mode == "full" and not allow_referenced:
        if blockers:
            raise ValueError(
                f"{proname}: symbols are referenced elsewhere in the kernel, so "
                f"removal is not self-contained: {blockers}"
            )
        if dependents:
            raise ValueError(
                f"{proname}: the catalog depends on it, so removing only its "
                f"pg_proc entries leaves a dangling reference: {dependents}"
            )

    for path, extents in by_file.items():
        text = (source.excise(path, extents) if mode == "full"
                else source.stub(path, extents))
        path.write_text(text, encoding="utf-8")
    removed_entries: list[str] = []
    if mode == "full":
        dat_text, removed_entries = remove_catalog_entries(pgbuild.PG_PROC_DAT, proname)
        pgbuild.PG_PROC_DAT.write_text(dat_text, encoding="utf-8")

    patch = tree.worktree_diff()
    STAND.reset()

    settings.PREP_DIR.mkdir(parents=True, exist_ok=True)
    settings.TASKS_DIR.mkdir(parents=True, exist_ok=True)
    settings.ORACLE_DIR.mkdir(parents=True, exist_ok=True)

    patch_path = settings.PREP_DIR / f"{proname}.patch"
    patch_path.write_text(patch, encoding="utf-8")

    task = catalog.spec_from_entries(proname, entries)

    doc = docs.lookup(proname)
    task["description"] = doc["description"]
    task["examples"] = doc["examples"]
    task["mode"] = mode
    (settings.TASKS_DIR / f"{proname}.json").write_text(
        json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")

    oracle = {
        "func": proname,
        "mode": mode,
        "patch": str(patch_path.relative_to(settings.DATA_DIR)),
        "symbols": symbols,
        "units": units,
        "catalog_entries": removed_entries,
        "referenced_by": blockers,
        "catalog_dependents": dependents,
        "failing_tests": None,
    }
    (settings.ORACLE_DIR / f"{proname}.json").write_text(
        json.dumps(oracle, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"func": proname, "symbols": symbols, "patch_lines": len(patch.splitlines())}

if __name__ == "__main__":
    import sys
    for name in sys.argv[1:]:
        try:
            print(prepare(name))
        except ValueError as exc:
            print(f"SKIP {name}: {exc}")

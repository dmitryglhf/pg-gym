from __future__ import annotations

import difflib
import re
from pathlib import Path

DISTINCTIVE = 25

_WS = re.compile(r"\s+")


def _normalise(lines) -> list[str]:
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            out.append(_WS.sub(" ", stripped))
    return out


def _removed(patch_text: str) -> list[str]:
    return _normalise(
        line[1:]
        for line in patch_text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


def _added(diff_text: str) -> list[str]:
    return _normalise(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def measure(patch_text: str, diff_text: str) -> dict:
    reference = _removed(patch_text)
    candidate = _added(diff_text)
    if not reference:
        return {"error": "removal patch removed nothing"}

    distinctive = [line for line in reference if len(line) > DISTINCTIVE]
    present = {line for line in candidate if len(line) > DISTINCTIVE}
    hits = sum(1 for line in distinctive if line in present)
    return {
        "verbatim": round(hits / len(distinctive), 3) if distinctive else None,
        "sequence": round(
            difflib.SequenceMatcher(None, reference, candidate).ratio(), 3
        ),
        "reference_lines": len(distinctive),
        "candidate_lines": len(present),
    }


def measure_paths(patch: Path, diff: Path) -> dict:
    if not patch.is_file():
        return {"error": f"no removal patch at {patch}"}
    if not diff.is_file():
        return {"error": f"no diff at {diff}"}
    return measure(
        patch.read_text(encoding="utf-8", errors="replace"),
        diff.read_text(encoding="utf-8", errors="replace"),
    )

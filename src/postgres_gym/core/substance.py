from __future__ import annotations

MIN_REFERENCE_LINES = 21

MIN_ORACLE_DIFF_LINES = 10


def reference_lines(oracle: dict) -> int:
    return sum(
        len(unit.get("code", "").splitlines())
        for unit in (oracle.get("units") or {}).values()
    )


def verdict(oracle: dict) -> dict:
    lines = reference_lines(oracle)
    covered = oracle.get("oracle_diff_lines", 0) or 0
    reasons = []
    if lines < MIN_REFERENCE_LINES:
        reasons.append(f"reference is {lines} lines, too short to get wrong")
    if covered < MIN_ORACLE_DIFF_LINES:
        reasons.append(
            f"removal changes {covered} lines of output, too little to check"
        )
    return {
        "reference_lines": lines,
        "oracle_diff_lines": covered,
        "discriminating": not reasons,
        "reasons": reasons,
    }


def discriminating(oracle: dict) -> bool:
    return verdict(oracle)["discriminating"]

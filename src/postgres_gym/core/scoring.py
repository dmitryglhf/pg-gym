from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CombinedReport:
    ok: bool
    seconds: float
    failed: list[str]
    total: int
    output: str
    statuses: dict[str, str] = field(default_factory=dict)
    diff_lines: int = 0
    diff_by_file: dict[str, int] = field(default_factory=dict)


def combine_reports(reports: list) -> CombinedReport:
    statuses: dict[str, str] = {}
    failed: set[str] = set()
    diff_by_file: dict[str, int] = {}
    for report in reports:
        statuses.update(getattr(report, "statuses", None) or {})
        failed.update(report.failed)
        for name, lines in report.diff_by_file.items():
            diff_by_file[name] = max(lines, diff_by_file.get(name, 0))

    total = len(statuses) or sum(report.total for report in reports)
    return CombinedReport(
        ok=all(report.ok for report in reports),
        seconds=sum(report.seconds for report in reports),
        failed=sorted(failed),
        total=total,
        output="\n".join(report.output for report in reports),
        statuses=statuses,
        diff_lines=sum(diff_by_file.values()),
        diff_by_file=diff_by_file,
    )


def gates(stand, changed: list[str], recreated: list[str] | None = None) -> dict:
    recreated = [f for f in (recreated or []) if stand.is_protected(f)]
    violations = sorted({f for f in changed if stand.is_protected(f)} | set(recreated))

    substantive = [f for f in changed if not stand.is_test_area(f)]
    return {
        "nonempty_diff": {
            "ok": bool(substantive) or bool(recreated),
            "changed": changed,
        },
        "no_test_edits": {"ok": not violations, "violations": violations},
    }


def outcome(stand, report, expected: set[str]) -> dict:
    actual = set(report.failed)
    diverged = stand.diverged(report.diff_by_file)
    statuses = getattr(report, "statuses", None) or {}

    unproven = sorted(t for t in expected if statuses and statuses.get(t) != "passed")
    missing = sorted(t for t in expected if statuses and t not in statuses)
    check = {
        "seconds": round(report.seconds, 1),
        "total": report.total,
        "failed": sorted(actual),
        "diff_lines": report.diff_lines,
        "diff_by_file": report.diff_by_file,
        "diverged": sorted(diverged),
        "skipped": sorted(t for t, s in statuses.items() if s == "skipped"),
        "never_ran": missing,
    }
    if not report.total:
        check["tail"] = report.output[-4000:]
    return {
        "check": check,
        "func_ok": bool(report.total)
        and bool(expected)
        and not unproven
        and not (expected & (actual | diverged)),
        "noregress_ok": bool(report.total) and not (actual - expected),
    }


def verdict(record: dict, checks: list[str]) -> bool:
    if not all(g["ok"] for g in (record.get("gates") or {}).values()):
        return False
    if not (record.get("func_ok") and record.get("noregress_ok")):
        return False
    return all((record.get(name) or {}).get("ok") for name in checks)

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

HARD_ZERO_GATE = "no_test_edits"


def gate_passed(record: dict, name: str) -> bool:
    return bool(((record.get("gates") or {}).get(name) or {}).get("ok"))


def step_passed(record: dict, name: str) -> bool:
    return bool((record.get(name) or {}).get("ok"))


def named_checks_passed(record: dict, names: Sequence[str]) -> bool:
    return bool(names) and all(step_passed(record, name) for name in names)


def tests_ran(record: dict) -> bool:
    return int((record.get("check") or {}).get("total") or 0) > 0


@dataclass(frozen=True)
class RewardStep:
    name: str
    value: float
    passed: Callable[[dict, Sequence[str]], bool]


LADDER = (
    RewardStep(
        "nonempty_diff", 0.1, lambda record, _: gate_passed(record, "nonempty_diff")
    ),
    RewardStep("build", 0.3, lambda record, _: step_passed(record, "build")),
    RewardStep("install", 0.4, lambda record, _: step_passed(record, "install")),
    RewardStep("checks", 0.6, named_checks_passed),
    RewardStep(
        "func_ok",
        0.8,
        lambda record, _: tests_ran(record) and bool(record.get("func_ok")),
    ),
    RewardStep(
        "noregress_ok",
        1.0,
        lambda record, _: tests_ran(record) and bool(record.get("noregress_ok")),
    ),
)


@dataclass
class RewardBreakdown:
    reward: float | None
    usable: bool = True
    rung: str = "none"
    blocked_by: str | None = None
    reached: list[str] = field(default_factory=list)
    detail: str = ""


def score(record: dict, check_names: Sequence[str] | None = None) -> RewardBreakdown:
    if record.get("error"):
        return RewardBreakdown(
            None, usable=False, detail=f"harness fault: {str(record['error'])[:200]}"
        )

    gates = record.get("gates") or {}
    if not gates or HARD_ZERO_GATE not in gates:
        return RewardBreakdown(
            None, usable=False, detail="record has no required gates"
        )

    if check_names is None and "check_names" not in record:
        return RewardBreakdown(None, usable=False, detail="record has no check_names")
    names = list(check_names if check_names is not None else record["check_names"])

    if not gate_passed(record, HARD_ZERO_GATE):
        return RewardBreakdown(
            0.0, blocked_by=HARD_ZERO_GATE, detail="protected files edited"
        )

    reward = 0.0
    rung = "none"
    reached: list[str] = []
    blocked_by = None
    for step in LADDER:
        if step.name == "checks" and not names:
            continue
        if not step.passed(record, names):
            blocked_by = step.name
            break
        reward = step.value
        rung = step.name
        reached.append(step.name)

    detail = "solved" if blocked_by is None else f"stopped at {blocked_by}"
    return RewardBreakdown(
        reward, rung=rung, blocked_by=blocked_by, reached=reached, detail=detail
    )

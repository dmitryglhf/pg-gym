from __future__ import annotations

import argparse
import json

from rich.console import Console
from rich.table import Table
from rich.text import Text

from postgres_gym import settings
from postgres_gym.core import recall
from postgres_gym.core import records as store

YES, NO, DASH = "[green]✓[/]", "[red]✗[/]", "[dim]·[/]"


def _mark(value: bool | None) -> str:
    if value is None:
        return DASH
    return YES if value else NO


def load_runs(pattern: str = "*.json", limit: int | None = None) -> list[dict]:
    files = sorted(store.iter_records(pattern), key=lambda p: p.stat().st_mtime)
    if limit:
        files = files[-limit:]
    out = []
    for f in files:
        try:
            rec = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue

        rec["_file"] = str(f.relative_to(settings.RUNS_DIR))
        out.append(rec)
    return out


def _model(rec: dict) -> str | None:
    return (rec.get("agent_meta") or {}).get("model")


def _short_model(name: str | None) -> str:
    return name.rsplit("/", 1)[-1] if name else "?"


def render_stand(records: list[dict]) -> str:
    seen: dict[tuple, int] = {}
    for rec in records:
        meta = rec.get("agent_meta") or {}
        key = (rec.get("agent", "?"), _model(rec), meta.get("agent_version"))
        seen[key] = seen.get(key, 0) + 1
    lines = []
    for (agent, model, version), count in sorted(seen.items(), key=lambda kv: -kv[1]):
        parts = [f"[bold]{agent}[/]", _short_model(model)]
        if version:
            parts.append(f"[dim]{version}[/]")
        lines.append(f"{' · '.join(parts)} - {count}")
    return "stand: " + "; ".join(lines)


def _gates_cell(rec: dict) -> str:
    gates = rec.get("gates") or {}
    tripped = [name for name, g in gates.items() if not g.get("ok")]
    if not gates:
        return DASH
    return YES if not tripped else f"[red]{', '.join(tripped)}[/]"


def _tests_cell(rec: dict) -> str:
    chk = rec.get("check") or {}
    failed = chk.get("failed") or []
    total = chk.get("total") or 0
    if not total:
        return DASH
    if not failed:
        return f"[green]{total}/{total}[/]"
    return f"[red]{total - len(failed)}/{total}[/]"


def _judge_cell(rec: dict) -> str:
    judge = rec.get("judge")
    if not judge:
        return DASH
    if judge.get("error"):
        return "[red]err[/]"
    score = judge.get("score")
    if not isinstance(score, (int, float)):
        return "?"
    return f"{float(score):.2f}"


def _recall_cell(rec: dict) -> str:
    data = rec.get("recall")
    if data is None:
        data = _recall_from_disk(rec) or {}
    if data.get("error"):
        return "[red]err[/]"
    value = data.get("verbatim")
    if not isinstance(value, (int, float)):
        return DASH
    text = f"{value * 100:.0f}%"

    return f"[bold yellow]{text}[/]" if value >= 0.95 else text


def _recall_from_disk(rec: dict) -> dict | None:
    name = rec.get("_file")
    if not name:
        return None
    return recall.measure_paths(
        settings.PREP_DIR / f"{rec.get('func')}.patch",
        settings.RUNS_DIR / name.replace(".json", ".diff"),
    )


RECALL_THRESHOLD = 0.90


def classify(rec: dict) -> str | None:
    if not rec.get("pass"):
        return None
    data = rec.get("recall") or _recall_from_disk(rec) or {}
    value = data.get("verbatim")
    if not isinstance(value, (int, float)):
        return "written"
    return "recalled" if value >= RECALL_THRESHOLD else "written"


def render_headline(records: list[dict]) -> str:
    total = len(records)
    solved = [r for r in records if r.get("pass")]
    recalled = [r for r in solved if classify(r) == "recalled"]
    written = [r for r in solved if classify(r) == "written"]

    eligible = total - len(recalled)
    out = [
        (
            f"[bold]{len(solved)} of {total} solved[/] "
            f"([dim]{len(solved) / total * 100:.0f}%[/])"
        ),
        (
            f"  [bold yellow]{len(recalled)}[/] of those reproduced the reference "
            f"and are counted as recall, not synthesis"
        ),
        f"  [bold]{len(written)} written from the specification[/] "
        f"([dim]{len(written)} of the {eligible} tasks where that can be told apart, "
        f"{len(written) / eligible * 100:.0f}%[/])"
        if eligible
        else "",
    ]
    return "\n".join(line for line in out if line)


def render_recall(records: list[dict]) -> str | None:
    scores = []
    for rec in records:
        data = rec.get("recall") or _recall_from_disk(rec) or {}
        value = data.get("verbatim")
        if isinstance(value, (int, float)):
            scores.append(value)
    if not scores:
        return None
    scores.sort()
    exact = sum(1 for v in scores if v >= 0.99)
    mid = scores[len(scores) // 2]
    return (
        f"[dim]reference reproduced[/] {len(scores)} diffs · median "
        f"{mid * 100:.0f}% · [bold yellow]{exact}[/] word for word "
        f"([dim]{exact / len(scores) * 100:.0f}% of the set[/])"
    )


def judge_totals(records: list[dict]) -> dict:
    total = {
        "runs": 0,
        "prompt": 0,
        "completion": 0,
        "tokens": 0,
        "cost": 0.0,
        "models": set(),
        "errors": 0,
    }
    for rec in records:
        judge = rec.get("judge")
        if not judge:
            continue
        total["runs"] += 1
        if judge.get("error"):
            total["errors"] += 1
        if model := judge.get("model"):
            total["models"].add(model)
        usage = judge.get("usage") or {}
        total["prompt"] += usage.get("prompt_tokens", 0)
        total["completion"] += usage.get("completion_tokens", 0)
        total["tokens"] += usage.get("total_tokens", 0)
        total["cost"] += float(usage.get("cost") or 0.0)
    return total


def render_totals(total: dict) -> str | None:
    if not total["runs"]:
        return None
    models = ", ".join(sorted(total["models"])) or "?"
    line = (
        f"[dim]judge[/] {total['runs']} runs · {models} · "
        f"{total['tokens']:,} tokens "
        f"([dim]{total['prompt']:,} in / {total['completion']:,} out[/])"
    )
    if total["cost"]:
        line += f" · ${total['cost']:.4f}"
    if total["errors"]:
        line += f" · [red]{total['errors']} failed[/]"
    return line


def check_names(records: list[dict]) -> list[str]:
    names: list[str] = []
    for rec in records:
        for name in rec.get("check_names") or ["callable"]:
            if name not in names:
                names.append(name)
    return names


def table(records: list[dict]) -> Table:
    t = Table(
        title="postgres_gym runs",
        title_style="bold",
        header_style="bold",
        show_lines=False,
    )
    checks = check_names(records)
    t.add_column("function", style="cyan", no_wrap=True)
    t.add_column("agent", no_wrap=True)

    t.add_column("honest", no_wrap=True)
    t.add_column("builds", justify="center")
    for name in checks:
        t.add_column(name, justify="center")
    t.add_column("its tests", justify="center")
    t.add_column("other tests", justify="center")
    t.add_column("suite", no_wrap=True)
    t.add_column("judge", justify="right", no_wrap=True)

    t.add_column("reference\nreproduced", justify="right", no_wrap=True)
    t.add_column("diff", justify="right", style="dim")
    t.add_column("agent s", justify="right", style="dim")
    t.add_column("total s", justify="right", style="dim")
    t.add_column("", justify="center")

    mixed = len({_model(r) for r in records}) > 1

    for rec in records:
        meta = rec.get("agent_meta") or {}
        passed = rec.get("pass")
        agent_cell = rec.get("agent", "?")
        if mixed:
            agent_cell += f"\n[dim]{_short_model(_model(rec))}[/]"
        t.add_row(
            rec.get("func", "?"),
            agent_cell,
            _gates_cell(rec),
            _mark((rec.get("build") or {}).get("ok")),
            *(_mark((rec.get(name) or {}).get("ok")) for name in checks),
            _mark(rec.get("func_ok")),
            _mark(rec.get("noregress_ok")),
            _tests_cell(rec),
            _judge_cell(rec),
            _recall_cell(rec),
            str(rec.get("diff_size", "-")),
            str(meta.get("seconds", "-")),
            str(rec.get("seconds", "-")),
            "[bold green]PASS[/]" if passed else "[bold red]FAIL[/]",
        )
    return t


GLOSSARY = [
    ("honest", "the diff is not empty and no test file was edited"),
    ("builds", "configure, make and make install all succeeded"),
    ("callable", "the function is in the catalog and answers a call"),
    ("its tests", "the tests that removing the function broke are green again"),
    ("other tests", "nothing outside that set broke"),
    ("suite", "the whole regression suite, passing / total"),
    ("judge", "advisory 0..1 from an LLM shown the reference the agent never saw"),
    (
        "reference reproduced",
        (
            "share of the reference's distinctive lines the agent's diff reproduces unchanged. "
            "At or above 90% on a solved task the answer is counted as recalled, not written"
        ),
    ),
    (
        "solved",
        "every gate green: honest diff, builds, callable, its tests back, nothing else broken",
    ),
    (
        "written from the specification",
        "solved, and the diff does not reproduce the reference. This is the number the benchmark is about",
    ),
]


def render_glossary() -> str:
    width = max(len(term) for term, _ in GLOSSARY)
    lines = [
        f"  [bold]{term.ljust(width)}[/]  [dim]{gloss}[/]" for term, gloss in GLOSSARY
    ]
    return "\n".join(lines)


def _oracle(func: str) -> dict:
    path = settings.ORACLE_DIR / f"{func}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def divergence(rec: dict) -> dict | None:
    oracle = _oracle(rec.get("func", ""))
    expected = set(oracle.get("failing_tests") or [])
    if not expected:
        return None
    check = rec.get("check") or {}
    still = set(check.get("failed") or []) & expected
    baseline = oracle.get("oracle_diff_lines") or 0

    residual = check.get("diff_lines")
    return {
        "func": rec.get("func", "?"),
        "oracle_files": len(expected),
        "recovered": len(expected - still),
        "still_red": sorted(still),
        "residual": residual,
        "baseline": baseline,
        "share": (residual / baseline) if (baseline and residual is not None) else None,
    }


def divergence_table(records: list[dict]) -> Table | None:
    rows = []
    for rec in records:
        d = divergence(rec)
        if d and (not rec.get("func_ok") or d["residual"]):
            rows.append((d, rec))
    if not rows:
        return None

    t = Table(
        title="divergence from the reference", title_style="bold", header_style="bold"
    )
    t.add_column("function", style="cyan", no_wrap=True)
    t.add_column("ref tests", justify="right", no_wrap=True)
    t.add_column("recovered", justify="right", no_wrap=True)
    t.add_column("residual lines", justify="right", no_wrap=True)
    t.add_column("of baseline", justify="right", no_wrap=True)
    t.add_column("judge", justify="right", no_wrap=True)
    t.add_column("still failing", style="dim")

    for d, rec in rows:
        share = d["share"]
        if share is None:
            share_cell = DASH
        else:
            colour = "red" if share >= 1 else "yellow" if share > 0.05 else "green"
            share_cell = f"[{colour}]{share * 100:.1f}%[/]"
        judge = rec.get("judge") or {}
        t.add_row(
            d["func"],
            str(d["oracle_files"]),
            f"{d['recovered']}/{d['oracle_files']}",
            f"{d['residual']} / {d['baseline']}"
            if d["residual"] is not None
            else f"[dim]- / {d['baseline']}[/]",
            share_cell,
            f"{judge['score']:.2f}" if judge.get("score") is not None else DASH,
            ", ".join(d["still_red"][:6]) + (" …" if len(d["still_red"]) > 6 else ""),
        )
    return t


def detail(rec: dict, console: Console) -> None:
    for name, gate in (rec.get("gates") or {}).items():
        if gate.get("ok"):
            continue
        console.print(
            f"  [red]gate {name}[/]: {gate.get('violations') or gate.get('changed')}"
        )
    hidden = rec.get("hidden_tests") or {}
    if hidden.get("recreated"):
        console.print(f"  [red]recreated hidden tests[/]: {hidden['recreated']}")
    if hidden.get("files"):
        console.print(f"  [dim]hidden while working: {len(hidden['files'])} files[/]")
    judge = rec.get("judge") or {}
    for d in judge.get("divergences") or []:
        console.print(f"  [yellow]judge[/]: {d}")


def console() -> Console:
    import os
    import sys

    if sys.stdout.isatty():
        return Console()
    return Console(width=int(os.environ.get("POSTGRES_GYM_WIDTH", "150")))


def render_all(runs: list[dict], con: Console) -> None:
    if not runs:
        con.print("[yellow]no run records[/]")
        return
    con.print(render_stand(runs))
    con.print(table(runs))
    con.print(render_glossary())
    if totals := render_totals(judge_totals(runs)):
        con.print(totals)
    if line := render_recall(runs):
        con.print(line)
    con.print()
    con.print(render_headline(runs))
    if second := divergence_table(runs):
        con.print()
        con.print(second)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="show postgres_gym run records")
    ap.add_argument("--glob", default="*.json", help="which records to include")
    ap.add_argument("--last", type=int, default=None, help="only the N most recent")
    ap.add_argument("--details", action="store_true", help="also print gate violations")

    ap.add_argument(
        "--model",
        default=None,
        metavar="SUBSTRING",
        help="only records whose agent model contains this",
    )
    args = ap.parse_args(argv)

    runs = load_runs(args.glob)
    if args.model:
        runs = [r for r in runs if args.model in (_model(r) or "")]
    if args.last:
        runs = runs[-args.last :]
    con = console()
    render_all(runs, con)
    if args.details:
        for rec in runs:
            con.print(Text(rec["_file"], style="bold dim"))
            detail(rec, con)


if __name__ == "__main__":
    main()

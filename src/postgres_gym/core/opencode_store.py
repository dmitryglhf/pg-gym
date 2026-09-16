from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from postgres_gym import settings

MAX_DETAIL = 1000


def _rows(db: Path, sql: str, args: tuple) -> list[tuple]:
    conn = sqlite3.connect(str(db))
    try:
        return list(conn.execute(sql, args))
    finally:
        conn.close()


def summarise(since_ms: int = 0, data_dir: Path | None = None) -> dict:
    root = Path(data_dir) if data_dir else settings.OPENCODE_DATA
    db = root / "opencode.db"
    if not db.is_file():
        return {"source": "opencode", "error": f"no session store at {db}"}

    calls: list[dict] = []
    for (data,) in _rows(
        db,
        "select data from message where time_created >= ? order by time_created",
        (since_ms,),
    ):
        msg = json.loads(data)
        if msg.get("role") != "assistant":
            continue
        clock = msg.get("time") or {}
        start, end = clock.get("created"), clock.get("completed")
        tokens = msg.get("tokens") or {}
        cache = tokens.get("cache") or {}
        calls.append(
            {
                "agent": msg.get("agent"),
                "model": msg.get("modelID"),
                "finish": msg.get("finish"),
                "started": start,
                "seconds": round((end - start) / 1000, 3) if start and end else None,
                "input": tokens.get("input"),
                "output": tokens.get("output"),
                "reasoning": tokens.get("reasoning"),
                "cache_read": cache.get("read"),
            }
        )

    tools: list[dict] = []
    for (data,) in _rows(
        db,
        "select data from part where time_created >= ? order by time_created",
        (since_ms,),
    ):
        part = json.loads(data)
        if part.get("type") != "tool":
            continue

        state = part.get("state") or {}
        clock = state.get("time") or {}
        start, end = clock.get("start"), clock.get("end")
        tools.append(
            {
                "tool": part.get("tool"),
                "status": state.get("status"),
                "started": start,
                "seconds": round((end - start) / 1000, 3) if start and end else None,
            }
        )

    return _totals(calls, tools)


def _tally(values) -> dict:
    out: dict = {}
    for value in values:
        key = str(value) if value is not None else "unfinished"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _totals(calls: list[dict], tools: list[dict]) -> dict:
    def total(rows, field):
        return round(sum(r[field] or 0 for r in rows), 1)

    summary = {
        "source": "opencode",
        "calls": len(calls),
        "tools": len(tools),
        "seconds_llm": total(calls, "seconds"),
        "seconds_tools": total(tools, "seconds"),
        "tokens_input": total(calls, "input"),
        "tokens_output": total(calls, "output"),
        "tokens_reasoning": total(calls, "reasoning"),
        "tokens_cache_read": total(calls, "cache_read"),
        "by_agent": _tally(c["agent"] for c in calls),
        "by_tool": _tally(t["tool"] for t in tools),
        "by_finish": _tally(c["finish"] for c in calls),
        "incomplete": sum(1 for c in calls if c["seconds"] is None),
        "peak_input": max((c["input"] or 0 for c in calls), default=0),
    }
    if len(calls) + len(tools) <= MAX_DETAIL:
        summary["detail"] = {"calls": calls, "tools": tools}
    return summary

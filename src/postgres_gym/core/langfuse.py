from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from postgres_gym import settings


def enabled() -> bool:
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def new_trace_id() -> str:
    return str(uuid.uuid4())


def trace_env(
    trace_id: str, *, func: str, agent: str, level: str, metadata: dict | None = None
) -> dict[str, str]:
    return {
        "LANGFUSE_TRACE_ID": trace_id,
        "LANGFUSE_TRACE_NAME": f"{func} · {level} · {agent}",
        "LANGFUSE_TRACE_TAGS": f"postgres_gym,{func},{level},{agent}",
        "LANGFUSE_TRACE_METADATA": json.dumps(metadata or {}),
    }


def _stamp(millis) -> str | None:
    if not millis:
        return None
    return datetime.fromtimestamp(millis / 1000, UTC).isoformat()


def _event(kind: str, body: dict) -> dict:
    return {"id": str(uuid.uuid4()), "timestamp": _now(), "type": kind, "body": body}


def _score(
    trace_id: str,
    name: str,
    value,
    *,
    kind: str = "NUMERIC",
    comment: str | None = None,
) -> dict:
    body = {
        "id": str(uuid.uuid4()),
        "traceId": trace_id,
        "name": name,
        "dataType": kind,
    }
    if kind == "CATEGORICAL":
        body["value"] = str(value)
    else:
        body["value"] = float(value)
    if comment:
        body["comment"] = comment[:2000]
    return _event("score-create", body)


_PHASE_FIELDS = ("ok", "seconds", "total")


def _check_names(record: dict) -> list[str]:
    return list(record.get("check_names") or ["callable"])


def _phases(trace_id: str, record: dict) -> list[dict]:
    events = []
    for phase in ("build", "install", *_check_names(record), "check"):
        data = record.get(phase)
        if not isinstance(data, dict):
            continue
        events.append(
            _event(
                "span-create",
                {
                    "id": str(uuid.uuid4()),
                    "traceId": trace_id,
                    "name": f"harness:{phase}",
                    "startTime": _now(),
                    "metadata": {k: data[k] for k in _PHASE_FIELDS if k in data},
                    "level": "DEFAULT" if data.get("ok", True) else "ERROR",
                },
            )
        )
    return events


def _agent_calls(trace_id: str, calls: dict) -> list[dict]:
    detail = (calls or {}).get("detail") or {}
    events = []
    for call in detail.get("calls") or []:
        body = {
            "id": str(uuid.uuid4()),
            "traceId": trace_id,
            "name": f"opencode:{call.get('agent') or 'llm'}",
            "startTime": _stamp(call.get("started")) or _now(),
            "model": call.get("model"),
            "metadata": {
                "finish": call.get("finish"),
                "cache_read": call.get("cache_read"),
            },
        }
        if call.get("seconds") is not None:
            body["endTime"] = _stamp(
                (call.get("started") or 0) + call["seconds"] * 1000
            )
        else:
            body["level"] = "WARNING"
        body["usage"] = {
            "input": call.get("input") or 0,
            "output": call.get("output") or 0,
            "unit": "TOKENS",
        }
        events.append(_event("generation-create", body))

    for tool in detail.get("tools") or []:
        events.append(
            _event(
                "span-create",
                {
                    "id": str(uuid.uuid4()),
                    "traceId": trace_id,
                    "name": f"opencode:tool:{tool.get('tool') or '?'}",
                    "startTime": _stamp(tool.get("started")) or _now(),
                    "endTime": _stamp(
                        (tool.get("started") or 0) + (tool.get("seconds") or 0) * 1000
                    ),
                    "metadata": {"status": tool.get("status")},
                    "level": "DEFAULT"
                    if tool.get("status") == "completed"
                    else "WARNING",
                },
            )
        )
    return events


def _judge_generation(trace_id: str, judge: dict) -> list[dict]:
    if not judge or judge.get("error"):
        return []
    usage = judge.get("usage") or {}
    body = {
        "id": str(uuid.uuid4()),
        "traceId": trace_id,
        "name": "judge",
        "startTime": _now(),
        "endTime": _now(),
        "model": judge.get("model"),
        "output": {
            "score": judge.get("score"),
            "equivalence": judge.get("equivalence"),
            "divergences": len(judge.get("divergences") or []),
            "concerns": len(judge.get("concerns") or []),
        },
    }
    if usage:
        body["usage"] = {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
            "unit": "TOKENS",
            "totalCost": usage.get("cost"),
        }
    return [_event("generation-create", body)]


def build_batch(trace_id: str, record: dict, task: dict) -> list[dict]:
    func = record.get("func", "?")
    meta = record.get("agent_meta") or {}
    gates = record.get("gates") or {}
    check = record.get("check") or {}
    judge = record.get("judge") or {}

    verdict = "PASS" if record.get("pass") else "FAIL"
    tripped = [name for name, g in gates.items() if not g.get("ok")]

    batch = [
        _event(
            "trace-create",
            {
                "id": trace_id,
                "name": f"{func} · {meta.get('level', '-')} · {record.get('agent')}",
                "timestamp": _now(),
                "input": task,
                "output": {
                    "verdict": verdict,
                    "gates_tripped": tripped,
                    "tests_failed": len(check.get("failed") or []),
                    "judge": {k: judge.get(k) for k in ("score", "equivalence")},
                },
                "tags": [
                    "postgres_gym",
                    func,
                    str(meta.get("level", "-")),
                    str(record.get("agent")),
                ],
                "metadata": {
                    "agent": record.get("agent"),
                    "level": meta.get("level"),
                    "seconds_total": record.get("seconds"),
                    "seconds_agent": meta.get("seconds"),
                    "calls": (record.get("agent_calls") or {}).get("calls"),
                    "tool_calls": (record.get("agent_calls") or {}).get("tools"),
                    "peak_input_tokens": (record.get("agent_calls") or {}).get(
                        "peak_input"
                    ),
                    "diff_size": record.get("diff_size"),
                    "hidden_tests": len(
                        (record.get("hidden_tests") or {}).get("files") or []
                    ),
                },
            },
        ),
        _event(
            "span-create",
            {
                "id": str(uuid.uuid4()),
                "traceId": trace_id,
                "name": "harness:diff",
                "startTime": _now(),
                "metadata": {
                    "lines": record.get("diff_size"),
                    "files_changed": len(
                        (gates.get("nonempty_diff") or {}).get("changed") or []
                    ),
                },
            },
        ),
    ]
    batch += _phases(trace_id, record)
    batch += _agent_calls(trace_id, record.get("agent_calls") or {})
    batch += _judge_generation(trace_id, judge)

    batch.append(
        _score(trace_id, "pass", 1 if record.get("pass") else 0, kind="BOOLEAN")
    )

    for name in _check_names(record):
        if isinstance(record.get(name), dict):
            batch.append(
                _score(
                    trace_id, name, 1 if record[name].get("ok") else 0, kind="BOOLEAN"
                )
            )
    batch.append(
        _score(trace_id, "func", 1 if record.get("func_ok") else 0, kind="BOOLEAN")
    )
    batch.append(
        _score(
            trace_id,
            "noregress",
            1 if record.get("noregress_ok") else 0,
            kind="BOOLEAN",
        )
    )
    batch.append(
        _score(
            trace_id,
            "gates",
            1 if record.get("gates_ok") else 0,
            kind="BOOLEAN",
            comment=", ".join(tripped) if tripped else None,
        )
    )
    if check:
        batch.append(_score(trace_id, "tests_failed", len(check.get("failed") or [])))
    if record.get("diff_size") is not None:
        batch.append(_score(trace_id, "diff_size", record["diff_size"]))
    if isinstance(judge.get("score"), (int, float)):
        batch.append(_score(trace_id, "llm_score", judge["score"]))
    if judge.get("equivalence"):
        batch.append(
            _score(
                trace_id, "llm_equivalence", judge["equivalence"], kind="CATEGORICAL"
            )
        )
    return batch


def publish(trace_id: str, record: dict, task: dict) -> dict:
    if not enabled():
        return {"sent": False, "reason": "LANGFUSE_PUBLIC_KEY/SECRET_KEY not set"}

    batch = build_batch(trace_id, record, task)
    auth = base64.b64encode(
        f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode()
    ).decode()
    req = urllib.request.Request(
        f"{settings.LANGFUSE_URL.rstrip('/')}/api/public/ingestion",
        data=json.dumps({"batch": batch}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return {
            "sent": False,
            "error": f"HTTP {exc.code}",
            "detail": exc.read().decode()[:500],
            "url": settings.LANGFUSE_URL,
        }
    except Exception as exc:  # noqa: BLE001 - reporting must not break a run
        return {
            "sent": False,
            "error": type(exc).__name__,
            "detail": str(exc)[:300],
            "url": settings.LANGFUSE_URL,
        }

    errors = body.get("errors") or []
    return {
        "sent": not errors,
        "trace_id": trace_id,
        "events": len(batch),
        "url": f"{settings.LANGFUSE_URL.rstrip('/')}/trace/{trace_id}",
        **({"errors": errors[:5]} if errors else {}),
    }


def health() -> tuple[bool, str]:
    url = settings.LANGFUSE_URL.rstrip("/")
    if not enabled():
        return False, "LANGFUSE_PUBLIC_KEY/SECRET_KEY not set"
    try:
        with urllib.request.urlopen(f"{url}/api/public/health", timeout=10) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001
        return False, f"{url} unreachable: {type(exc).__name__} {exc}"

    auth = base64.b64encode(
        f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode()
    ).decode()
    req = urllib.request.Request(
        f"{url}/api/public/projects", headers={"Authorization": f"Basic {auth}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        return False, f"{url} rejected the keys: HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{url}: {type(exc).__name__} {exc}"
    return True, url


def require() -> None:
    ok, detail = health()
    if not ok:
        raise SystemExit(
            f"langfuse required (POSTGRES_GYM_REQUIRE_LANGFUSE=1) but {detail}"
        )


def main() -> None:
    print(f"url          : {settings.LANGFUSE_URL}")
    print(f"public key   : {'set' if settings.LANGFUSE_PUBLIC_KEY else 'MISSING'}")
    print(f"secret key   : {'set' if settings.LANGFUSE_SECRET_KEY else 'MISSING'}")
    if not enabled():
        print(
            "\nNot configured. markov reads the same variables and silently skips\n"
            "tracing when either key is empty, so this would look like success."
        )
        return
    probe = new_trace_id()
    record = {
        "func": "langfuse-check",
        "agent": "none",
        "pass": True,
        "gates": {},
        "check": {},
        "diff_size": 0,
        "agent_meta": {"level": "-"},
    }
    print(json.dumps(publish(probe, record, {"func": "langfuse-check"}), indent=2))


if __name__ == "__main__":
    main()

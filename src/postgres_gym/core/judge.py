from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from postgres_gym import settings

SYSTEM = """\
You review C code written for the PostgreSQL backend. You are given the public \
specification of a built-in SQL function, the reference implementation from \
upstream PostgreSQL, and a diff produced by an agent that was asked to write \
the function from the specification alone.

Judge the diff against the specification and the reference. Be concrete: name \
inputs where the two implementations would return different results.

Reply with JSON only, no prose around it, in this shape:

{
  "score": <number between 0 and 1>,
  "equivalence": "equivalent" | "narrower" | "wider" | "different",
  "divergences": ["<input> -> reference gives X, candidate gives Y", ...],
  "concerns": ["memory or overflow issues, missing error paths, ...", ...],
  "conventions": "<one line on fit with surrounding PostgreSQL style>",
  "summary": "<one or two sentences>"
}

"equivalent" means identical observable behaviour on every input. "wider" means \
the candidate also transforms inputs the reference leaves alone; "narrower" the \
reverse. "different" is for outright wrong or incomparable behaviour. An empty \
divergences list is only valid alongside "equivalent".

The score is your overall judgement of how well the candidate answers the \
specification, where 1.0 is indistinguishable from the reference in behaviour \
and fit, and 0.0 is unrelated or non-functional. Weight observable behaviour \
far above style. Do not round to a coarse scale -- 0.72 is a useful answer.
"""


def build_prompt(specification: str, reference: str, diff: str) -> str:
    return (
        "## Specification given to the agent\n"
        + specification
        + "\n\n## Reference implementation (upstream, agent never saw this)\n```c\n"
        + reference
        + "\n```"
        + "\n\n## Diff the agent produced\n```diff\n"
        + diff[:60000]
        + "\n```"
    )


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else None
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return {"error": "unparseable judge reply", "raw": text[:2000]}


def review(
    specification: str,
    reference: str,
    diff: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    key: str | None = None,
) -> dict:

    key = key or os.environ.get(settings.JUDGE_KEY_ENV)
    if not key:
        return {"error": f"{settings.JUDGE_KEY_ENV} is not set"}

    model = model or settings.JUDGE_MODEL
    base_url = (base_url or settings.JUDGE_BASE_URL).rstrip("/")

    payload: dict = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_prompt(specification, reference, diff)},
        ],
    }

    on_openrouter = "openrouter.ai" in base_url
    if on_openrouter:
        payload["usage"] = {"include": True}
        payload["max_tokens"] = settings.JUDGE_MAX_TOKENS
        payload["reasoning"] = {"max_tokens": settings.JUDGE_REASONING_TOKENS}

    last: dict = {}
    for attempt in range(2):
        if attempt and on_openrouter:
            payload["reasoning"] = {"effort": "low"}
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=settings.JUDGE_TIMEOUT) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return {
                "error": f"HTTP {exc.code}",
                "detail": exc.read().decode()[:500],
                "model": model,
            }
        except Exception as exc:  # noqa: BLE001 - the record should carry any failure
            return {
                "error": type(exc).__name__,
                "detail": str(exc)[:500],
                "model": model,
            }

        text = (body.get("choices") or [{}])[0].get("message", {}).get("content")
        if not text:
            last = {"error": "empty judge reply", "model": model}
            if usage := body.get("usage"):
                last["usage"] = usage
            continue
        out = _extract_json(text)
        out["model"] = model
        if usage := body.get("usage"):
            out["usage"] = usage
        if "error" not in out:
            if attempt:
                out["retried"] = True
            return out
        last = out

    last["retried"] = True
    return last

from __future__ import annotations

import json
import os
from pathlib import Path


def configure():
    raw = os.environ.get("POSTGRES_GYM_HARNESS_CONFIG")
    if not raw:
        return
    config = json.loads(raw)
    model = os.environ["GOOSE_MODEL"]
    max_turns = int(config.get("max_turns", 50))
    os.environ["GOOSE_MAX_TURNS"] = str(max_turns)
    os.environ["GOOSE_MODE"] = "auto"
    os.environ["GOOSE_CONTEXT_STRATEGY"] = config.get("context_strategy", "summarize")
    os.environ["GOOSE_TEMPERATURE"] = str(config.get("temperature", 0))
    os.environ["GOOSE_DISABLE_SESSION_NAMING"] = "true"
    os.environ["GOOSE_RANDOM_THINKING_MESSAGES"] = "false"
    opencode = {
        "$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
        "model": "pgpro/" + model,
        "provider": {"pgpro": {"npm": "@ai-sdk/openai-compatible", "name": "Postgres Gym",
            "options": {"baseURL": os.environ["PGPRO_HOST"].rstrip("/") + "/v1", "apiKey": "{env:POSTGRES_GYM_PROVIDER_KEY}"},
            "models": {model: {"name": model, "limit": {"context": int(config.get("context_length", 32768)), "output": int(config.get("max_tokens", 4096))}}}}},
        "agent": {"build": {"steps": max_turns, "temperature": float(config.get("temperature", 0))}},
        "tools": {"webfetch": False}, "permission": {"webfetch": "deny"},
    }
    directory = Path.home() / ".config" / "opencode"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "opencode.jsonc").write_text(json.dumps(opencode), encoding="utf-8")
    os.environ["OPENCODE_CONFIG"] = str(directory / "opencode.jsonc")

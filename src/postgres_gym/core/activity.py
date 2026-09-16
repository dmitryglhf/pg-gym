from __future__ import annotations

import json
import os
import time


def emit(kind: str, **payload):
    if os.environ.get("POSTGRES_GYM_EVENTS") == "1":
        print("@pg-gym " + json.dumps({"kind": kind, "at": time.time(), "payload": payload}, ensure_ascii=False), flush=True)

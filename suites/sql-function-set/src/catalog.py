from __future__ import annotations

import json
import subprocess
from pathlib import Path

_PERL = r"""
use strict; use warnings;
local $/; my $txt = <STDIN>;
my $data = eval $txt;
die "eval failed: $@" if $@;
use JSON::PP;
print JSON::PP->new->canonical->encode($data);
"""

def load_pg_proc(dat_path: Path) -> list[dict]:
    text = dat_path.read_text(encoding="utf-8")
    proc = subprocess.run(
        ["perl", "-e", _PERL],
        input=text, capture_output=True, text=True, timeout=120, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to parse {dat_path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)

def by_name(entries: list[dict], proname: str) -> list[dict]:
    return [e for e in entries if e.get("proname") == proname]

def spec_from_entries(proname: str, entries: list[dict]) -> dict:
    variants = [
        {
            "arguments": e.get("proargtypes", ""),
            "returns": e.get("prorettype", ""),
            "kind": e.get("prokind", "f"),
            "volatile": e.get("provolatile", "i"),
            "description": e.get("descr", ""),
        }
        for e in entries
    ]
    return {"func": proname, "variants": variants}

def symbols_from_entries(entries: list[dict]) -> list[str]:
    return sorted({e["prosrc"] for e in entries if "prosrc" in e})

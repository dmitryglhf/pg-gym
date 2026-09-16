from __future__ import annotations

import json
from pathlib import Path

from postgres_gym.core import payload, substance
from postgres_gym.core.protocol import Suite

QUOTED_TYPES = {"any", "char"}

SYSTEM_RULES = """\
You are working in a real PostgreSQL 17 source tree. Implement the requested SQL \
built-in function so that it is callable from SQL and behaves correctly.

That means both halves:
  1. the C implementation, in the appropriate file under src/backend/utils/adt/
  2. the catalog registration in src/include/catalog/pg_proc.dat

Follow the conventions of the surrounding code (PG_GETARG_*/PG_RETURN_* macros, \
palloc, ereport for errors).

Do NOT modify anything under src/test/. Editing expected output instead of fixing \
the code is detected and scores zero.
"""

def _type_name(arg: str) -> str:
    return f'"{arg}"' if arg.lower() in QUOTED_TYPES else arg

class SqlFunctionSet(Suite):
    id = "sql-function-set"
    stand = "postgres"
    check_names = ("callable",)

    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[1]

    @property
    def data(self) -> Path:
        return self.root / "data"

    def task_names(self) -> list[str]:
        return sorted(p.stem for p in (self.data / "tasks").glob("*.json"))

    def runnable(self) -> list[str]:
        out = []
        for name in self.task_names():
            path = self.data / "oracle" / f"{name}.json"
            if not path.is_file():
                continue
            oracle = json.loads(path.read_text())
            if oracle.get("usable") and substance.discriminating(oracle):
                out.append(name)
        return out

    def load(self, name: str) -> tuple[dict, dict]:
        return payload.load(name, self.data)

    def mutation(self, oracle: dict) -> str:
        return payload.mutation(oracle, self.data)

    def private_dirs(self) -> list[Path]:
        return [self.data / "prep", self.data / "oracle", self.data / "tasks"]

    def prompt(self, task: dict, oracle: dict) -> str:
        lines = [SYSTEM_RULES, "", f"Function to implement: {task['func']}", "",
                 "Registered signatures required:"]
        for v in task["variants"]:
            lines.append(f"  {task['func']}({v['arguments']}) -> {v['returns']}"
                         f"   -- {v['description']}")
        if task.get("description"):
            lines += ["", f"Description: {task['description']}"]
        if task.get("examples"):
            lines += ["", "Examples from the documentation:"]
            lines += [f"  {e}" for e in task["examples"]]

        return "\n".join(lines)

    def hide(self, task: dict, oracle: dict) -> list[str]:
        from postgres_gym.stands.postgres import isolate
        needles = [task["func"], *(oracle.get("symbols") or [])]
        return isolate.leaking_tests(needles, oracle.get("failing_tests"))

    def reference_files(self, oracle: dict) -> list[str]:
        from postgres_gym.stands.postgres import isolate
        return isolate.reference_tests(oracle.get("failing_tests"))

    def secret_strings(self, oracle: dict) -> list[str]:
        seen: list[str] = []
        for unit in (oracle.get("units") or {}).values():
            for line in unit.get("code", "").splitlines():
                line = line.strip()
                if len(line) >= 30 and line not in seen:
                    seen.append(line)
        seen.sort(key=lambda s: not s.startswith(("*", "/*", "//")))
        return seen

    def checks(self, task: dict, stand) -> dict:
        sigs = []
        for v in task["variants"]:
            args = ",".join(_type_name(a) for a in v["arguments"].split())
            sigs.append(f"('{task['func']}({args})')")
        sql = ("SELECT bool_and(to_regprocedure(sig) IS NOT NULL) "
               f"FROM (VALUES {', '.join(sigs)}) v(sig)")

        out = stand.query(sql, tag=task["func"])
        return {"callable": {
            "ok": out.ok and out.output.strip().startswith("t"),
            "seconds": round(out.seconds, 1),
            "output": out.output.strip()[-500:],
        }}

    def specification(self, task: dict) -> str:
        spec = [f"Function: {task['func']}"]
        for v in task.get("variants", []):
            spec.append(f"  {task['func']}({v['arguments']}) -> {v['returns']}"
                        f"   -- {v['description']}")
        if task.get("description"):
            spec.append(f"Description: {task['description']}")
        for ex in task.get("examples") or []:
            spec.append(f"Example: {ex}")
        return "\n".join(spec)

    def reference(self, oracle: dict) -> str:
        parts = []
        for unit in (oracle.get("units") or {}).values():
            parts.append(f"/* {unit['file']} */\n{unit['code']}")
        for entry in oracle.get("catalog_entries") or []:
            parts.append(f"/* src/include/catalog/pg_proc.dat */\n{entry}")
        return "\n".join(parts)

SUITE = SqlFunctionSet()

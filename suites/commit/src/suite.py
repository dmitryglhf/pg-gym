from __future__ import annotations

import json
from pathlib import Path

from postgres_gym.core import payload
from postgres_gym.core.protocol import Suite

SYSTEM_RULES = """\
You are working in a real PostgreSQL 17 source tree, at an upstream commit with \
one bug still in it. Fix the bug in the C code.

The tree builds and tests itself with its own machinery: `make` at the root, \
`make -C src/test/regress check` for the regression suite. Read the code around \
the area you are changing and follow its conventions.

You are graded by the upstream regression test for this bug. That test is off \
disk while you work and is put back afterwards, so you cannot read it, and \
writing anything under src/test/ is detected and scores zero. Everything the \
test checks is in the task below; make the code do that and the test passes.

The rest of the regression suite runs too. A fix that breaks something else is \
not a fix.
"""

class CommitSet(Suite):
    id = "commit"
    stand = "postgres"

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
            task = json.loads((self.data / "tasks" / f"{name}.json").read_text())

            if task.get("goal") == "TODO":
                continue
            path = self.data / "oracle" / f"{name}.json"
            if not path.is_file():
                continue
            oracle = json.loads(path.read_text())
            if not oracle.get("usable"):
                continue

            graded = set(oracle.get("expected_tests") or [])
            if graded and not graded <= set(oracle.get("failing_tests") or []):
                continue
            out.append(name)
        return out

    def expected_failures(self, oracle: dict) -> set[str]:
        graded = set(oracle.get("expected_tests") or [])
        measured = set(oracle.get("failing_tests") or [])
        return graded if graded and graded <= measured else measured

    def test_names(self, oracle: dict) -> list[str]:
        return list(oracle.get("expected_tests") or [])

    def load(self, name: str) -> tuple[dict, dict]:
        return payload.load(name, self.data)

    def mutation(self, oracle: dict) -> str:
        return payload.mutation(oracle, self.data)

    def base(self, oracle: dict) -> str | None:
        return oracle.get("sha")

    def private_dirs(self) -> list[Path]:
        return [self.data / "samples", self.data / "oracle",
                self.data / "tasks", self.data / "prep"]

    def prompt(self, task: dict, oracle: dict) -> str:
        lines = [SYSTEM_RULES, "", f"Area: {task['area']}", "", task["goal"]]

        if task.get("contract"):
            lines += ["",
                      ("The test compares output as text. Where your fix produces "
                       "these, use them exactly as written:")]
            lines += [f"  {message}" for message in task["contract"]]
        if task.get("graded_by"):
            lines += ["",
                      "The hidden test that grades this is "
                      + ", ".join(task["graded_by"]) + "."]
        return "\n".join(lines)

    def hide(self, task: dict, oracle: dict) -> list[str]:
        return [p for p in (oracle.get("test_files") or []) if _is_test_source(p)]

    def reference_files(self, oracle: dict) -> list[str]:
        return list(oracle.get("test_files") or [])

    def secret_strings(self, oracle: dict) -> list[str]:
        seen: list[str] = []
        for text in (oracle.get("reference") or "", oracle.get("test") or ""):
            added, removed = _diff_sides(text)
            for line in added:
                if line in removed or line in seen:
                    continue

                if len(line) >= 30 and sum(c.isalnum() for c in line) >= 15:
                    seen.append(line)

        seen.sort(key=lambda s: not s.startswith(("--", "*", "/*", "//", "#")))
        return seen

    def specification(self, task: dict) -> str:
        return f"Area: {task['area']}\n\n{task['goal']}"

    def reference(self, oracle: dict) -> str:
        return oracle.get("reference") or ""

def _diff_sides(text: str) -> tuple[list[str], set[str]]:
    added, removed = [], set()
    for line in text.splitlines():
        if line.startswith(("+++", "---", "diff --git", "index ", "@@")):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.add(line[1:].strip())
    return added, removed

def _is_test_source(rel: str) -> bool:
    return (rel.endswith((".sql", ".out", ".spec"))
            and any(part in rel for part in ("/sql/", "/expected/", "/specs/")))

SUITE = CommitSet()

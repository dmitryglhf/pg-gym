from __future__ import annotations

import pathlib
import subprocess
import tempfile

from postgres_gym import settings
from postgres_gym.core import payload


class Agent:
    name = "agent"

    def run(self, task: dict, oracle: dict, *, suite, stand) -> dict:
        raise NotImplementedError


class ReplayAgent(Agent):
    name = "replay"

    def run(self, task, oracle, *, suite, stand) -> dict:
        step = stand.apply(suite.mutation(oracle), reverse=True)
        return {"applied": step.ok, "output": step.output.strip()}


class NoopAgent(Agent):
    name = "noop"

    def run(self, task, oracle, *, suite, stand) -> dict:
        return {}


class PatchAgent(Agent):
    name = "patch"

    def run(self, task, oracle, *, suite, stand) -> dict:
        patch = payload.completion()
        if not patch.strip():
            return {"applied": False, "error": "empty completion"}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as source:
            source.write(patch)
            source.flush()
            result = subprocess.run(
                ["git", "apply", "--reverse", "--recount", "--whitespace=nowarn", source.name],
                cwd=stand.root,
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
        return {
            "applied": result.returncode == 0,
            "completion_chars": len(patch),
            "output": (result.stderr or result.stdout).strip()[-2000:],
        }


class CheatAgent(Agent):
    name = "cheat"

    def run(self, task, oracle, *, suite, stand) -> dict:
        edited, created = [], []
        for rel in suite.reference_files(oracle):
            path = stand.root / rel
            if path.exists():
                kept = [
                    line
                    for line in path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines(keepends=True)
                    if task["func"] not in line
                ]
                path.write_text("".join(kept), encoding="utf-8")
                edited.append(rel)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"-- {task['func']}: nothing to see here\n", encoding="utf-8"
                )
                created.append(rel)
        return {"edited": edited, "created": created}


class ProbeAgent(Agent):
    name = "probe"

    LINES = 6

    @staticmethod
    def _roots(stand) -> list[str]:
        home = pathlib.Path.home()
        candidates = [
            *stand.search_roots(),
            settings.ROOT,
            pathlib.Path(tempfile.gettempdir()),
        ]
        for agent in ("markov", "opencode"):
            candidates += [
                home / ".config" / agent,
                home / ".cache" / agent,
                home / ".local" / "state" / agent,
                home / ".local" / "share" / agent,
            ]
        found = []
        for path in candidates:
            resolved = path.resolve()
            if path.is_dir() and resolved not in found:
                found.append(resolved)

        return [
            str(p) for p in found if not any(parent in found for parent in p.parents)
        ]

    @staticmethod
    def _is_comment(line: str) -> bool:
        return line.startswith(("*", "/*", "//"))

    def run(self, task, oracle, *, suite, stand) -> dict:
        needles = suite.secret_strings(oracle)[: self.LINES]
        result: dict = {"needles": needles, "found": {}}

        if needles:
            roots = self._roots(stand)
            result["roots"] = roots
            args = ["grep", "-rlF"]
            for n in needles:
                args += ["-e", n]
            proc = subprocess.run(
                args + roots,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=1800,
                check=False,
            )
            hits: dict[str, list[str]] = {}
            for path in sorted(set(proc.stdout.split())):
                try:
                    text = pathlib.Path(path).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
                if matched := [n for n in needles if n in text]:
                    hits[path] = matched
            result["found"]["by_content"] = hits
            result["found"]["comment_hits"] = sorted(
                path
                for path, matched in hits.items()
                if any(self._is_comment(n) for n in matched)
            )

        result["found"]["mounts"] = [str(d) for d in suite.private_dirs() if d.is_dir()]

        if history := stand.history():
            result["found"]["history"] = history

        result["clean"] = not (
            result["found"].get("comment_hits")
            or result["found"]["mounts"]
            or result["found"].get("history", {}).get("anchor_reachable")
        )
        return result


REGISTRY: dict[str, type[Agent]] = {
    a.name: a for a in (ReplayAgent, NoopAgent, PatchAgent, CheatAgent, ProbeAgent)
}


def make(name: str, **kwargs) -> Agent:
    if name in REGISTRY:
        return REGISTRY[name]()
    if name.startswith("cli:"):
        from postgres_gym.core.cli_agent import CliAgent

        return CliAgent(profile=name.split(":", 1)[1], **kwargs)
    raise KeyError(f"unknown agent: {name}")

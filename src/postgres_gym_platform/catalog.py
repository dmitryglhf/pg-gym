from __future__ import annotations

import hashlib
import json
from pathlib import Path


class Catalog:
    def __init__(self, root: Path):
        from postgres_gym.core import data, registry
        self.suites: list[dict] = []
        self.tasks: dict[str, dict[str, dict]] = {}
        self.splits: dict[tuple[str, str], list[str]] = {}
        for suite in registry.available():
            names = suite.runnable()
            tasks = {}
            for name in names:
                public, oracle = suite.load(name)
                tasks[name] = {"suite": suite.id, "name": name, "prompt": suite.prompt(public, oracle),
                               "task_hash": data.task_hash(suite.data, name), "data": {}}
            self.tasks[suite.id] = tasks
            split_names = sorted(p.stem for p in (suite.data / "splits").glob("*.txt"))
            for split in split_names:
                self.splits[suite.id, split] = data.apply_split(suite.data, names, split)
            suite_hash = hashlib.sha256(json.dumps(
                {"tasks": [(name, tasks[name]["task_hash"]) for name in sorted(tasks)], "splits": {split: self.splits[suite.id, split] for split in split_names}}
            ).encode()).hexdigest()
            self.suites.append({"id": suite.id, "stand": suite.stand, "tasks": len(names),
                                "total_tasks": len(suite.task_names()), "splits": split_names,
                                "suite_hash": suite_hash})

    def select(self, suite: str, tasks: list[str] | None = None, split: str | None = None) -> list[dict]:
        if suite not in self.tasks:
            raise ValueError("Unknown suite")
        if split and (suite, split) not in self.splits:
            raise ValueError("Unknown split")
        available = self.splits[suite, split] if split else list(self.tasks[suite])
        selected = list(dict.fromkeys(tasks)) if tasks else available
        if not selected or any(task not in available for task in selected):
            raise ValueError("Select runnable tasks within the requested split")
        return [self.tasks[suite][name] for name in selected]

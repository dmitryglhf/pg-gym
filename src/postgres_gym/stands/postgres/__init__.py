from __future__ import annotations

import re
import shutil
import subprocess
from contextlib import AbstractContextManager
from pathlib import Path

from postgres_gym import settings
from postgres_gym.core import tree
from postgres_gym.core.process import Step
from postgres_gym.stands.postgres import build as _build
from postgres_gym.stands.postgres import isolate as _isolate

_ALT_EXPECTED_RE = re.compile(r"_\d+$")

TEST_ROOT = "src/test/"

SCRATCH = ("src/test/regress",)

class PostgresStand:
    name = "postgres"

    @property
    def root(self):
        return settings.PG_SRC

    def reset(self) -> str:
        return tree.reset_pristine(SCRATCH)

    def reset_to(self, sha: str | None = None) -> None:
        tree.reset_tree(sha, SCRATCH)

    def anchor(self) -> str:
        return tree.pristine_sha()

    def apply(self, patch: str, reverse: bool = False) -> Step:
        return tree.apply_patch_text(patch, reverse=reverse)

    def commit_baseline(self, message: str) -> str:
        return tree.commit_baseline(message)

    def sever_history(self) -> str:
        return tree.sever_history()

    def restore_history(self) -> bool:
        return tree.restore_history()

    def diff(self) -> str:
        return tree.diff()

    def changed_files(self) -> list[str]:
        return tree.changed_files()

    def search_roots(self) -> list[Path]:
        return [settings.PG_SRC.parent, settings.PG_SRC, settings.PG_PREFIX]

    def history(self) -> dict:
        if not (shutil.which("git") and settings.PG_GIT_DIR.is_dir()):
            return {}
        git = ["git", f"--git-dir={settings.PG_GIT_DIR}"]

        def ask(*args: str) -> str:
            proc = subprocess.run(git + list(args), capture_output=True,
                                  text=True, errors="replace", timeout=120,
                                  check=False)
            return proc.stdout.strip()

        return {
            "commits_reachable": ask("rev-list", "--all", "--count"),
            "anchor_reachable": ask("rev-parse", "--verify", "--quiet",
                                    tree.PRISTINE_REF) or None,
        }

    def build(self, changed: list[str] | None = None) -> Step:
        return _build.build(changed)

    def install(self) -> Step:
        return _build.install()

    def test(self, tests: list[str] | None = None) -> _build.CheckResult:
        return _build.check(tests)

    def query(self, sql: str, tag: str = "smoke") -> Step:
        return _build.smoke(sql, tag=tag)

    def hide(self, paths: list[str]) -> AbstractContextManager:
        return _isolate.tests_hidden(paths)

    def leaking_tests(self, needles: list[str], failing: list[str] | None) -> list[str]:
        return _isolate.leaking_tests(needles, failing)

    def is_test_area(self, path: str) -> bool:
        return path.startswith(TEST_ROOT)

    def is_protected(self, path: str) -> bool:
        return self.is_test_area(path) and (_isolate.is_test_source(path)
                                            or _isolate.is_test_plan(path))

    def diverged(self, diff_by_file: dict[str, int]) -> set[str]:
        out = set()
        for name in diff_by_file:
            out.add(name)
            out.add(_ALT_EXPECTED_RE.sub("", name))
        return out

STAND = PostgresStand()

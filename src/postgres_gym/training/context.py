from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from postgres_gym import settings


def buggy_context(suite, oracle: dict) -> str:
    patch = suite.mutation(oracle)
    base = suite.base(oracle) or "refs/postgres-gym/pristine"
    return context_from_patch(settings.PG_GIT_DIR, base, patch)


def context_from_patch(git_dir: Path, base: str, patch: str, radius: int = 20) -> str:
    regions: dict[str, list[tuple[int, int]]] = {}
    path = None
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            rel = PurePosixPath(path)
            if rel.is_absolute() or ".." in rel.parts or path.startswith("src/test/"):
                raise ValueError(f"unsupported context path: {path}")
            regions.setdefault(path, [])
        elif line.startswith("+++ "):
            raise ValueError("context requires an existing buggy-side file")
        elif match := re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line):
            if path is None:
                raise ValueError("hunk without a file")
            start = int(match[1])
            count = int(match[2]) if match[2] is not None else 1
            regions[path].append((max(0, start - 1 - radius), start - 1 + count + radius))
    if not regions:
        raise ValueError("mutation contains no context files")
    with tempfile.TemporaryDirectory(prefix="postgres-gym-context-") as directory:
        root = Path(directory)
        for name in regions:
            content = subprocess.run(
                ["git", f"--git-dir={git_dir.resolve()}", "show", f"{base}:{name}"],
                capture_output=True, check=True,
            ).stdout
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"], cwd=root,
            input=patch, text=True, capture_output=True, check=True,
        )
        excerpts = []
        for name, spans in regions.items():
            lines = (root / name).read_text().splitlines(keepends=True)
            end = 0
            for first, last in sorted(spans):
                first, last = max(first, end), min(last, len(lines))
                if first < last:
                    excerpts.append(f"File: {name}, lines {first + 1}-{last}\n```\n"
                                    + "".join(lines[first:last]) + "\n```")
                    end = last
        return "\n\n".join(excerpts)

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FuncExtent:
    path: Path
    start: int
    body_start: int
    end: int


def find_symbol_file(pg_src: Path, symbol: str) -> Path | None:
    proc = subprocess.run(
        [
            "grep",
            "-rlE",
            rf"^{re.escape(symbol)}\(",
            str(pg_src / "src/backend"),
            "--include=*.c",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    files = [f for f in proc.stdout.strip().splitlines() if f]
    if len(files) != 1:
        return None
    return Path(files[0])


def _match_brace(lines: list[str], open_line: int) -> int:
    depth = 0
    in_block_comment = False
    seen_open = False

    for i in range(open_line, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]
            nxt = line[j + 1] if j + 1 < len(line) else ""

            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    j += 2
                    continue
            elif ch == "/" and nxt == "*":
                in_block_comment = True
                j += 2
                continue
            elif ch == "/" and nxt == "/":
                break
            elif ch in "\"'":
                quote = ch
                j += 1
                while j < len(line):
                    if line[j] == "\\":
                        j += 2
                        continue
                    if line[j] == quote:
                        break
                    j += 1
            elif ch == "{":
                depth += 1
                seen_open = True
            elif ch == "}":
                depth -= 1
                if seen_open and depth == 0:
                    return i
            j += 1

    raise ValueError(f"unbalanced braces starting at line {open_line + 1}")


def find_function(path: Path, symbol: str) -> FuncExtent:
    lines = path.read_text(encoding="utf-8").splitlines()

    name_re = re.compile(rf"^{re.escape(symbol)}\s*\(")
    name_line = next((i for i, line in enumerate(lines) if name_re.match(line)), None)
    if name_line is None:
        raise ValueError(f"{symbol} not defined at column 0 in {path}")

    body_start = name_line
    while (
        body_start > 0
        and lines[body_start - 1].strip()
        and not lines[body_start - 1].startswith(("/*", " *", "*/"))
    ):
        body_start -= 1

    start = body_start
    k = start - 1
    while k >= 0 and not lines[k].strip():
        k -= 1
    if k >= 0 and lines[k].rstrip().endswith("*/"):
        while k >= 0 and not lines[k].lstrip().startswith("/*"):
            k -= 1
        if k >= 0:
            start = k

    open_line = next(i for i in range(name_line, len(lines)) if "{" in lines[i])
    end = _match_brace(lines, open_line) + 1

    if end < len(lines) and not lines[end].strip():
        end += 1

    return FuncExtent(path=path, start=start, body_start=body_start, end=end)


def excise(path: Path, extents: list[FuncExtent]) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    drop: set[int] = set()
    for e in extents:
        drop.update(range(e.start, e.end))
    return "".join(line for i, line in enumerate(lines) if i not in drop)


def extract(path: Path, extent: FuncExtent) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return "".join(lines[extent.start : extent.end])


def stub_text(symbol: str) -> str:
    return (
        f"Datum\n{symbol}(PG_FUNCTION_ARGS)\n"
        "{\n"
        f'\telog(ERROR, "{symbol} is not implemented");\n'
        "\tPG_RETURN_NULL();\n"
        "}\n"
    )


def stub(path: Path, extents: list[FuncExtent]) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for extent in sorted(extents, key=lambda e: e.start, reverse=True):
        symbol = _symbol_at(lines, extent)
        lines[extent.start : extent.end] = [stub_text(symbol), "\n"]
    return "".join(lines)


def _symbol_at(lines: list[str], extent: FuncExtent) -> str:
    for line in lines[extent.body_start : extent.end]:
        if m := re.match(r"^([a-zA-Z_]\w*)\(PG_FUNCTION_ARGS\)", line):
            return m.group(1)
    raise ValueError(f"no PG_FUNCTION_ARGS definition at line {extent.body_start}")

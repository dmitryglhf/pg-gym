from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any

from rich.console import Console
from rich.table import Table


class OutputMode(str, Enum):
    table = "table"
    json = "json"
    jsonl = "jsonl"


@dataclass(frozen=True)
class CliContext:
    output: OutputMode = OutputMode.table
    no_color: bool = False


def emit(value: Any, context: CliContext, *, stream=None) -> None:
    stream = stream or sys.stdout
    if context.output is OutputMode.json:
        print(json.dumps(value, ensure_ascii=False, allow_nan=False), file=stream)
    elif context.output is OutputMode.jsonl:
        if isinstance(value, list):
            for item in value:
                print(
                    json.dumps(item, ensure_ascii=False, allow_nan=False), file=stream
                )
        else:
            print(json.dumps(value, ensure_ascii=False, allow_nan=False), file=stream)
    else:
        console = Console(file=stream, no_color=context.no_color, force_terminal=False)
        page = isinstance(value, dict) and "items" in value and "next" in value
        rows = value["items"] if page else value
        table = Table(show_lines=False)

        def cell(item):
            return (
                json.dumps(item, ensure_ascii=False, allow_nan=False)
                if isinstance(item, (dict, list))
                else ("—" if item is None else str(item))
            )

        if (
            isinstance(rows, list)
            and rows
            and all(isinstance(row, dict) for row in rows)
        ):
            columns = list(dict.fromkeys(key for row in rows for key in row))
            for column in columns:
                table.add_column(str(column), overflow="fold")
            for row in rows:
                table.add_row(*(cell(row.get(column)) for column in columns))
        elif isinstance(rows, dict):
            table.add_column("Field")
            table.add_column("Value", overflow="fold")
            for key, item in rows.items():
                table.add_row(str(key), cell(item))
        else:
            table.add_column("Value")
            for item in rows if isinstance(rows, list) else [rows]:
                table.add_row(cell(item))
        console.print(table, markup=False)
        if page and value["next"] is not None:
            console.print("Next cursor: " + str(value["next"]), markup=False)


def fail(message: str, code: int = 2) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)

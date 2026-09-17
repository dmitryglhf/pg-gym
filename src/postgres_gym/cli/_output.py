from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, TextIO

import typer
from rich.console import Console
from rich.table import Table


class OutputMode(str, Enum):
    table = "table"
    json = "json"
    jsonl = "jsonl"


@dataclass(frozen=True)
class Runtime:
    """Invocation-wide options set by the root callback and read by every command."""

    output: OutputMode = OutputMode.table
    no_color: bool = False
    context: str | None = None
    timeout: float = 60.0
    wait_timeout: float = 600.0


def runtime(ctx: typer.Context) -> Runtime:
    return ctx.find_root().obj or Runtime()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def emit(ctx: typer.Context, value: Any, *, stream: TextIO | None = None) -> None:
    settings = runtime(ctx)
    stream = stream or sys.stdout
    if settings.output is OutputMode.json:
        print(dumps(value), file=stream)
    elif settings.output is OutputMode.jsonl:
        for item in value if isinstance(value, list) else [value]:
            print(dumps(item), file=stream)
    else:
        console = Console(file=stream, no_color=settings.no_color, force_terminal=False)
        page = isinstance(value, dict) and "items" in value and "next" in value
        console.print(table(value["items"] if page else value), markup=False)
        if page and value["next"] is not None:
            console.print("Next cursor: " + str(value["next"]), markup=False)


def cell(item: Any) -> str:
    if isinstance(item, (dict, list)):
        return dumps(item)
    return "-" if item is None else str(item)


def table(rows: Any) -> Table:
    result = Table(show_lines=False)
    if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
        columns = list(dict.fromkeys(key for row in rows for key in row))
        for column in columns:
            result.add_column(str(column), overflow="fold")
        for row in rows:
            result.add_row(*(cell(row.get(column)) for column in columns))
    elif isinstance(rows, dict):
        result.add_column("Field")
        result.add_column("Value", overflow="fold")
        for key, item in rows.items():
            result.add_row(str(key), cell(item))
    else:
        result.add_column("Value")
        for item in rows if isinstance(rows, list) else [rows]:
            result.add_row(cell(item))
    return result

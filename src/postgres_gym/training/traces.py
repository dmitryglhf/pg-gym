from __future__ import annotations

import argparse
import json
from pathlib import Path


def examples(messages: list[dict]) -> list[dict]:
    rows = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant" and index:
            rows.append({"prompt": messages[:index], "completion": [message]})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    count = 0
    with args.input.open(encoding="utf-8") as source, args.output.open("w", encoding="utf-8") as target:
        for line in source:
            if line.strip():
                for row in examples(json.loads(line)["messages"]):
                    target.write(json.dumps(row, ensure_ascii=False) + "\n")
                    count += 1
    print(count)

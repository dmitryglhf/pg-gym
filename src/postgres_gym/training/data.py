from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from postgres_gym.core import registry
from postgres_gym.training import settings
from postgres_gym.training.context import buggy_context


def split(names: list[str], test_ratio: float, seed: int) -> tuple[list[str], list[str]]:
    shuffled = names.copy()
    random.Random(seed).shuffle(shuffled)
    test_count = max(1, round(len(shuffled) * test_ratio))
    return sorted(shuffled[test_count:]), sorted(shuffled[:test_count])


def prompt(suite, task: dict, oracle: dict) -> str:
    return (
        suite.prompt(task, oracle)
        + "\n\nBuggy source excerpts (repair locations supplied by the task harness):\n"
        + buggy_context(suite, oracle)
        + "\n\nReturn only the unified diff from the fixed tree to the current buggy tree."
    )


def prompt_rows(split: str) -> list[dict]:
    from postgres_gym import Gym

    rows = []
    for suite_id in settings.suites():
        suite = registry.load(suite_id)
        for name in Gym(suite_id).tasks(split):
            task, oracle = suite.load(name)
            rows.append({"suite": suite_id, "task": name, "prompt": prompt(suite, task, oracle)})
    return rows


def row(suite, name: str) -> dict:
    task, oracle = suite.load(name)
    patch = (suite.data / oracle["patch"]).read_text(encoding="utf-8")
    return {
        "messages": [
            {"role": "user", "content": prompt(suite, task, oracle)},
            {"role": "assistant", "content": patch},
        ]
    }


def write_split(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(names) + "\n", encoding="utf-8")


def write_dataset(path: Path, suite, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for name in names:
            output.write(json.dumps(row(suite, name), ensure_ascii=False) + "\n")


def build_gym_sft_dataset(output: Path, test_ratio: float, seed: int) -> list[dict]:
    datasets: list[dict] = []
    for suite_id in settings.suites():
        suite = registry.load(suite_id)
        all_train, all_test = split(suite.task_names(), test_ratio, seed)
        runnable = set(suite.runnable())
        train = [name for name in all_train if name in runnable]
        test = [name for name in all_test if name in runnable]
        write_split(suite.data / "splits" / "train.txt", all_train)
        write_split(suite.data / "splits" / "test.txt", all_test)
        write_dataset(output / suite_id / "train.jsonl", suite, train)
        write_dataset(output / suite_id / "test.jsonl", suite, test)
        datasets.append(
            {
                "suite": suite_id,
                "train": len(train),
                "test": len(test),
                "all_train": len(all_train),
                "all_test": len(all_test),
            }
        )
    for part, target in (("train", "train.jsonl"), ("test", "valid.jsonl"), ("test", "test.jsonl")):
        rows = []
        for suite_id in settings.suites():
            source = output / suite_id / f"{part}.jsonl"
            rows.extend(source.read_text(encoding="utf-8").splitlines())
        (output / target).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return datasets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=settings.path("POSTGRES_GYM_SFT_DATA", "artifacts/gym-sft-data"))
    parser.add_argument("--test-ratio", type=float, default=settings.decimal("POSTGRES_GYM_TRAIN_TEST_RATIO", 0.2))
    parser.add_argument("--seed", type=int, default=settings.integer("POSTGRES_GYM_TRAIN_SEED", 42))
    args = parser.parse_args()
    if not 0 < args.test_ratio < 1:
        parser.error("--test-ratio must be between zero and one")
    print(json.dumps(build_gym_sft_dataset(args.output, args.test_ratio, args.seed)))

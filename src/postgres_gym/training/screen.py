from __future__ import annotations

import argparse
import collections
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from postgres_gym import Gym
from postgres_gym.training.chat import configure_template
from postgres_gym.training.data import prompt_rows
from postgres_gym.training.reward import append_rollout, applied, rollout


def graded(path: Path) -> dict[tuple[str, str], list[float]]:
    rewards: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    if not path.exists():
        return rewards
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        rewards[(record["suite"], record["task"])].append(record["reward"] or 0.0)
    return rewards


def first_per_suite(rows: list[dict], limit: int) -> list[dict]:
    if not limit:
        return rows
    taken: collections.Counter[str] = collections.Counter()
    kept = []
    for row in rows:
        if taken[row["suite"]] < limit:
            taken[row["suite"]] += 1
            kept.append(row)
    return kept


def liveness(rewards: dict[tuple[str, str], list[float]]) -> list[dict]:
    rows = []
    for (suite, task), values in sorted(rewards.items()):
        rows.append({
            "suite": suite, "task": task, "rewards": values,
            "live": len(set(values)) > 1,
            "reward_mean": sum(values) / len(values),
            "reward_max": max(values),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    by_suite: dict[str, dict] = {}
    for row in rows:
        counts = by_suite.setdefault(row["suite"], {"tasks": 0, "live": 0, "rewarded": 0, "reward_sum": 0.0})
        counts["tasks"] += 1
        counts["live"] += row["live"]
        counts["rewarded"] += row["reward_max"] > 0
        counts["reward_sum"] += sum(row["rewards"])
    return {"suites": by_suite, "tasks": len(rows), "live": sum(row["live"] for row in rows)}


def write_results(output: Path, rewards: dict[tuple[str, str], list[float]]) -> dict:
    rows = liveness(rewards)
    output.mkdir(parents=True, exist_ok=True)
    (output / "liveness.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    live = [f"{row['suite']}\t{row['task']}" for row in rows if row["live"]]
    (output / "live-tasks.txt").write_text("\n".join(live) + ("\n" if live else ""), encoding="utf-8")
    summary = summarize(rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=3,
                        help="containers graded at once, bounded by the docker VM memory")
    args = parser.parse_args()
    rows = first_per_suite(prompt_rows(args.split), args.limit)
    if args.workers > len(rows):
        parser.error("--workers must not exceed the number of tasks, rounds keep tasks distinct")

    audit = args.output / "rollouts.jsonl"
    rewards = graded(audit)
    resumed = {key: len(values) for key, values in rewards.items()}
    gyms = {row["suite"]: Gym(row["suite"]) for row in rows}
    mlx = importlib.import_module("mlx_lm")
    sampling = importlib.import_module("mlx_lm.sample_utils")
    model, tokenizer = mlx.load(args.model, adapter_path=args.adapter)
    configure_template(tokenizer, args.model)
    sampler = sampling.make_sampler(temp=args.temperature)
    lock = threading.Lock()

    def grade(row: dict) -> None:
        record = rollout(gyms[row["suite"]], row["task"], row["completion"])
        with lock:
            rewards[(row["suite"], row["task"])].append(record["reward"] or 0.0)
            append_rollout(audit, record)
            print(json.dumps({"suite": row["suite"], "task": row["task"], "applied": applied(record),
                              "patch_chars": len(record["patch"]), "reward": record["reward"]}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for round_index in range(args.samples):
            for row in rows:
                if resumed.get((row["suite"], row["task"]), 0) > round_index:
                    continue
                text = tokenizer.apply_chat_template(
                    [{"role": "user", "content": row["prompt"]}], add_generation_prompt=True, tokenize=False
                )
                completion = mlx.generate(
                    model, tokenizer, prompt=text, max_tokens=args.max_tokens, sampler=sampler, verbose=False
                )
                pool.submit(grade, {**row, "completion": completion})
            print(json.dumps({"round": round_index + 1, "of": args.samples}), flush=True)

    print(json.dumps(write_results(args.output, rewards)), flush=True)


if __name__ == "__main__":
    main()

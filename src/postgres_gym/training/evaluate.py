from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from postgres_gym import Gym
from postgres_gym.training.chat import configure_template
from postgres_gym.training.data import prompt_rows
from postgres_gym.training.reward import append_rollout, applied, rollout


def summarize(records: list[dict]) -> dict:
    rewards = [record["reward"] or 0.0 for record in records]
    return {
        "tasks": len(records),
        "applied": sum(applied(record) for record in records),
        "nonempty_patch": sum(1 for record in records if record["patch"]),
        "rewarded": sum(1 for reward in rewards if reward > 0),
        "reward_mean": sum(rewards) / len(records) if records else 0.0,
        "reward_max": max(rewards, default=0.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()
    mlx = importlib.import_module("mlx_lm")
    sampling = importlib.import_module("mlx_lm.sample_utils")
    # mlx_lm annotates load() as a Union of a 2-tuple and a 3-tuple.
    model, tokenizer = mlx.load(  # ty: ignore[invalid-assignment]
        args.model, adapter_path=args.adapter
    )
    configure_template(tokenizer, args.model)
    sampler = sampling.make_sampler(temp=args.temperature)
    rows = prompt_rows(args.split)
    if args.limit:
        rows = rows[: args.limit]
    gyms: dict[str, Gym] = {}
    records = []
    for row in rows:
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": row["prompt"]}],
            add_generation_prompt=True,
            tokenize=False,
        )
        completion = mlx.generate(
            model,
            tokenizer,
            prompt=text,
            max_tokens=args.max_tokens,
            sampler=sampler,
            verbose=False,
        )
        gym = gyms.setdefault(row["suite"], Gym(row["suite"]))
        record = rollout(gym, row["task"], completion)
        append_rollout(args.output / "rollouts.jsonl", record)
        records.append(record)
        print(
            json.dumps(
                {
                    "task": row["task"],
                    "applied": applied(record),
                    "patch_chars": len(record["patch"]),
                    "reward": record["reward"],
                }
            ),
            flush=True,
        )
    summary = summarize(records)
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()

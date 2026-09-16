from __future__ import annotations

import argparse
import importlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from postgres_gym.training.chat import configure_template, validate_lengths


def within_length(tokenizer, row: dict, max_length: int) -> bool:
    return len(tokenizer.apply_chat_template(row["messages"], return_dict=False)) <= max_length


def prepare(data: Path, directory: Path, tokenizer, max_length: int, skip: bool) -> dict[str, str]:
    kept = {}
    for part in ("train", "valid"):
        rows = [json.loads(line) for line in (data / f"{part}.jsonl").read_text().splitlines()]
        if skip:
            fitting = [row for row in rows if within_length(tokenizer, row, max_length)]
        else:
            validate_lengths(tokenizer, rows, max_length)
            fitting = rows
        kept[part] = f"{len(fitting)}/{len(rows)}"
        (directory / f"{part}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fitting), encoding="utf-8"
        )
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-length", type=int, default=12288)
    parser.add_argument("--skip-overlength", action="store_true")
    parser.add_argument("--steps", type=int, default=153)
    parser.add_argument("--num-layers", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-5)
    parser.add_argument("--steps-per-eval", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    lora = importlib.import_module("mlx_lm.lora")
    np.random.seed(args.seed)
    model, tokenizer, _ = lora.load(args.model, return_config=True)
    configure_template(tokenizer, args.model)
    with tempfile.TemporaryDirectory(prefix="postgres-gym-mlx-sft-") as directory:
        kept = prepare(args.data, Path(directory), tokenizer, args.max_length, args.skip_overlength)
        print(json.dumps({"examples": kept, "max_length": args.max_length}), flush=True)
        config = dict(lora.CONFIG_DEFAULTS)
        config.update(model=args.model, data=directory, adapter_path=args.output,
                      max_seq_length=args.max_length, iters=args.steps, seed=args.seed,
                      num_layers=args.num_layers, learning_rate=args.learning_rate,
                      steps_per_eval=args.steps_per_eval, save_every=args.steps_per_eval,
                      val_batches=10, steps_per_report=5, clear_cache_threshold=1,
                      train=True, test=False, batch_size=1, mask_prompt=True, grad_checkpoint=True)
        options = SimpleNamespace(**config)
        train, valid, _ = lora.load_dataset(options, tokenizer)
        lora.train_model(options, model, train, valid)
    tokenizer.save_pretrained(args.output)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

from datasets import load_dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

from postgres_gym.training import settings
from postgres_gym.training.chat import tokenizer_for, validate_lengths
from postgres_gym.training.grpo import MODEL_ID, TARGET_MODULES


def adapter_config(kind: str, rank: int, dropout: float) -> LoraConfig:
    options = {"r": rank, "lora_alpha": rank, "lora_dropout": dropout, "target_modules": TARGET_MODULES, "bias": "none", "task_type": "CAUSAL_LM"}
    if kind == "nora":
        options["use_nora"] = True
    elif kind == "nora-init":
        options["use_nora"] = "init"
    elif kind == "bimi":
        options["init_lora_weights"] = "bimi"
    try:
        return LoraConfig(**cast(Any, options))
    except TypeError as exc:
        if kind != "lora":
            raise RuntimeError("install the training-nora dependency group for this adapter") from exc
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--output", type=Path, default=settings.path("POSTGRES_GYM_SFT_OUTPUT", "artifacts/postgres-gym-deepseek-lora"))
    parser.add_argument("--adapter", choices=["lora", "nora", "nora-init", "bimi"], default="lora")
    parser.add_argument("--rank", type=int, default=settings.integer("POSTGRES_GYM_SFT_RANK", 32))
    parser.add_argument("--dropout", type=float, default=settings.decimal("POSTGRES_GYM_SFT_DROPOUT", 0.05))
    parser.add_argument("--max-length", type=int, default=settings.integer("POSTGRES_GYM_SFT_MAX_LENGTH", 12288))
    parser.add_argument("--epochs", type=float, default=settings.decimal("POSTGRES_GYM_SFT_EPOCHS", 1.0))
    parser.add_argument("--max-steps", type=int, default=settings.integer("POSTGRES_GYM_SFT_MAX_STEPS", -1))
    parser.add_argument("--learning-rate", type=float, default=settings.decimal("POSTGRES_GYM_SFT_LEARNING_RATE", 2e-4))
    parser.add_argument("--batch-size", type=int, default=settings.integer("POSTGRES_GYM_SFT_BATCH_SIZE", 1))
    parser.add_argument("--grad-accum", type=int, default=settings.integer("POSTGRES_GYM_SFT_GRAD_ACCUM", 8))
    parser.add_argument("--seed", type=int, default=settings.integer("POSTGRES_GYM_TRAIN_SEED", 42))
    parser.add_argument("--dtype", choices=["auto", "bfloat16", "float16", "float32"], default="auto")
    args = parser.parse_args()
    dataset = load_dataset("json", data_files=str(args.dataset), split="train")
    tokenizer = tokenizer_for(args.model)
    validate_lengths(tokenizer, dataset, args.max_length)
    if "messages" in dataset.column_names:
        dataset = dataset.map(lambda row: {"prompt": row["messages"][:-1], "completion": row["messages"][-1:]},
                              remove_columns=["messages"])
    output = args.output
    model_init_kwargs = {} if args.dtype == "auto" else {"dtype": args.dtype}
    config = SFTConfig(output_dir=str(output), num_train_epochs=args.epochs, max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size, gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.learning_rate, max_length=args.max_length, packing=False, shuffle_dataset=True,
        completion_only_loss=True, gradient_checkpointing=True, use_cache=False, logging_steps=1,
        save_strategy="epoch", report_to="none", seed=args.seed, model_init_kwargs=model_init_kwargs or None)
    trainer = SFTTrainer(model=args.model, args=config, train_dataset=dataset,
                         peft_config=adapter_config(args.adapter, args.rank, args.dropout),
                         processing_class=tokenizer)
    trainer.train()
    trainer.save_model(str(output))

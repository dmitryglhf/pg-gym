from __future__ import annotations

import argparse
from pathlib import Path

from datasets import Dataset
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoConfig, AutoModelForCausalLM, TrainerCallback
from trl import GRPOConfig, GRPOTrainer

from postgres_gym import Gym
from postgres_gym.core import registry
from postgres_gym.core.activity import emit
from postgres_gym.training import settings
from postgres_gym.training.chat import tokenizer_for
from postgres_gym.training.data import prompt
from postgres_gym.training.reward import audited_reward

MODEL_ID = settings.text("POSTGRES_GYM_TRAIN_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def selected(path: Path | None) -> set[tuple[str, str]] | None:
    if path is None:
        return None
    chosen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        suite_id, _, name = line.partition("\t")
        if not name:
            raise ValueError(f"{path} must hold tab separated suite and task, got {line!r}")
        chosen.add((suite_id.strip(), name.strip()))
    if not chosen:
        raise ValueError(f"{path} names no tasks")
    return chosen


def interleave(rows: list[dict]) -> list[dict]:
    by_suite: dict[str, list[dict]] = {}
    for row in rows:
        by_suite.setdefault(row["suite"], []).append(row)
    queues = list(by_suite.values())
    ordered = []
    for index in range(max(len(queue) for queue in queues)):
        ordered += [queue[index] for queue in queues if index < len(queue)]
    return ordered


def tasks(split: str, tokenizer, max_prompt_length: int, chosen: set[tuple[str, str]] | None,
          balance: bool) -> Dataset:
    rows = []
    for suite_id in settings.suites():
        suite = registry.load(suite_id)
        for name in Gym(suite_id).tasks(split):
            if chosen is not None and (suite_id, name) not in chosen:
                continue
            task, oracle = suite.load(name)
            messages = [{"role": "user", "content": prompt(suite, task, oracle)}]
            if max_prompt_length and len(tokenizer.apply_chat_template(messages, return_dict=False)) > max_prompt_length:
                continue
            rows.append({"prompt": messages, "suite": suite_id, "task": name})
    if not rows:
        raise ValueError("every prompt was dropped by --tasks-file or --max-prompt-length")
    return Dataset.from_list(interleave(rows) if balance else rows)


def peft_config(rank: int, num_layers: int, total_layers: int) -> LoraConfig:
    if not 0 < num_layers <= total_layers:
        raise ValueError(f"--num-layers must be between 1 and {total_layers}")
    return LoraConfig(
        r=rank,
        lora_alpha=20,
        lora_dropout=0.0,
        target_modules=TARGET_MODULES,
        layers_to_transform=list(range(total_layers - num_layers, total_layers)),
        bias="none",
        task_type="CAUSAL_LM",
    )


class ActivityCallback(TrainerCallback):
    def on_log(self, args, state, control, logs=None, **kwargs):
        import math
        values = {key: float(value) for key, value in (logs or {}).items()
                  if key not in {"step", "total"} and isinstance(value, (int, float)) and math.isfinite(value)}
        emit("metrics", step=state.global_step, total=args.max_steps, **values)

    def on_save(self, args, state, control, **kwargs):
        emit("phase", phase="checkpoint", step=state.global_step)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--output", type=Path, default=settings.path("POSTGRES_GYM_GRPO_OUTPUT", "artifacts/grpo"))
    parser.add_argument("--split", default=settings.text("POSTGRES_GYM_GRPO_SPLIT", "train"))
    parser.add_argument("--max-steps", type=int, default=settings.integer("POSTGRES_GYM_GRPO_MAX_STEPS", 153))
    parser.add_argument("--rank", type=int, default=settings.integer("POSTGRES_GYM_GRPO_RANK", 8))
    parser.add_argument("--num-layers", type=int, default=settings.integer("POSTGRES_GYM_GRPO_NUM_LAYERS", 16))
    parser.add_argument("--num-generations", type=int, default=settings.integer("POSTGRES_GYM_GRPO_NUM_GENERATIONS", 2))
    parser.add_argument("--max-completion-length", type=int, default=settings.integer("POSTGRES_GYM_GRPO_MAX_COMPLETION_LENGTH", 2048))
    parser.add_argument("--score-truncated", action="store_true",
                        help="keep truncated completions in the group, scored by the harness instead of masked")
    parser.add_argument("--batch-size", type=int, default=settings.integer("POSTGRES_GYM_GRPO_BATCH_SIZE", 0),
                        help="completions per forward pass, defaults to the whole group")
    parser.add_argument("--max-prompt-length", type=int, default=settings.integer("POSTGRES_GYM_GRPO_MAX_PROMPT_LENGTH", 0),
                        help="drop tasks whose prompt exceeds this, instead of truncating away the buggy code")
    parser.add_argument("--tasks-file", type=Path,
                        help="restrict training to tab separated suite and task lines, as written by the screener")
    parser.add_argument("--balance-suites", action="store_true",
                        help="visit suites in turn instead of shuffling, so no suite drives a whole run alone")
    parser.add_argument("--beta", type=float, default=settings.decimal("POSTGRES_GYM_GRPO_BETA", 0.001),
                        help="KL weight against the warm start, the brake on losing suites that yield no gradient")
    parser.add_argument("--learning-rate", type=float, default=settings.decimal("POSTGRES_GYM_GRPO_LEARNING_RATE", 1e-5))
    parser.add_argument("--save-steps", type=int, default=10)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--seed", type=int, default=settings.integer("POSTGRES_GYM_TRAIN_SEED", 42))
    args = parser.parse_args()
    batch_size = args.batch_size or args.num_generations
    if args.num_generations % batch_size:
        raise ValueError("--num-generations must be a multiple of --batch-size")

    config = GRPOConfig(
        output_dir=str(args.output), max_steps=args.max_steps,
        per_device_train_batch_size=batch_size, gradient_accumulation_steps=args.num_generations // batch_size,
        learning_rate=args.learning_rate, num_generations=args.num_generations,
        max_completion_length=args.max_completion_length, beta=args.beta, loss_type="dapo",
        mask_truncated_completions=not args.score_truncated, gradient_checkpointing=True, use_cache=False,
        bf16=True, logging_steps=1, save_strategy="steps", save_steps=args.save_steps, save_total_limit=args.save_total_limit, report_to="none",
        remove_unused_columns=False, seed=args.seed, shuffle_dataset=not args.balance_suites,
    )
    if args.adapter:
        model = AutoModelForCausalLM.from_pretrained(args.model, dtype="bfloat16")
        model = PeftModel.from_pretrained(model, args.adapter, is_trainable=True)
    else:
        total_layers = AutoConfig.from_pretrained(args.model).num_hidden_layers
        model = AutoModelForCausalLM.from_pretrained(args.model, dtype="bfloat16")
        model = get_peft_model(model, peft_config(args.rank, args.num_layers, total_layers))
    tokenizer = tokenizer_for(args.model)
    dataset = tasks(args.split, tokenizer, args.max_prompt_length, selected(args.tasks_file), args.balance_suites)
    print(f"{len(dataset)} prompts, batch {batch_size} of {args.num_generations} generations", flush=True)
    trainer = GRPOTrainer(model=model, reward_funcs=audited_reward(args.output), args=config, train_dataset=dataset,
                          processing_class=tokenizer, callbacks=[ActivityCallback()])
    emit("phase", phase="training", tasks=len(dataset))
    trainer.train()
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))


if __name__ == "__main__":
    main()

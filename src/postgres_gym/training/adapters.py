from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from peft import LoraConfig
from safetensors import safe_open
from safetensors.torch import save_file


def convert_mlx_lora(source: Path, output: Path, model: str) -> None:
    parameters = json.loads((source / "adapter_config.json").read_text())["lora_parameters"]
    rank = int(parameters["rank"])
    scale = float(parameters["scale"])
    alpha = round(scale * rank)
    if alpha != scale * rank:
        raise ValueError("MLX scale times rank must be an integer PEFT alpha")
    weights: dict[str, torch.Tensor] = {}
    modules: set[str] = set()
    layers: set[int] = set()
    with safe_open(source / "adapters.safetensors", framework="pt") as adapter:
        for key in sorted(adapter.keys()):
            tensor = adapter.get_tensor(key)
            if key.endswith(".lora_a"):
                name = key.removesuffix(".lora_a")
                weights[f"base_model.model.{name}.lora_A.weight"] = tensor.T.contiguous()
            elif key.endswith(".lora_b"):
                name = key.removesuffix(".lora_b")
                weights[f"base_model.model.{name}.lora_B.weight"] = tensor.T.contiguous()
            else:
                raise ValueError(f"unsupported MLX adapter weight {key}")
            parts = name.split(".")
            layers.add(int(parts[parts.index("layers") + 1]))
            modules.add(parts[-1])
            if tensor.shape[1 if key.endswith(".lora_a") else 0] != rank:
                raise ValueError(f"rank mismatch in {key}")
    if not weights:
        raise ValueError("adapter has no weights")
    for key in weights:
        other = key.replace(".lora_A.", ".lora_B.") if ".lora_A." in key else key.replace(".lora_B.", ".lora_A.")
        if other not in weights:
            raise ValueError(f"missing paired weight for {key}")
    output.mkdir(parents=True, exist_ok=True)
    save_file(weights, output / "adapter_model.safetensors")
    LoraConfig(r=rank, lora_alpha=alpha, lora_dropout=float(parameters.get("dropout", 0)), target_modules=sorted(modules),
               layers_to_transform=sorted(layers), bias="none", task_type="CAUSAL_LM",
               base_model_name_or_path=model).save_pretrained(str(output))


def convert_peft_lora(source: Path, output: Path) -> None:
    config = json.loads((source / "adapter_config.json").read_text())
    rank = int(config["r"])
    scale = float(config["lora_alpha"]) / rank
    weights: dict[str, torch.Tensor] = {}
    keys: set[str] = set()
    layers: set[int] = set()
    with safe_open(source / "adapter_model.safetensors", framework="pt") as adapter:
        for key in sorted(adapter.keys()):
            tensor = adapter.get_tensor(key)
            if key.endswith(".lora_A.weight"):
                name, suffix = key.removesuffix(".lora_A.weight"), "lora_a"
            elif key.endswith(".lora_B.weight"):
                name, suffix = key.removesuffix(".lora_B.weight"), "lora_b"
            else:
                raise ValueError(f"unsupported PEFT adapter weight {key}")
            name = name.removeprefix("base_model.model.")
            weights[f"{name}.{suffix}"] = tensor.T.contiguous()
            parts = name.split(".")
            index = parts.index("layers") + 1
            layers.add(int(parts[index]))
            keys.add(".".join(parts[index + 1:]))
    if not weights:
        raise ValueError("adapter has no weights")
    if sorted(layers) != list(range(min(layers), max(layers) + 1)):
        raise ValueError("MLX applies LoRA to a contiguous tail of layers")
    output.mkdir(parents=True, exist_ok=True)
    save_file(weights, output / "adapters.safetensors")
    (output / "adapter_config.json").write_text(json.dumps({
        "fine_tune_type": "lora", "num_layers": len(layers),
        "lora_parameters": {"rank": rank, "scale": scale,
                            "dropout": float(config.get("lora_dropout", 0)), "keys": sorted(keys)},
    }, indent=4) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    convert_mlx_lora(args.source, args.output, args.model)


def main_peft() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert_peft_lora(args.source, args.output)

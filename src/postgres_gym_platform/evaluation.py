from __future__ import annotations

from typing import Any

from .runtime import Runtime, atomic_json


def evaluate(runtime: Runtime) -> dict:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, set_seed

    from postgres_gym import Gym
    from postgres_gym.training.chat import tokenizer_for
    from postgres_gym.training.data import prompt
    from postgres_gym.training.reward import rollout

    config = runtime.config
    path, artifact = runtime.materialize(config["artifact_id"])
    base = path
    if artifact["kind"] == "adapter":
        base, _ = runtime.materialize(artifact["metadata"]["base_artifact_id"])
    runtime.events.emit("phase", phase="loading")
    set_seed(config["seed"])
    tokenizer = tokenizer_for(str(base))
    model: Any = AutoModelForCausalLM.from_pretrained(str(base), dtype=torch.bfloat16, trust_remote_code=False, device_map="cuda")
    if artifact["kind"] == "adapter":
        model = PeftModel.from_pretrained(model, str(path))
    model.eval()
    gym = Gym(config["suite"])
    selected = list(config["task_hashes"])
    report = runtime.directory / "evaluation"
    report.mkdir()
    episodes: list[dict] = []
    for index, task in enumerate(selected):
        if gym.task(task).task_hash != config["task_hashes"][task]:
            raise ValueError("Suite changed since submission")
        public, oracle = gym.suite.load(task)
        messages = [{"role": "user", "content": prompt(gym.suite, public, oracle)}]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to("cuda")
        runtime.events.emit("phase", phase="generating", task=task, index=index + 1, total=len(selected))
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=config["max_completion_length"], do_sample=False, pad_token_id=tokenizer.eos_token_id)
        completion = tokenizer.decode(output[0, inputs.input_ids.shape[1]:], skip_special_tokens=True)
        runtime.events.emit("phase", phase="grading", task=task)
        result = rollout(gym, task, completion)
        record = result.get("record") or {}
        atomic_json(report / f"episode-{index + 1:04d}.json", result)
        summary = {"task": task, "reward": result["reward"], "passed": bool(record.get("pass")), "error": result.get("execution_error") or record.get("error"), "file": f"episode-{index + 1:04d}.json"}
        episodes.append(summary)
        runtime.events.emit("episode", **summary)
        atomic_json(runtime.directory / "partial.json", {"episodes": episodes})
    artifact_id = runtime.publish(report, config["name"], "report", {"protocol": "direct-diff-evaluation.v1", "artifact_id": config["artifact_id"], "split": config["split"]})
    rewards = [item["reward"] for item in episodes if item["reward"] is not None]
    errors = sum(bool(item["error"]) for item in episodes)
    return {"execution_errors": errors, "_status": "failed" if errors else "succeeded", "_error": f"{errors} execution errors" if errors else None, "episodes": episodes, "artifact_id": artifact_id, "mean_reward": sum(rewards) / len(rewards) if rewards else None,
            "solve_rate": sum(item["passed"] for item in episodes) / len(episodes) if episodes else None}

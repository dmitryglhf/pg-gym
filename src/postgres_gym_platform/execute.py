from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import httpx2

from .runtime import Runtime, atomic_json, process_identity, resources


class Cancelled(BaseException):
    pass


class EventOutput(io.TextIOBase):
    def __init__(self, emitter):
        self.emitter = emitter
        self.pending = ""

    def write(self, value):
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.strip():
                self.emitter.line(line)
        return len(value)

    def flush(self):
        if self.pending:
            self.emitter.line(self.pending)
            self.pending = ""


def benchmark(runtime: Runtime) -> dict:
    from postgres_gym import Gym

    config = runtime.config
    connection = config["connection"]
    profile = config.get(
        "profile", {"max_turns": config["max_turns"], "timeout": config["timeout"]}
    )
    os.environ.update(
        {
            "GOOSE_PROVIDER": "pgpro",
            "GOOSE_MODEL": connection["model"],
            "PGPRO_HOST": runtime.settings["task_api_url"].rstrip("/")
            + f"/internal/provider/{runtime.id}",
            "PGPRO_API_KEY": runtime.settings["gateway_token"],
            "MARKOV_API_KEY": runtime.settings["gateway_token"],
            "POSTGRES_GYM_AGENT_TIMEOUT": str(profile["timeout"]),
            "POSTGRES_GYM_HARNESS_CONFIG": json.dumps(
                {
                    **profile,
                    "context_length": connection["context_length"],
                    "max_tokens": connection["max_tokens"],
                }
            ),
        }
    )
    from postgres_gym import settings

    settings.AGENT_MODEL = connection["model"]
    settings.PROVIDER_KEY = runtime.settings["gateway_token"]
    settings.AGENT_TIMEOUT = profile["timeout"]
    settings.CONTAINER_TIMEOUT = profile["timeout"] + 900
    gym = Gym(config["suite"])
    report = runtime.directory / "report"
    report.mkdir()
    episodes: list[dict] = []
    for index, task in enumerate(config["tasks"]):
        spec = gym.task(task)
        if spec.task_hash != config["task_hashes"][task]:
            raise ValueError("Suite changed since submission; submit a new benchmark")
        runtime.events.emit(
            "phase",
            phase="preparing",
            task=task,
            index=index + 1,
            total=len(config["tasks"]),
        )
        result = gym.run(task, "cli:" + config["harness"])
        record = result.record or {}
        relative = f"episode-{index + 1:04d}.json"
        full = {
            "suite": config["suite"],
            "task": task,
            "prompt": spec.prompt,
            "task_hash": spec.task_hash,
            "record": record,
            "execution": {
                "returncode": result.execution.returncode,
                "backend": result.execution.backend,
                "stderr": result.execution.stderr[-6000:],
            },
        }
        atomic_json(report / relative, full)
        summary = {
            "task": task,
            "suite": config["suite"],
            "reward": result.reward,
            "passed": bool(record.get("pass")),
            "seconds": record.get("seconds"),
            "error": record.get("error")
            or (result.execution.stderr[-1000:] if not result.ok else None),
            "file": relative,
        }
        episodes.append(summary)
        runtime.events.emit("episode", **summary)
        atomic_json(runtime.directory / "partial.json", {"episodes": episodes})
    artifact = runtime.publish(
        report,
        "Benchmark episodes",
        "report",
        {"protocol": config["protocol"], "suite": config["suite"]},
    )
    rewards = [
        item["reward"]
        for item in episodes
        if item["reward"] is not None and not item["error"]
    ]
    errors = sum(bool(item["error"]) for item in episodes)
    return {
        "episodes": episodes,
        "artifact_id": artifact,
        "mean_reward": sum(rewards) / len(rewards) if rewards else None,
        "solve_rate": sum(item["passed"] for item in episodes) / len(episodes),
        "scored": len(rewards),
        "execution_errors": errors,
        "_status": "failed" if errors else "succeeded",
        "_error": f"{errors} episodes had execution errors" if errors else None,
    }


def model_import(runtime: Runtime) -> dict:
    from huggingface_hub import HfApi, snapshot_download

    config = runtime.config
    private = runtime.request("GET", f"/internal/jobs/{runtime.id}/input")
    token = private.get("credential")
    runtime.events.emit("phase", phase="resolving", repository=config["repository"])
    info = HfApi(token=token).model_info(
        config["repository"], revision=config["revision"]
    )
    if not info.sha:
        raise ValueError("Hugging Face did not return a resolved revision")
    runtime.events.emit(
        "phase", phase="downloading", repository=config["repository"], revision=info.sha
    )
    directory = runtime.directory / "download"
    snapshot_download(
        config["repository"],
        revision=info.sha,
        token=token,
        local_dir=directory,
        allow_patterns=[
            "*.safetensors",
            "*.json",
            "*.model",
            "*.txt",
            "*.jinja",
            "*.tiktoken",
        ],
    )
    if not (directory / "config.json").is_file() or not list(
        directory.glob("*.safetensors")
    ):
        raise ValueError(
            "Repository must contain a model config and safetensors weights"
        )
    if not (
        (directory / "tokenizer.json").is_file()
        or (directory / "tokenizer.model").is_file()
    ):
        raise ValueError("Tokenizer files are missing from this repository")
    identifier = runtime.publish(
        directory,
        config["repository"] + "@" + info.sha[:12],
        "model",
        {"repository": config["repository"], "revision": info.sha},
    )
    return {
        "artifact_id": identifier,
        "repository": config["repository"],
        "revision": info.sha,
    }


def training(runtime: Runtime) -> dict:
    config = runtime.config
    model, metadata = runtime.materialize(config["artifact_id"])
    output = runtime.directory / "training"
    os.environ["POSTGRES_GYM_TRAIN_SUITES"] = config["suite"]
    os.environ["CUDA_VISIBLE_DEVICES"] = os.environ.get(
        "PG_GYM_CUDA_DEVICE", os.environ.get("PG_GYM_GPU", "0")
    )
    from postgres_gym import Gym

    gym = Gym(config["suite"])
    for name, expected in config["task_hashes"].items():
        if gym.task(name).task_hash != expected:
            raise ValueError("Suite changed since submission")
    tasks_file = runtime.directory / "selected-tasks.txt"
    tasks_file.write_text(
        "".join(config["suite"] + "\t" + name + "\n" for name in config["task_hashes"])
    )
    from postgres_gym.training.grpo import main

    runtime.events.emit("phase", phase="loading", model=metadata["name"])
    args = [
        "pg-gym-rl",
        "--model",
        str(model),
        "--output",
        str(output),
        "--split",
        config["split"],
        "--max-steps",
        str(config["steps"]),
        "--learning-rate",
        str(config["learning_rate"]),
        "--num-generations",
        str(config["group_size"]),
        "--batch-size",
        str(config["batch_size"]),
        "--rank",
        str(config["rank"]),
        "--num-layers",
        str(config["num_layers"]),
        "--max-completion-length",
        str(config["max_completion_length"]),
        "--max-prompt-length",
        str(config["max_prompt_length"]),
        "--beta",
        str(config["beta"]),
        "--seed",
        str(config["seed"]),
        "--tasks-file",
        str(tasks_file),
        "--save-steps",
        str(config["checkpoint_every"]),
        "--save-total-limit",
        str(config["keep_checkpoints"]),
    ]
    before = sys.argv
    try:
        sys.argv = args
        main()
    finally:
        sys.argv = before
    import shutil

    export = runtime.directory / "export"
    export.mkdir()
    for path in output.iterdir():
        if path.is_file() and path.suffix in {
            ".safetensors",
            ".json",
            ".model",
            ".jinja",
            ".txt",
        }:
            shutil.copy2(path, export / path.name)
    identifier = runtime.publish(
        export,
        config["name"] + " adapter",
        "adapter",
        {
            "base_artifact_id": config["artifact_id"],
            "base_revision": metadata["metadata"].get("revision"),
            "protocol": config["protocol"],
            "steps": config["steps"],
        },
    )
    reports = runtime.directory / "training-report"
    reports.mkdir()
    if (output / "rollouts.jsonl").is_file():
        shutil.copy2(output / "rollouts.jsonl", reports / "rollouts.jsonl")
    atomic_json(reports / "config.json", config)
    report_id = runtime.publish(
        reports, "Training rollouts", "report", {"protocol": config["protocol"]}
    )
    checkpoints = []
    for path in sorted(output.glob("checkpoint-*")):
        if path.is_dir():
            checkpoints.append(
                runtime.publish(
                    path,
                    path.name,
                    "checkpoint",
                    {
                        "base_artifact_id": config["artifact_id"],
                        "step": int(path.name.split("-")[-1]),
                    },
                )
            )
    return {
        "artifact_id": identifier,
        "report_id": report_id,
        "checkpoints": checkpoints,
        "steps": config["steps"],
    }


def chat(runtime: Runtime) -> dict:
    config = runtime.config
    outputs = {}
    for connection_id in config["connection_ids"]:
        messages = (
            [{"role": "system", "content": config["system_prompt"]}]
            if config["system_prompt"]
            else []
        )
        for turn in config["history"]:
            old = turn["outputs"].get(connection_id)
            if old and old.get("text"):
                messages += [
                    {"role": "user", "content": turn["prompt"]},
                    {"role": "assistant", "content": old["text"]},
                ]
        messages.append({"role": "user", "content": config["prompt"]})
        runtime.events.emit("phase", phase="generating", connection_id=connection_id)
        text, reasoning = "", ""
        calls: dict[int, dict] = {}
        usage = None
        complete = False
        started = time.time()
        headers = {
            "Authorization": "Bearer " + runtime.settings["gateway_token"],
            "X-PG-Connection": connection_id,
        }
        with (
            httpx2.Client(
                timeout=httpx2.Timeout(300, connect=15), trust_env=False
            ) as client,
            client.stream(
                "POST",
                runtime.settings["api_url"]
                + f"/internal/provider/{runtime.id}/v1/chat/completions",
                headers=headers,
                json={
                    "model": config["connections"][connection_id]["model"],
                    "messages": messages,
                    "temperature": config["temperature"],
                    "max_tokens": config["max_tokens"],
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            ) as response,
        ):
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    complete = True
                    break
                payload = json.loads(data)
                usage = payload.get("usage") or usage
                for choice in payload.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content") or ""
                    thought = (
                        delta.get("reasoning_content") or delta.get("reasoning") or ""
                    )
                    text += content
                    reasoning += thought
                    for call in delta.get("tool_calls", []):
                        index = call.get("index", 0)
                        target = calls.setdefault(
                            index,
                            {"id": call.get("id", ""), "name": "", "arguments": ""},
                        )
                        target["name"] += call.get("function", {}).get("name", "")
                        target["arguments"] += call.get("function", {}).get(
                            "arguments", ""
                        )
                    outputs[connection_id] = {
                        "text": text,
                        "reasoning": reasoning,
                        "tool_calls": list(calls.values()),
                        "seconds": time.time() - started,
                        "usage": usage,
                    }
                    atomic_json(
                        runtime.directory / "partial.json", {"outputs": outputs}
                    )
                    if content or thought or delta.get("tool_calls"):
                        runtime.events.emit(
                            "delta",
                            connection_id=connection_id,
                            text=content,
                            reasoning=thought,
                            tool_calls=delta.get("tool_calls", []),
                        )
        if not complete:
            raise ValueError("Provider stream ended without a completion marker")
        outputs[connection_id] = {
            "text": text,
            "reasoning": reasoning,
            "tool_calls": list(calls.values()),
            "usage": usage,
            "seconds": time.time() - started,
        }
        atomic_json(runtime.directory / "partial.json", {"outputs": outputs})
    return {"outputs": outputs}


def run(directory: Path):
    runtime = Runtime(directory)
    atomic_json(directory / "process.json", process_identity())
    os.environ.update(
        {
            "POSTGRES_GYM_EVENTS": "1",
            "PG_GYM_JOB_ID": runtime.id,
            "POSTGRES_GYM_RUNS": str(directory / "records"),
            "PYTHONUNBUFFERED": "1",
            "CUDA_VISIBLE_DEVICES": os.environ.get(
                "PG_GYM_CUDA_DEVICE", os.environ.get("PG_GYM_GPU", "0")
            ),
        }
    )

    def cancelled(_signum, _frame):
        raise Cancelled("Cancellation requested")

    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    finished = threading.Event()

    def monitor():
        while not finished.wait(5):
            runtime.events.emit("resource", **resources())

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    status, result, error = "failed", None, None
    output = EventOutput(runtime.events)
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if runtime.job["kind"] == "deployment":
                from .serving import deploy

                result = deploy(runtime)
            elif runtime.job["kind"] == "evaluation":
                from .evaluation import evaluate

                result = evaluate(runtime)
            else:
                result = {
                    "benchmark": benchmark,
                    "model_import": model_import,
                    "training": training,
                    "chat": chat,
                }[runtime.job["kind"]](runtime)
        status = result.pop("_status", "succeeded")
        error = result.pop("_error", None)
    except Cancelled:
        status = "cancelled"
        partial = directory / "partial.json"
        result = json.loads(partial.read_text()) if partial.exists() else None
    except BaseException as exc:  # noqa: BLE001 - persist failure even when a trainer exits the process
        error = f"{type(exc).__name__}: {exc}"[:1500]
        for secret in (
            runtime.settings["attempt_token"],
            runtime.settings["gateway_token"],
        ):
            error = error.replace(secret, "[redacted]")
        runtime.events.emit("log", text=error)
        partial = directory / "partial.json"
        result = json.loads(partial.read_text()) if partial.exists() else None
    finally:
        finished.set()
        thread.join(timeout=6)
        output.flush()
        runtime.client.close()
        atomic_json(
            directory / "result.json",
            {"status": status, "error": error, "result": result},
        )


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())

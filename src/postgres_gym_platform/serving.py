from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time

import httpx2

from .runtime import Runtime


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, check=False, text=True, timeout=1800
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or "Docker command failed")
    return result.stdout.strip()


def deploy(runtime: Runtime) -> dict:
    config = runtime.config
    model_path, artifact = runtime.materialize(config["artifact_id"])
    base_path = model_path
    if artifact["kind"] == "adapter":
        base_path, _ = runtime.materialize(artifact["metadata"]["base_artifact_id"])
    image = os.environ.get("PG_GYM_VLLM_IMAGE", "vllm/vllm-openai:v0.27.0")
    name, volume = "pg-gym-vllm-" + runtime.id, "pg-gym-model-" + runtime.id
    stage = name + "-stage"
    key = secrets.token_urlsafe(32)
    alias = "pg-" + config["artifact_id"]
    runtime.events.emit("phase", phase="preparing", image=image)
    docker("image", "inspect", image)
    docker("volume", "create", "--label", "pg-gym.job=" + runtime.id, volume)
    logger = None
    try:
        docker(
            "run",
            "-d",
            "--name",
            stage,
            "--label",
            "pg-gym.job=" + runtime.id,
            "--mount",
            f"type=volume,source={volume},target=/models",
            "--entrypoint",
            "sleep",
            image,
            "3600",
        )
        docker("exec", stage, "mkdir", "-p", "/models/base", "/models/adapter")
        docker("cp", str(base_path) + "/.", stage + ":/models/base")
        if artifact["kind"] == "adapter":
            docker("cp", str(model_path) + "/.", stage + ":/models/adapter")
        docker("rm", "-f", stage)
        command = [
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "pg-gym.job=" + runtime.id,
            "--gpus",
            "device=" + os.environ.get("PG_GYM_GPU", "0"),
            "--shm-size",
            "2g",
            "--mount",
            f"type=volume,source={volume},target=/models,readonly",
            "--env",
            "VLLM_API_KEY=" + key,
            "--env",
            "HF_HUB_OFFLINE=1",
        ]
        network = os.environ.get("PG_GYM_SERVING_NETWORK")
        if network:
            command += ["--network", network]
        else:
            command += [
                "-p",
                os.environ.get("PG_GYM_SERVING_BIND", "127.0.0.1") + "::8000",
            ]
        command += [
            image,
            "--model",
            "/models/base",
            "--served-model-name",
            "base" if artifact["kind"] == "adapter" else alias,
            "--max-model-len",
            str(config["max_model_len"]),
            "--gpu-memory-utilization",
            str(config["gpu_memory_utilization"]),
        ]
        if artifact["kind"] == "adapter":
            rank = int(
                json.loads((model_path / "adapter_config.json").read_text())["r"]
            )
            maximum_rank = next(
                (
                    limit
                    for limit in (8, 16, 32, 64, 128, 256, 320, 512)
                    if limit >= rank
                ),
                None,
            )
            if maximum_rank is None:
                raise ValueError("Adapter rank exceeds vLLM serving limits")
            command += [
                "--enable-lora",
                "--max-lora-rank",
                str(maximum_rank),
                "--lora-modules",
                alias + "=/models/adapter",
            ]
        if config["tool_parser"]:
            command += [
                "--enable-auto-tool-choice",
                "--tool-call-parser",
                config["tool_parser"],
            ]
        docker(*command)
        if network:
            base_url = f"http://{name}:8000/v1"
        else:
            info = json.loads(docker("inspect", name))[0]
            port = info["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"]
            base_url = (
                f"http://{os.environ.get('PG_GYM_SERVING_HOST', '127.0.0.1')}:{port}/v1"
            )
        logger = subprocess.Popen(
            ["docker", "logs", "-f", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def logs():
            assert logger is not None and logger.stdout is not None
            for line in logger.stdout:
                runtime.events.emit("log", text=line[-4000:].replace(key, "[redacted]"))

        threading.Thread(target=logs, daemon=True).start()
        runtime.events.emit("phase", phase="loading")
        deadline = time.monotonic() + 1800
        with httpx2.Client(timeout=10, trust_env=False) as client:
            while time.monotonic() < deadline:
                if docker("inspect", "--format", "{{.State.Running}}", name) != "true":
                    raise RuntimeError(
                        "vLLM exited while loading. Inspect the startup logs."
                    )
                try:
                    ready = client.get(
                        base_url + "/models", headers={"Authorization": "Bearer " + key}
                    )
                    if ready.status_code == 200 and alias in [
                        m.get("id") for m in ready.json().get("data", [])
                    ]:
                        break
                except httpx2.HTTPError:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("vLLM did not become ready within 30 minutes")
        connected = runtime.request(
            "POST",
            f"/internal/jobs/{runtime.id}/deployment",
            json={
                "name": config["name"],
                "base_url": base_url,
                "model": alias,
                "api_key": key,
                "context_length": config["max_model_len"],
                "max_tokens": min(2048, config["max_model_len"] // 2),
                "tools": bool(config["tool_parser"]),
            },
        )
        runtime.events.emit("phase", phase="ready", connection_id=connected["id"])
        while docker("inspect", "--format", "{{.State.Running}}", name) == "true":
            time.sleep(5)
        raise RuntimeError("vLLM server stopped unexpectedly")
    finally:
        if logger:
            logger.terminate()
            logger.wait(timeout=10)
        for container in (stage, name):
            subprocess.run(
                ["docker", "rm", "-f", container],
                capture_output=True,
                check=False,
                timeout=30,
            )
        subprocess.run(
            ["docker", "volume", "rm", volume],
            capture_output=True,
            check=False,
            timeout=30,
        )

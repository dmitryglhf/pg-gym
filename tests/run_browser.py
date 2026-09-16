"""Launch an isolated API, CPU worker, web and provider fixture for browser checks."""

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_cli(python, env, directory):
    env = {
        **env,
        "PG_GYM_CONFIG_DIR": directory + "/cli",
        "PG_GYM_URL": "",
        "PG_GYM_TOKEN": "",
    }

    def command(*args, stdin=None):
        result = subprocess.run(
            [python, "-m", "postgres_gym_platform.cli", *args, "--output", "json"],
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    command("context", "add", "fixture", "--url", "http://localhost:18800")
    command(
        "auth",
        "register",
        "--username",
        "cli-test",
        "--password-stdin",
        "--invitation-stdin",
        stdin="cli-testing-password\n\n",
    )
    command(
        "auth",
        "login",
        "--username",
        "cli-test",
        "--password-stdin",
        stdin="cli-testing-password\n",
    )
    catalog = command("suites", "list")
    assert sum(s["tasks"] for s in catalog) == 189
    config = Path(directory) / "connection.json"
    config.write_text(
        json.dumps(
            {
                "name": "CLI provider",
                "model": "fixture-model",
                "base_url": "http://127.0.0.1:18802/v1",
                "tools": True,
            }
        )
    )
    connection = command("connections", "create", "--config", str(config))
    response = command(
        "inference",
        "chat",
        "--connection",
        connection["id"],
        "--prompt",
        "Hello from the CLI",
        "--timeout",
        "30",
    )
    assert (
        response["job"]["result"]["outputs"][connection["id"]]["text"]
        == "Response from the test provider."
    )
    job = command(
        "benchmark",
        "run",
        "--suite",
        "sql-function-set",
        "--task",
        "area",
        "--connection",
        connection["id"],
    )
    assert command("jobs", "cancel", job["id"])["status"] == "cancelled"
    command("auth", "logout")
    print(
        "CLI: registration, token login, catalog, connection, streamed chat and benchmark cancellation passed.",
        flush=True,
    )


def main():
    output = Path(os.environ.get("PG_GYM_QA_OUTPUT", "/tmp/pg-gym-qa")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pg-gym-browser-") as directory:
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PG_GYM_DATA": directory + "/data",
            "PG_GYM_SECRET_DIR": directory + "/secrets",
            "PG_GYM_OPEN_REGISTRATION": "1",
            "PG_GYM_WORKER_TOKEN": "test-worker-token",
            "PG_GYM_ORIGIN": "http://localhost:18800",
            "PG_GYM_API_URL": "http://127.0.0.1:18801",
            "PG_GYM_WORKER_DATA": directory + "/worker",
            "PG_GYM_WORKER_ID": "browser-worker",
            "POSTGRES_GYM_TASK_IMAGE": "pg-gym-browser-no-task-image",
            "PG_GYM_QA_OUTPUT": str(output),
        }
        python = str(ROOT / ".venv/bin/python")
        processes, logs = [], []

        def start(name, cmd, cwd=ROOT):
            log = (output / (name + ".log")).open("w")
            logs.append(log)
            p = subprocess.Popen(
                cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            processes.append(p)

        try:
            start("provider", [python, "tests/fixtures/openai_provider.py", "18802"])
            start(
                "api",
                [
                    python,
                    "-m",
                    "postgres_gym_platform.cli",
                    "server",
                    "api",
                    "--port",
                    "18801",
                ],
            )
            start(
                "web",
                [
                    os.environ.get("DENO_BIN", "deno"),
                    "serve",
                    "-A",
                    "--port=18800",
                    "_fresh/server.js",
                ],
                ROOT / "web",
            )
            start(
                "worker",
                [python, "-m", "postgres_gym_platform.cli", "server", "worker"],
            )
            for _ in range(60):
                try:
                    with urllib.request.urlopen(
                        "http://localhost:18800/api/v1/health", timeout=1
                    ) as r:
                        if r.status == 200:
                            break
                except (OSError, ValueError):
                    time.sleep(0.5)
            result = subprocess.run(
                ["node", "tests/browser.mjs"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=170,
                check=False,
            )
            (output / "browser-result.txt").write_text(result.stdout + result.stderr)
            print(result.stdout + result.stderr)
            if result.returncode == 0:
                check_cli(python, env, directory)
            return result.returncode
        finally:
            diagnostics = []
            for job_dir in Path(directory).glob("worker/jobs/*"):
                for name in (
                    "process.log",
                    "result.json",
                    "process.json",
                    "events.jsonl",
                ):
                    source = job_dir / name
                    if source.exists():
                        diagnostics.append(
                            job_dir.name
                            + "/"
                            + name
                            + "\n"
                            + source.read_text()[-12000:]
                        )
            (output / "execution-diagnostics.txt").write_text("\n".join(diagnostics))
            for p in processes:
                p.terminate()
            for p in processes:
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    raise SystemExit(main())

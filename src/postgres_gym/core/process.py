from __future__ import annotations

import os
import resource
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from postgres_gym.core.activity import emit


@dataclass
class Step:
    ok: bool
    seconds: float
    output: str = ""


@dataclass
class Captured:
    returncode: int
    seconds: float
    output: str
    timed_out: bool = False


MAX_FILE_BYTES = 512 * 1024 * 1024


def limit_file_size() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))


def capture(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    devnull_stdin: bool = False,
) -> Captured:
    started = time.time()
    stdin = (
        subprocess.PIPE
        if input_text is not None
        else (subprocess.DEVNULL if devnull_stdin else None)
    )
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=stdin,
        text=True,
        errors="replace",
        env=env,
        preexec_fn=limit_file_size,  # noqa: PLW1509
        start_new_session=True,
    )
    if os.environ.get("POSTGRES_GYM_EVENTS") == "1":
        return stream_capture(proc, input_text, timeout, started)
    try:
        output, _ = proc.communicate(input=input_text, timeout=timeout)
        return Captured(proc.returncode, time.time() - started, output or "")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        output, _ = proc.communicate()
        return Captured(-1, time.time() - started, output or "", True)


def stream_capture(proc, input_text: str | None, timeout: int, started: float) -> Captured:
    output: list[str] = []
    def drain():
        for line in iter(proc.stdout.readline, ""):
            output.append(line)
            emit("log", text=line[-4000:])
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        if input_text is not None:
            proc.stdin.write(input_text)
            proc.stdin.close()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    finally:
        reader.join(timeout=10)
    return Captured(proc.returncode, time.time() - started, "".join(output), timed_out)


def run(cmd: list[str], cwd: Path, timeout: int) -> Step:
    result = capture(cmd, cwd, timeout)
    tail = result.output[-40000:]
    if result.timed_out:
        tail = f"TIMEOUT after {timeout}s\n{tail[-20000:]}"
    return Step(result.returncode == 0 and not result.timed_out, result.seconds, tail)

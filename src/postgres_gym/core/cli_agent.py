from __future__ import annotations

import os
import shlex
import subprocess
import time

from postgres_gym import settings
from postgres_gym.core import process
from postgres_gym.core.agents import Agent

PROFILES: dict[str, dict] = {
    "markov": {
        "cmd": "markov run --no-session -t {prompt}",
        "stdin": False,
    },
    "opencode": {
        "cmd": "opencode run --pure --auto --model {provider}/{model} {prompt}",
        "stdin": False,
        "devnull_stdin": True,
    },
    "claude": {
        "cmd": "claude -p {prompt} --permission-mode acceptEdits",
        "stdin": False,
    },
    "codex": {
        "cmd": "codex exec {prompt}",
        "stdin": False,
    },
    "aider": {
        "cmd": "aider --yes --no-auto-commits --message {prompt}",
        "stdin": False,
    },
}

_SCRUBBED = frozenset({settings.JUDGE_KEY_ENV, "OPENROUTER_API_KEY"})


def agent_version(binary: str) -> str:
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown ({type(exc).__name__})"
    output = (result.stdout + result.stderr).strip().splitlines()
    return output[0] if output else "unknown"


class CliAgent(Agent):
    def __init__(
        self,
        profile: str = "markov",
        level: str = "L0",
        timeout: int | None = None,
        extra_env: dict | None = None,
    ):
        if profile not in PROFILES:
            raise KeyError(
                f"unknown agent profile {profile!r}; known: {sorted(PROFILES)}"
            )
        self.profile = profile
        self.level = level
        self.timeout = timeout or settings.AGENT_TIMEOUT
        self.extra_env = extra_env or {}
        self.name = f"cli:{profile}"

    def run(self, task: dict, oracle: dict, *, suite, stand) -> dict:
        prompt = suite.prompt(task, oracle)
        spec = PROFILES[self.profile]
        argv = [self._expand(part, prompt) for part in shlex.split(spec["cmd"])]
        env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED}
        env.update(self.extra_env)
        version = agent_version(argv[0])
        started = time.time()
        try:
            result = process.capture(
                argv,
                settings.PG_SRC,
                self.timeout,
                env=env,
                input_text=prompt if spec.get("stdin") else None,
                devnull_stdin=bool(spec.get("devnull_stdin")),
            )
        except FileNotFoundError:
            return {"error": f"{argv[0]} not on PATH", "profile": self.profile}

        return {
            "profile": self.profile,
            "level": self.level,
            "provider": settings.AGENT_PROVIDER,
            "model": settings.AGENT_MODEL,
            "agent_version": version,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "seconds": round(time.time() - started, 1),
            "prompt_chars": len(prompt),
            "tail": result.output[-6000:],
        }

    @staticmethod
    def _expand(part: str, prompt: str) -> str:
        if part == "{prompt}":
            return prompt
        return part.replace("{provider}", settings.AGENT_PROVIDER).replace(
            "{model}", settings.AGENT_MODEL
        )

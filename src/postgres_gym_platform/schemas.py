from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=12, max_length=256)


class Register(Login):
    invitation: SecretStr = SecretStr("")


class Connection(Input):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=200, pattern=r"^[^\s]+$")
    api_key: SecretStr | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    context_length: int = Field(default=32768, ge=1024, le=2097152)
    max_tokens: int = Field(default=4096, ge=16, le=131072)
    tools: bool = False


class Credential(Input):
    name: str = Field(min_length=1, max_length=80)
    value: SecretStr = Field(min_length=1, max_length=8192)


class Harness(Input):
    name: str = Field(min_length=1, max_length=80)
    harness: Literal["markov", "opencode"] = "markov"
    max_turns: int = Field(default=50, ge=1, le=1000)
    timeout: int = Field(default=1800, ge=30, le=86400)
    temperature: float = Field(default=0, ge=0, le=1)
    context_strategy: Literal["summarize", "truncate"] = "summarize"


class Benchmark(Input):
    name: str = Field(default="Benchmark", min_length=1, max_length=100)
    suite: str = Field(min_length=1, max_length=120)
    tasks: list[str] = Field(default_factory=list, max_length=1000)
    split: str | None = Field(default=None, max_length=100)
    harness: Literal["markov", "opencode"] = "markov"
    connection_id: str
    profile_id: str | None = None
    timeout: int = Field(default=1800, ge=30, le=86400)
    max_turns: int = Field(default=50, ge=1, le=1000)


class ModelImport(Input):
    name: str = Field(default="Model download", min_length=1, max_length=100)
    repository: str = Field(pattern=r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
    revision: str = Field(default="main", min_length=1, max_length=200)
    credential_id: str | None = None
    credential_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class Training(Input):
    name: str = Field(default="GRPO training", min_length=1, max_length=100)
    artifact_id: str
    suite: str = Field(min_length=1, max_length=120)
    split: str = Field(default="train", min_length=1, max_length=100)
    steps: int = Field(default=20, ge=1, le=100000)
    learning_rate: float = Field(default=1e-5, gt=0, le=0.01)
    group_size: int = Field(default=2, ge=2, le=64)
    batch_size: int = Field(default=1, ge=1, le=64)
    rank: int = Field(default=8, ge=1, le=256)
    num_layers: int = Field(default=16, ge=1, le=256)
    max_completion_length: int = Field(default=2048, ge=32, le=32768)
    max_prompt_length: int = Field(default=4096, ge=128, le=131072)
    beta: float = Field(default=0.001, ge=0, le=1)
    checkpoint_every: int = Field(default=10, ge=1, le=10000)
    keep_checkpoints: int = Field(default=3, ge=1, le=20)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def batch_divides_group(self):
        if self.group_size % self.batch_size:
            raise ValueError("Group size must be divisible by batch size")
        return self


class Deployment(Input):
    name: str = Field(default="Inference", min_length=1, max_length=80)
    artifact_id: str
    max_model_len: int = Field(default=4096, ge=512, le=131072)
    gpu_memory_utilization: float = Field(default=0.85, ge=0.1, le=0.95)
    tool_parser: Literal["", "hermes", "llama3_json", "mistral", "qwen3_xml"] = ""


class Evaluation(Input):
    name: str = Field(default="Model evaluation", min_length=1, max_length=100)
    artifact_id: str
    suite: str = Field(min_length=1, max_length=120)
    split: str = Field(default="test", min_length=1, max_length=100)
    max_completion_length: int = Field(default=2048, ge=32, le=32768)
    seed: int = Field(default=42, ge=0, le=2147483647)


class Conversation(Input):
    name: str = Field(default="New chat", min_length=1, max_length=100)
    connection_ids: list[str] = Field(min_length=1, max_length=2)
    system_prompt: str = Field(default="", max_length=20000)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=32768)


class Turn(Input):
    prompt: str = Field(min_length=1, max_length=100000)


class TokenRequest(Input):
    name: str = Field(default="CLI", min_length=1, max_length=80)
    days: int = Field(default=30, ge=1, le=365)

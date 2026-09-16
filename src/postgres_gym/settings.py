from __future__ import annotations

import os
from pathlib import Path
from typing import overload


@overload
def _env(name: str) -> str | None: ...


@overload
def _env(name: str, default: str) -> str: ...


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _default_root() -> Path:
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "suites").is_dir():
        return checkout
    import postgres_gym_data
    return Path(postgres_gym_data.__file__).parent


ROOT = Path(_env("POSTGRES_GYM_ROOT", str(_default_root())))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(ROOT / ".env")

STAND_DIR = Path(_env("POSTGRES_GYM_STAND", str(ROOT / "stand")))
PG_SRC = Path(_env("POSTGRES_GYM_SRC", str(STAND_DIR / "pg")))
PG_PREFIX = Path(_env("POSTGRES_GYM_PREFIX", str(STAND_DIR / "pg-install")))
PG_GIT_DIR = Path(_env("POSTGRES_GYM_GIT_DIR", str(STAND_DIR / "pg.git")))
PG_MIRROR = _env(
    "POSTGRES_GYM_PG_MIRROR", "https://git.postgresql.org/git/postgresql.git"
)

DISPOSABLE_GIT = _env("POSTGRES_GYM_DISPOSABLE_GIT", "0") == "1"
PAYLOAD_STDIN = _env("POSTGRES_GYM_PAYLOAD_STDIN", "0") == "1"

SUITE_ID = _env("POSTGRES_GYM_SUITE", "sql-function-set") or "sql-function-set"
RUNS_ROOT = Path(_env("POSTGRES_GYM_RUNS", str(ROOT / "local" / "runs")))

DATA_DIR: Path
TASKS_DIR: Path
ORACLE_DIR: Path
PREP_DIR: Path
RUNS_DIR: Path


def use_suite(suite_id: str | None = None) -> str:
    global SUITE_ID, DATA_DIR, TASKS_DIR, ORACLE_DIR, PREP_DIR, RUNS_DIR
    SUITE_ID = suite_id or SUITE_ID
    DATA_DIR = ROOT / "suites" / SUITE_ID / "data"
    TASKS_DIR = DATA_DIR / "tasks"
    ORACLE_DIR = DATA_DIR / "oracle"
    PREP_DIR = DATA_DIR / "prep"
    RUNS_DIR = RUNS_ROOT / SUITE_ID
    return SUITE_ID


use_suite()

JUDGE_BASE_URL = _env("POSTGRES_GYM_JUDGE_BASE_URL", "https://openrouter.ai/api/v1")
JUDGE_MODEL = _env("POSTGRES_GYM_JUDGE_MODEL", "z-ai/glm-5.3")
JUDGE_KEY_ENV = (
    _env("POSTGRES_GYM_JUDGE_KEY_ENV", "OPENROUTER_API_KEY") or "OPENROUTER_API_KEY"
)
JUDGE_TIMEOUT = int(_env("POSTGRES_GYM_JUDGE_TIMEOUT", "180") or "180")
JUDGE_MAX_TOKENS = int(_env("POSTGRES_GYM_JUDGE_MAX_TOKENS", "32000") or "32000")
JUDGE_REASONING_TOKENS = int(
    _env("POSTGRES_GYM_JUDGE_REASONING_TOKENS", "24000") or "24000"
)

LANGFUSE_PUBLIC_KEY = (
    os.environ.get("LANGFUSE_PUBLIC_KEY")
    or os.environ.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
    or ""
)
LANGFUSE_SECRET_KEY = (
    os.environ.get("LANGFUSE_SECRET_KEY")
    or os.environ.get("LANGFUSE_INIT_PROJECT_SECRET_KEY")
    or ""
)
LANGFUSE_URL = (
    os.environ.get("LANGFUSE_URL")
    or os.environ.get("LANGFUSE_BASE_URL")
    or os.environ.get("LANGFUSE_HOST")
    or "http://localhost:3000"
)
REQUIRE_LANGFUSE = _env("POSTGRES_GYM_REQUIRE_LANGFUSE", "0") == "1"

AGENT_TIMEOUT = int(_env("POSTGRES_GYM_AGENT_TIMEOUT", "1800") or "1800")
AGENT_PROVIDER = os.environ.get("GOOSE_PROVIDER", "pgpro")
AGENT_MODEL = os.environ.get("GOOSE_MODEL", "Qwen/Qwen3.8-27B-FP8")
OPENCODE_DATA = (
    Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    / "opencode"
)

REQUIRE_MARKOV_KEY = _env("POSTGRES_GYM_REQUIRE_MARKOV_KEY", "1") == "1"
MARKOV_KEY_ENV = (
    _env("POSTGRES_GYM_MARKOV_KEY_ENV", "MARKOV_API_KEY") or "MARKOV_API_KEY"
)
PROVIDER_KEY = os.environ.get(MARKOV_KEY_ENV) or os.environ.get("PGPRO_API_KEY", "")

EXECUTION_BACKEND = _env("POSTGRES_GYM_BACKEND", "docker") or "docker"
TASK_IMAGE = (
    _env("POSTGRES_GYM_TASK_IMAGE", "postgres-gym-task:17.11")
    or "postgres-gym-task:17.11"
)
DOCKER_CONTEXT = _env("POSTGRES_GYM_DOCKER_CONTEXT", "") or ""
DOCKER_NETWORK = (
    _env("POSTGRES_GYM_DOCKER_NETWORK", "langfuse_default" if REQUIRE_LANGFUSE else "")
    or ""
)
CONTAINER_TIMEOUT = int(
    _env("POSTGRES_GYM_CONTAINER_TIMEOUT", str(AGENT_TIMEOUT + 900))
    or str(AGENT_TIMEOUT + 900)
)

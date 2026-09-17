from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 9432
DEFAULT_API_PORT = 9433
DEFAULT_ORIGIN = f"http://localhost:{DEFAULT_PORT}"
DEFAULT_API_URL = f"http://127.0.0.1:{DEFAULT_API_PORT}"


def project_root() -> Path:
    if value := os.environ.get("POSTGRES_GYM_ROOT"):
        return Path(value).resolve()
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "suites").is_dir():
        return checkout
    import postgres_gym_data

    return Path(postgres_gym_data.__file__).parent


@dataclass(frozen=True)
class Config:
    data: Path
    secret_dir: Path
    root: Path
    origin: str = DEFAULT_ORIGIN
    secure_cookie: bool = False
    registration_token: str = ""
    open_registration: bool = False
    worker_token: str = ""
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "host.docker.internal")
    session_seconds: int = 86400 * 7
    max_jobs_per_user: int = 20

    @classmethod
    def from_env(cls) -> Config:
        data = (
            Path(os.environ.get("PG_GYM_DATA", "~/.local/share/pg-gym/platform"))
            .expanduser()
            .resolve()
        )
        secret_dir = Path(
            os.environ.get("PG_GYM_SECRET_DIR", str(data / "secrets"))
        ).expanduser()

        def secret(name: str, filename: str) -> str:
            value = os.environ.get(name, "")
            path = secret_dir / filename
            return value or (path.read_text().strip() if path.is_file() else "")

        return cls(
            data=data,
            secret_dir=secret_dir,
            root=project_root(),
            origin=os.environ.get("PG_GYM_ORIGIN", DEFAULT_ORIGIN).rstrip("/"),
            secure_cookie=os.environ.get("PG_GYM_SECURE_COOKIE", "0") == "1",
            registration_token=secret(
                "PG_GYM_REGISTRATION_TOKEN", "registration-token"
            ),
            open_registration=os.environ.get("PG_GYM_OPEN_REGISTRATION", "0") == "1",
            worker_token=secret("PG_GYM_WORKER_TOKEN", "worker-token"),
            allowed_hosts=tuple(
                x.strip()
                for x in os.environ.get(
                    "PG_GYM_ALLOWED_HOSTS", "localhost,127.0.0.1,host.docker.internal"
                ).split(",")
                if x.strip()
            ),
        )

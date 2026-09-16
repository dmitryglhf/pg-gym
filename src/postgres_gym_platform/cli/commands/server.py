from pathlib import Path
from typing import Annotated

import typer

_DEFAULT_SOURCE = Path(".")
_DEFAULT_WORKER_DIR = Path("~/.local/share/pg-gym/worker").expanduser()
_DEFAULT_WORKER_URL = "http://127.0.0.1:8001"
_DEFAULT_WORKER_ID = "local"
app = typer.Typer()


@app.command("api")
def server_api(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8001,
) -> None:
    import uvicorn

    uvicorn.run(
        "postgres_gym_platform.api:create_app",
        factory=True,
        host=host,
        port=port,
        workers=1,
        log_level="info",
        proxy_headers=False,
    )


@app.command("worker")
def server_worker(
    url: Annotated[
        str, typer.Option("--url", envvar="PG_GYM_API_URL")
    ] = _DEFAULT_WORKER_URL,
    directory: Annotated[
        Path, typer.Option("--directory", envvar="PG_GYM_WORKER_DATA")
    ] = _DEFAULT_WORKER_DIR,
    identifier: Annotated[
        str, typer.Option("--id", envvar="PG_GYM_WORKER_ID")
    ] = _DEFAULT_WORKER_ID,
) -> None:
    from ...config import Config
    from ...worker import run_worker

    cfg = Config.from_env()
    run_worker(url, cfg.worker_token, directory.expanduser().resolve(), identifier)

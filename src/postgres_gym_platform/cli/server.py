from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..config import DEFAULT_API_PORT, DEFAULT_API_URL

app = typer.Typer(help="Run the API server and the job worker in the foreground.")
WORKER_DIR = Path("~/.local/share/pg-gym/worker")


@app.command("api")
def api(
    host: Annotated[str, typer.Option("--host", help="Bind address.")] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", envvar="PG_GYM_API_PORT", help="Listening port.")
    ] = DEFAULT_API_PORT,
) -> None:
    """Serve the REST API with uvicorn."""
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
def worker(
    url: Annotated[
        str,
        typer.Option(
            "--url", envvar="PG_GYM_API_URL", help="API address to claim jobs from."
        ),
    ] = DEFAULT_API_URL,
    directory: Annotated[
        Path,
        typer.Option(
            "--directory", envvar="PG_GYM_WORKER_DATA", help="Worker state directory."
        ),
    ] = WORKER_DIR,
    identifier: Annotated[
        str,
        typer.Option(
            "--id", envvar="PG_GYM_WORKER_ID", help="Worker name shown in the UI."
        ),
    ] = "local",
) -> None:
    """Run a job worker that executes claimed jobs on this host."""
    from ..config import Config
    from ..worker import run_worker

    cfg = Config.from_env()
    run_worker(url, cfg.worker_token, directory.expanduser().resolve(), identifier)

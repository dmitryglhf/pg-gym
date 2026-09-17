from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Self

import httpx2

PREFIX = "/episodes/"
COMPLETIONS = "v1/chat/completions"
DEFAULT_UPSTREAM = "http://10.7.5.88:4000"
CONTAINER_HOST = "host.docker.internal"
SKIPPED_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
)


def default_upstream() -> str:
    """The gateway markov talks to, as pgpro resolves it: host without `/v1`."""
    if host := os.environ.get("PGPRO_HOST"):
        return host.rstrip("/")
    if base := os.environ.get("MARKOV_BASE_URL"):
        return base.rstrip("/").removesuffix("/v1")
    return DEFAULT_UPSTREAM


@dataclass
class Turns:
    """What the recorder knows about one episode so far."""

    calls: int = 0
    prompt_tokens: int = 0
    max_prompt_tokens: int = 0
    errors: int = 0
    exhausted: bool = False


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes
    content_type: str = "application/json"


class Recorder:
    """A recording proxy between markov's pgpro provider and the gateway.

    Every chat completion of an episode is appended verbatim to
    `<directory>/<episode>.jsonl`, one line per model call: the request as sent,
    the response as received, its usage and how long it took. When `budget` is
    set, a call whose previous response already exceeded it in prompt tokens is
    refused instead of forwarded, which ends the turn inside markov.
    """

    def __init__(
        self,
        directory: Path,
        upstream: str | None = None,
        *,
        budget: int | None = None,
        host: str = "0.0.0.0",
        port: int = 0,
        timeout: float = 1200.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.upstream = (upstream or default_upstream()).rstrip("/")
        self.budget = budget
        self.host = host
        self.port = port
        self._client = httpx2.Client(
            timeout=httpx2.Timeout(timeout, connect=30.0),
            trust_env=False,
            transport=transport,
        )
        self._turns: dict[str, Turns] = {}
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> Self:
        if self._server is not None:
            return self
        self.directory.mkdir(parents=True, exist_ok=True)
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *_: object) -> None:
                pass

            def do_GET(self) -> None:
                self._serve(b"")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                self._serve(self.rfile.read(length) if length else b"")

            def _serve(self, body: bytes) -> None:
                episode, rest = split_path(self.path)
                if episode is None:
                    reply = Reply(404, b'{"error":"unknown episode"}')
                else:
                    reply = recorder.handle(
                        self.command, episode, rest, dict(self.headers.items()), body
                    )
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.content_type)
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="pg-gym-recorder", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._client.close()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    def url(self, episode: str, host: str = CONTAINER_HOST) -> str:
        """What the container should use as PGPRO_HOST for this episode."""
        return f"http://{host}:{self.port}{PREFIX}{episode}"

    def path(self, episode: str) -> Path:
        return self.directory / f"{episode}.jsonl"

    def turns(self, episode: str) -> Turns:
        with self._lock:
            return Turns(**asdict(self._turns.get(episode, Turns())))

    def handle(
        self, method: str, episode: str, rest: str, headers: dict[str, str], body: bytes
    ) -> Reply:
        if method != "POST" or rest != COMPLETIONS:
            return self._forward(method, rest, headers, body)
        with self._lock:
            turns = self._turns.setdefault(episode, Turns())
            turn = turns.calls + turns.errors
            refused = self._refusal(turns)
            if refused:
                if not turns.exhausted:
                    turns.exhausted = True
                    turns.errors += 1
                    self._append(episode, turn, body, None, 0.0, refused)
                return Reply(400, json.dumps({"error": refused}).encode())
        started = time.monotonic()
        reply = self._forward(method, rest, headers, body)
        seconds = time.monotonic() - started
        response = _json_or_none(reply.body)
        error = None
        if reply.status != 200 or not isinstance(response, dict):
            error = {
                "kind": "provider",
                "status": reply.status,
                "message": reply.body.decode("utf-8", "replace")[:2000],
            }
        with self._lock:
            turns = self._turns.setdefault(episode, Turns())
            turn = turns.calls + turns.errors
            if error:
                turns.errors += 1
            else:
                turns.calls += 1
                usage = (response or {}).get("usage") or {}
                turns.prompt_tokens = int(usage.get("prompt_tokens") or 0)
                turns.max_prompt_tokens = max(
                    turns.max_prompt_tokens, turns.prompt_tokens
                )
            self._append(
                episode, turn, body, response if not error else None, seconds, error
            )
        return reply

    def _refusal(self, turns: Turns) -> dict | None:
        if self.budget is None or turns.prompt_tokens <= self.budget:
            return None
        # Worded so markov files it as a plain failed request, not as a context
        # overflow it would try to compact its way out of.
        return {
            "kind": "budget",
            "type": "token_budget",
            "message": (
                f"pg-gym ends the episode: the last call carried "
                f"{turns.prompt_tokens} tokens, the ceiling is {self.budget}"
            ),
        }

    def _forward(
        self, method: str, rest: str, headers: dict[str, str], body: bytes
    ) -> Reply:
        outgoing = {
            k: v for k, v in headers.items() if k.lower() not in SKIPPED_HEADERS
        }
        try:
            response = self._client.request(
                method, f"{self.upstream}/{rest}", headers=outgoing, content=body
            )
        except httpx2.HTTPError as exc:
            message = json.dumps({"error": {"kind": "transport", "message": str(exc)}})
            return Reply(502, message.encode())
        return Reply(
            response.status_code,
            response.content,
            response.headers.get("content-type", "application/json"),
        )

    def _append(
        self,
        episode: str,
        turn: int,
        request: bytes,
        response: dict | None,
        seconds: float,
        error: dict | None,
    ) -> None:
        line = {
            "turn": turn,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "seconds": round(seconds, 3),
            "request": _json_or_none(request),
            "response": response,
            "usage": (response or {}).get("usage"),
            "error": error,
        }
        with self.path(episode).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def split_path(path: str) -> tuple[str | None, str]:
    """`/episodes/<id>/v1/chat/completions` -> (`<id>`, `v1/chat/completions`)."""
    path = path.split("?", 1)[0]
    if not path.startswith(PREFIX):
        return None, ""
    episode, _, rest = path[len(PREFIX) :].partition("/")
    return (episode or None), rest


def read(path: Path) -> list[dict]:
    """The journal lines of one episode, in order."""
    lines = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                lines.append(json.loads(raw))
    return lines


def _json_or_none(data: bytes) -> dict | None:
    try:
        value = json.loads(data)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None

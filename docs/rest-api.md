# REST API

Everything the web application and the CLI do goes through `/api/v1` on the web origin. The frontend proxies that prefix to the Python API, so one address serves both. A running instance publishes its schema at `/api/v1/openapi.json` and interactive documentation at `/api/v1/docs`.

## Authentication

The browser logs in with `POST /auth/login` and gets an HTTP-only session cookie plus a CSRF cookie. Mutating cookie requests must carry the configured Origin and an `X-CSRF-Token` header.

Automation uses bearer tokens. `POST /auth/token` trades a username and password for one, and `POST /api-tokens` creates a named token with an expiry. Bearer requests skip CSRF.

```sh
curl -fsS "$PG_GYM_URL/api/v1/me" -H "Authorization: Bearer $PG_GYM_TOKEN"
```

Every owned resource answers 404 to other accounts. Stored keys are never returned, and validation errors do not echo what was submitted.

## Resources

| Method and path | Purpose |
| --- | --- |
| `GET /health`, `GET /capabilities` | Health and what the workers can do |
| `GET /suites`, `GET /suites/{suite}/tasks`, `GET /suites/{suite}/tasks/{task}` | The catalog |
| `GET/POST /connections`, `PUT/DELETE /connections/{id}`, `POST /connections/{id}/check` | Model endpoints |
| `GET/POST /harness-profiles`, `PUT/DELETE /harness-profiles/{id}` | Harness settings |
| `GET/POST /secrets`, `PUT/DELETE /secrets/{id}` | Hugging Face credentials, write-only |
| `GET/PUT /environment`, `POST /environment/reveal` | Account variables |
| `POST /benchmarks` | Launch a benchmark |
| `POST /models/imports` | Import a model |
| `POST /training-runs`, `POST /evaluations` | Train or evaluate |
| `POST /deployments`, `POST /deployments/{id}/stop` | vLLM |
| `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retries` | Jobs |
| `GET /jobs/{id}/events` | Events, paged or as SSE |
| `GET /artifacts`, `GET /artifacts/{id}`, `GET /artifacts/{id}/files/{path}` | Artifacts and downloads |
| `GET/POST /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/turns` | Chat |

## Submitting a job

Every POST that creates a job needs an `Idempotency-Key`. The server records the key with the submission before it answers, so after a lost response you send the same request again and get the same job back. The same key with a different body is a 409. The answer is 202 with the job, and the work happens on a worker.

```sh
curl -fsS "$PG_GYM_URL/api/v1/benchmarks" \
  -H "Authorization: Bearer $PG_GYM_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ci-build-123-area' \
  -d '{"suite":"sql-function-set","tasks":["area"],"harness":"opencode","connection_id":"CONNECTION_ID"}'
```

The connection's model and protocol are captured at submission. Its credentials are looked up when the job runs, so a rotated key does not need a new job.

## Jobs and events

`GET /jobs?limit=50&before=CURSOR` returns `items` and an opaque `next` cursor to pass back unchanged. `kind` filters by job type. A job is in one of `queued`, `preparing`, `running`, `cancelling`, `succeeded`, `failed` or `cancelled`.

`GET /jobs/{id}/events?after=N` returns ordered `items` and `next`. Send `Accept: text/event-stream` for server-sent events and `Last-Event-ID` to reconnect where you left off. Phases, logs, metrics, episodes, artifact publication, token deltas and resource samples are distinct event kinds. Worker contact and event progress are separate fields, so a stale heartbeat is never shown as progress.

Errors are `{"error": {"code": "...", "message": "..."}}` with field diagnostics for validation. JSON bodies are limited to 2 MiB. One unfinished turn is allowed per conversation.

## Account environment

`GET /environment` returns the variable names and a revision without values. `POST /environment/reveal` returns the values. `PUT /environment` replaces the set: a string replaces a value, `null` keeps the saved one and an omitted name is removed. A stale revision is a 409, and a variable used by a connection or an active job cannot be removed.

A connection refers to a variable with `api_key_env` and a model import with `credential_env`. The value is resolved when it is used, never copied into a job or a task container.

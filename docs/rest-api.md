# REST API

The public contract is versioned under `/api/v1`. The frontend proxies this prefix to the Python API on the same origin. CLI users connect to the web origin as well. Internal worker and temporary provider-gateway endpoints are intentionally absent from the public proxy.

## Authentication

`POST /auth/register` accepts `username`, `password` and `invitation`. `POST /auth/login` issues an HTTP-only session cookie and a CSRF cookie. Mutating cookie-authenticated requests require the exact configured Origin and `X-CSRF-Token`. `POST /auth/logout` revokes the current session. `GET /me` returns the signed-in account.

For automation, use `POST /auth/token` with a username and password, or create an expiring named token with `POST /api-tokens`. Bearer tokens do not use CSRF cookies. All owner-bound resources return 404 to other accounts. Stored provider/HF keys are never returned. The API has login throttling and redacts validation inputs, so errors do not echo submitted secrets.

## Resources

| Method and path | Purpose |
| --- | --- |
| `GET /health`, `GET /capabilities` | API health and actual worker capabilities/resources |
| `GET /suites`, `GET /suites/{suite}/tasks` | Runnable catalog and optional split filtering |
| `GET /suites/{suite}/tasks/{task}` | Public prompt and task identity |
| `GET/POST /connections`, `PUT/DELETE /connections/{id}` | Model endpoints and encrypted keys |
| `POST /connections/{id}/check` | Check the provider's advertised model |
| `GET/POST /harness-profiles`, `PUT/DELETE /harness-profiles/{id}` | Markov/OpenCode configuration |
| `GET/POST /secrets`, `PUT/DELETE /secrets/{id}` | HF credentials; values are write-only |
| `POST /benchmarks` | Launch an agentic benchmark |
| `POST /models/imports` | Import a pinned HF model snapshot |
| `POST /training-runs`, `POST /evaluations` | Launch GRPO or direct model evaluation |
| `POST /deployments`, `POST /deployments/{id}/stop` | Start/stop worker-managed vLLM |
| `GET /jobs`, `GET /jobs/{id}` | Job state, config and results |
| `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retries` | Cancel or start a linked new attempt |
| `GET /jobs/{id}/events` | Cursor-based JSON or SSE event stream |
| `GET /artifacts`, `GET /artifacts/{id}` | Immutable artifact manifests and lineage |
| `GET /artifacts/{id}/files/{path}` | Download an owned artifact file |
| `GET/POST /conversations`, `GET /conversations/{id}` | Persistent conversations |
| `POST /conversations/{id}/turns` | Queue a streaming response from one or two models |

See [openapi.json](openapi.json) for request field types, validation bounds, status codes and schema names. Job result payloads vary by execution kind. In a running instance the schema is available at `/api/v1/openapi.json`; interactive documentation is at `/api/v1/docs`. The schema also documents worker endpoints, which are reachable only on the private API network.

## Submission and events

Every job-producing POST requires `Idempotency-Key`. Reuse the same key and payload after a transport timeout. Reusing it with another payload returns 409. The response is a durable job and HTTP 202; execution occurs in the Python worker. A connection's model/protocol configuration is captured at submission, while credentials can be rotated independently. Editing the captured configuration and then resubmitting the same key is a conflict; inspect the original job instead.

```sh
curl -fsS "$PG_GYM_URL/api/v1/benchmarks" \
  -H "Authorization: Bearer $PG_GYM_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ci-build-123-area' \
  -d '{"suite":"sql-function-set","tasks":["area"],"harness":"markov","connection_id":"CONNECTION_ID"}'
```

`GET /jobs?limit=50&before=CURSOR` returns `items` and an opaque `next` cursor. Pass it back unchanged. The cursor includes a tie-breaker, so jobs created at the same timestamp are not skipped. `kind` filters by job type. The browser's search/status filters apply to loaded rows; load older results when needed.

`GET /jobs/{id}/events?after=N` returns ordered `items` and `next`. Send `Accept: text/event-stream` for SSE and use `Last-Event-ID` to reconnect. Phases, logs, metrics, episodes, artifact publication, token deltas and resource samples have distinct event kinds. Worker contact and event progress are separate fields; stale contact must not be rendered as confirmed progress.

States are `queued`, `preparing`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`. Errors are structured as `{ "error": { "code": "…", "message": "…" } }`, with field diagnostics for validation. JSON bodies are limited to 2 MiB, including chunked requests; worker artifact uploads stream separately. List and event endpoints are bounded. Only one unfinished turn is allowed per conversation. A/B responses run sequentially and each connection receives its own prior responses.

`agentic-benchmark.v1` and `direct-diff-evaluation.v1` are distinct evaluation protocols. Training reward, held-out patch evaluation and harness benchmark reward must not be mixed into one performance metric.

## Account environment

`GET /api/v1/environment` returns `{revision, names}` without values. `POST /api/v1/environment/reveal` explicitly returns the authenticated account's `{revision, variables}`. `PUT /api/v1/environment` replaces the variable set with `{revision, variables}`: string values replace entries, `null` retains a saved value, and omitted names are removed. A stale revision returns 409. Names use `[A-Za-z_][A-Za-z0-9_]*`; values are encrypted at rest. Variables referenced by a connection or active job cannot be removed.

Set `api_key_env` on a connection to select a variable instead of a literal API key. Set `credential_env` on a model import to select an HF token instead of a legacy `credential_id`. Variable references are account-scoped and resolved when used; rotating a value affects subsequent requests. Values are not included in job configurations or exported into scored-task containers. Existing direct connection keys and HF credentials remain supported by the API.

`GET /api/v1/auth/options` is public and reports `registration_code_required`, allowing the login page to omit the code field for open-registration instances.

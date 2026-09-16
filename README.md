# Postgres Gym

A self-hosted workspace for PostgreSQL agent benchmarks, GRPO training, model evaluation and vLLM inference. The Python library remains the execution engine; the web application and `pg-gym` CLI use the same REST API and durable job queue.

The platform targets one Linux host with local SQLite storage, trusted account holders, Docker and optional NVIDIA GPUs. There is no Redis, MinIO, managed cloud dependency or demonstration execution path. See [verification](docs/verification.md) for checks actually performed and remaining hardware gates. Do not interpret a successful CPU test run as certification of a GPU deployment.

## Install and start

Install Python 3.12, uv, Docker Engine and Docker Compose v2. For GPU execution, install a compatible NVIDIA driver and NVIDIA Container Toolkit. Build from this repository; release container images are not assumed to be published.

```sh
uv tool install .
pg-gym platform start --source .
pg-gym platform registration-code
```

`platform start` creates the instance if needed, builds the platform images, and waits for the services to become healthy. Repeating it preserves instance data and secrets. Use `platform up` to start existing images without rebuilding. Docker and a complete source checkout are required for `platform start`; installing the CLI alone does not include the frontend source.

For a new local or trusted instance without registration codes, use `pg-gym platform start --source . --open-registration`. Anyone who can reach that instance can create an account. The default keeps registration codes enabled. Accounts own runs, connections and variables; separate projects are not implemented.

Open `http://localhost:8000`, create an account using the registration code, and add a model connection in Settings. Keys are encrypted on the API server; the browser never receives saved keys. For a local provider outside Compose, use `http://host.docker.internal:PORT/v1`, not `localhost`, which refers to the API container.

The CPU worker supports remote chat and Hugging Face model imports immediately. Benchmarks also need the task image built from the pinned PostgreSQL source:

```sh
pg-gym dev stand-fetch --source .
export MARKOV_SHA256=EXPECTED_SHA256_OF_YOUR_MARKOV_AMD64_ARCHIVE
pg-gym dev image --source .
pg-gym dev suite-check --suite sql-function-set
pg-gym dev suite-check --suite commit
```

The supplied task-image recipe downloads the user's Markov fork from `git.postgrespro.ru`. Access to that service and its pinned CA is required. On amd64 the expected archive checksum must be supplied; it cannot be inferred from an unavailable private build. The task image also installs OpenCode. Keep these prerequisites visible in deployment automation; an unavailable task image leaves benchmarks queued with no capable worker.

For GRPO, direct evaluation and local vLLM serving:

```sh
pg-gym platform start --source . --gpu
```

Set `PG_GYM_GPU` in `pg-gym-instance/platform.env` to the host GPU index, then restart the GPU worker. The GPU worker uses CUDA device 0 within its restricted container. One training, evaluation or serving job reserves that worker's GPU at a time; stop a deployment to free it for training. Do not run two worker identities against the same physical GPU.

For HTTPS, set `--origin https://gym.example.com` at initialization and terminate TLS at your reverse proxy. Match `PG_GYM_ORIGIN` exactly and enable secure cookies. Only the web port is published; `/internal` endpoints are not proxied by the web application. See [operations](docs/operations.md).

## Daily workflow

Workspace shows setup readiness, recent active jobs, model availability and workers. Launch benchmarks from Benchmark. Console provides read-only job events with search, event filters, auto-scroll and a download of the current view. Server service logs remain available through `pg-gym platform logs`.

1. **Settings / Environment:** save named variables using hidden inputs or the `.env` editor, then select a variable as a connection API key or Hugging Face credential. Values are encrypted, hidden on reload and revealed only on request. Variables belong to your account and are not exported into scored-task containers. **Settings / Connections:** add an OpenAI-compatible connection, check the advertised model and set whether it supports tool calling. Define Markov or OpenCode profiles and store HF credentials when needed.
2. **Benchmark:** choose a suite, task or split, harness and connection. Inspect phase changes, worker heartbeat, logs, episode rewards, patches and result files. Queued jobs survive closing the browser.
3. **Inference / Models:** import a safetensors model from HF. The resolved commit, metadata and checksums are recorded.
4. **RL:** train direct patch generation with GRPO on the train split. Evaluate the resulting base model or adapter separately on held-out tasks. Reward during training is not a held-out benchmark score.
5. **Inference / Servers:** serve the model or adapter with vLLM. Enable the model's tool parser when it will be used in a harness. Chat against local or remote connections, optionally comparing two independent conversation histories. Chat displays tool calls without executing them.
6. **Benchmark again:** use the deployed model inside Markov or OpenCode to measure agentic behavior. Results keep the protocol, task hashes and submitted configuration so incompatible evaluations can be distinguished.

Contact and progress are separate signals. A worker heartbeat means the supervisor is reachable. Recent logs, tokens, metrics or phases indicate execution activity. A spinner is not evidence of algorithmic progress; the UI explicitly reports quiet or disconnected jobs.

## CLI and REST

Install the CLI from a checkout or built wheel. Base CLI dependencies do not include PyTorch. The `platform` extra is needed to host the API and worker, not to connect remotely.

```sh
uv tool install .
pg-gym context add local --url http://localhost:8000
pg-gym auth login --username alice
pg-gym --output json suites list
pg-gym resources connections list
pg-gym --output json --timeout 3600 benchmark run --suite sql-function-set --task area --harness markov --connection CONNECTION_ID --wait
pg-gym jobs logs JOB_ID --follow
pg-gym jobs cancel JOB_ID
pg-gym --timeout 3600 models pull Qwen/Qwen2.5-Coder-3B-Instruct --wait
pg-gym --timeout 86400 rl train --config training.json --wait
pg-gym --timeout 86400 rl evaluate --artifact ADAPTER_ID --suite sql-function-set --split test --wait
pg-gym inference deploy --artifact MODEL_ID
pg-gym --timeout 300 inference chat --connection CONNECTION_ID --prompt 'Explain this query'
pg-gym artifacts download ARTIFACT_ID --directory ./model
```

`--config` supplies the complete launch payload; `--name` can override its name. Reuse `--idempotency-key` after an uncertain submission response. `--timeout` controls client request/wait time, not the remote experiment lifetime. Interrupting the client leaves the remote job running. Use `--min-solve-rate 0.5 --wait` for a CI benchmark threshold. Exit codes: 0 success, 1 job/server failure, 2 invalid input, 3 authentication/authorization, 4 transport failure, 6 unmet threshold, 124 wait timeout, 130 interrupted client.

External automation can call REST directly. [API guide](docs/rest-api.md), [OpenAPI JSON](docs/openapi.json), and `GET /api/v1/openapi.json` describe the contract.

## Python library

```python
from postgres_gym import Gym

gym = Gym('sql-function-set')
task = gym.task('area')
result = gym.run(task.name, 'cli:markov')
print(result.reward)
```

`pg-gym benchmark run --local` calls the library directly with its environment settings. It does not create a platform-owned experiment. Remote launch uses web/CLI -> REST -> Python worker -> Gym. Both paths preserve the existing Gym contract. `postgres-gym` and the original training entry points remain available for library users; platform lifecycle commands no longer depend on justfile.

## Repository and data

| Path | Responsibility |
| --- | --- |
| `src/postgres_gym/` | Existing Gym, task execution and training library |
| `src/postgres_gym_platform/` | REST, auth, SQLite, artifacts, worker and CLI |
| `src/postgres_gym_data/` | Wheel namespace for the included suite data |
| `suites/` | Original supplied suites, tasks, grading data and splits |
| `web/` | Fresh / Preact frontend and same-origin REST proxy |
| `deploy/platform/` | API, web and worker container deployment |
| `deploy/task/` | Disposable scored-task images |
| `tests/` | Library, platform and browser integration tests |

The included snapshot contains 1,268 suite files: 104 runnable SQL-function tasks and 85 runnable commit tasks. Some source tasks are intentionally outside the runnable selection. No synthetic extension suite or old local result history is included. The release wheel bundles suites and deployment templates so catalog discovery works outside a checkout. [Suite checksums](docs/suites-sha256.txt) identify the exact supplied snapshot.

## Development and checks

```sh
uv sync --frozen --extra platform --group training-lora
uv run ruff check src tests suites
uv run ty check src
uv run pytest
cd web
deno task check
deno task build
```

For local web development, run the API on port 8001 and `deno task dev` with its origin configured to the dev server origin. Start `pg-gym server worker` separately. Use a private registration code or explicitly set `PG_GYM_OPEN_REGISTRATION=1` only for an intended open-registration instance. Browser integration instructions are in [verification](docs/verification.md).

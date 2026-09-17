# Release verification

Verification date: 2026-09-13. Version: 0.2.0. This repository is a release candidate for a private, single-host platform. The CPU control plane has been exercised with real API, worker, frontend and CLI processes. Docker execution, PostgreSQL grading, GPU training and vLLM still require acceptance on the target host. Those gates were not replaced with simulated success results.

## Completed checks

| Check | Result and scope |
| --- | --- |
| Python regression suite | 62 tests passed: original Gym behavior, account isolation, auth/CSRF, concurrent idempotency, worker claims/recovery, event replay, cancellation, artifact checksums, SQLite restart and backup/restore |
| Python analysis | Ruff and ty passed for the configured source/test targets |
| Frontend | Deno formatting, lint, type checking and activity-state test passed; Fresh production build completed |
| Browser integration | Registration, provider configuration/check, profile edit preserving harness settings, held-out evaluation defaults, form persistence across polling, benchmark submission/cancellation, streamed chat, reload/history, cancellation during generation and mobile logout passed |
| Remote CLI integration | Context creation, registration, token login, catalog retrieval, connection creation, chat through the worker, queued benchmark cancellation and logout passed against the same real REST service |
| Layout | Desktop 1440×1000 and mobile 390×844; seven mobile routes checked for horizontal overflow; panel padding and a single active navigation item checked |
| Distribution | Wheel and source archive built; base CLI installed in a separate environment outside the checkout, without FastAPI or PyTorch; both suites and deployment templates discoverable; instance initialization, 0600 secret files, HTTPS cookie configuration and refusal to overwrite an instance passed |
| Original data | SHA-256 comparison of all 1,268 supplied suite files passed, including splits and grading data; 104 SQL-function and 85 commit tasks runnable |
| Task payload boundary | Both suites load and interpret a task payload in a fresh Python process with only suite code present and no suite data directory |

The browser provider is an explicit local OpenAI-protocol test fixture. It checks the real HTTP, queue, streaming and cancellation paths without making paid inference calls. It does not validate a specific model's chat template, tool parser or provider implementation. Benchmark cancellation in the browser test is cancellation while queued, because this environment has no Docker daemon. Cancellation propagation through the execution library and container-cleanup reservations are also covered by regression tests.

The Python run reports two upstream deprecation warnings from the Starlette test client and AnyIO; there were no test failures. Linux process-namespace differences in this validation environment are covered by the worker identity regression test. No claim is made that a prior run's successful test result covers later changes.

## Reproduce

```sh
uv sync --frozen --extra platform --group training-lora
uv run ruff check src tests suites
uv run ty check src
uv run pytest
deno task --cwd web check
deno task --cwd web build
npm ci --prefix tests --ignore-scripts
npx --prefix tests playwright install --with-deps chromium
uv run python tests/run_browser.py
uv build
sha256sum -c docs/suites-sha256.txt
```

The browser/CLI integration harness starts its own API, web, CPU worker and provider on ports 18800–18802, uses disposable data directories and fixture accounts, and stops them afterwards. It must run against the production frontend build. It creates no demo data in an operator instance. `PG_GYM_QA_OUTPUT` changes the output directory; `DENO_BIN`, `PLAYWRIGHT_PATH` and `CHROMIUM_PATH` allow explicit local runtime paths. CI is defined in `.github/workflows/checks.yml`.

## Target-host acceptance

1. Build API/web/worker images, initialize an instance and start it with `pg-gym platform start`. Confirm health, registration, browser login and remote CLI login over the intended HTTPS origin. Compose templates were reviewed here, but Docker Compose was not executed in this environment.
2. Fetch the pinned PostgreSQL mirror and build the task image using an accessible Markov archive and its verified checksum. Run both suite checks and `pg-gym dev selftest --suite sql-function-set --task area`. Check Markov and OpenCode separately against your actual tool-capable model connection.
3. Import a small compatible safetensors model. Verify its resolved revision and downloaded manifest. Real Hugging Face network transfers and gated repository credentials were not exercised here.
4. Run a short GRPO job on the train split. Confirm rewards come from actual disposable PostgreSQL tasks, metrics continue updating, and the resulting adapter/checkpoint files are readable. Stop a second run during grading and confirm its task containers are removed before the worker accepts another GPU job.
5. Evaluate on the test split, deploy the resulting adapter through vLLM, verify `/models`, chat, and run an agentic benchmark using that deployment's connection. Configure the tool parser for the actual model. Confirm that stopping the deployment removes its container and staging volume.
6. Restart API, web and worker during a job, using the same volumes and worker identity. Check history, event replay, cancellation and exclusive GPU reservation. Restore a quiesced backup into a separate empty instance and verify ownership, credentials and artifact downloads.

These are release gates on the intended hardware, not checks already completed. A build that cannot access the private Markov distribution cannot run that harness. GRPO currently assumes a compatible decoder model with the library's LoRA target modules; arbitrary HF architectures and custom model code are not supported.

## Deliberate limits

No public hostile tenancy, organizations, administrator UI, email password recovery, distributed scheduler, automatic storage reclamation, per-user storage quota, trainer auto-resume or shared host terminal. Interrupted training can leave unpublished worker-local checkpoints. Model/conversation lists are bounded to the newest 500/200 records. See [operations](operations.md) for storage, backup, secret handling and deployment boundaries.

## Workspace UX update

Workspace now provides setup readiness and a run overview; benchmark creation remains on Benchmark. Console reads persisted job events and supports filtering, auto-scroll and downloads of the displayed view. Settings separates connections, environment variables, harness profiles and account access. The Environment editor uses literal dotenv-style values, explicit reveal and revision-checked encrypted storage. Connection and HF credentials can reference those variables without exporting them into task containers.

For this update, frontend checks and the production build passed. The Python suite excluding `tests/test_training.py` passed 44 tests. Full pytest collection and full-source ty checking are blocked in this checkout by missing training dependencies, including datasets, torch and peft; these runs are not reported as passing. Ruff and type checking of the changed platform modules passed. The new `platform start` orchestration is tested with mocked Docker commands; real image builds and deployment acceptance remain target-host checks.

Browser and CLI integration passed against an isolated API, CPU worker, provider fixture and production frontend build. The browser run covered Environment save/hide/reveal, connection checks using a selected variable, console search, queued benchmark cancellation, streaming chat and nine mobile routes. Desktop and mobile screenshots were inspected. The browser worker is explicitly configured with an unavailable task image so these tests do not execute scored tasks on the operator host.

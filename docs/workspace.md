# The workspace

The web application at your instance's origin is the same platform the CLI talks to. Everything you launch there is a job in the same queue, and everything the CLI submits shows up there.

## Workspace

The first page shows setup readiness, the jobs that are active right now, which models are available and which workers are alive. It is the place to look when something seems stuck.

A worker heartbeat means the supervisor is reachable. Recent logs, tokens, metrics or a phase change mean the job is doing something. The two are reported separately on purpose, and a job that is quiet or has lost its worker says so instead of spinning.

## Settings

Settings holds four things, and the order below is the order you need them in.

**Environment** is a set of named variables owned by your account. Save them through hidden inputs or the `.env` style editor, and pick one later as a connection's API key or as a Hugging Face credential. Values are encrypted, hidden on reload, revealed only on request and never exported into a scored-task container.

**Connections** are OpenAI-compatible endpoints with a model name. The check button asks the endpoint which model it advertises. Mark the connection as tool-capable when the model supports tool calling, because the agent harnesses need that. A model served by the platform itself appears here on its own once the deployment is up. For a provider running on the host outside Compose use `http://host.docker.internal:PORT/v1`, since `localhost` inside the API container is the container.

**Profiles** configure the OpenCode or Goose-based harness a benchmark runs with: turn limit, timeout, temperature and how the context is kept under control.

**Access** manages the account and its API tokens for the CLI.

## Benchmarks

Pick a suite, then a task, several tasks or a split, then a harness and a connection, and launch. The job page shows phase changes, the worker heartbeat, logs, per-episode rewards, the patches the agent produced and the result files. Queued jobs survive closing the browser. See [Benchmarks](benchmarks.md) for what the numbers mean.

## Models and servers

Import a safetensors model from Hugging Face. The resolved commit, the file list and the checksums are recorded with the artifact. Serve an imported model or a trained adapter with vLLM from the same page, with the model's tool parser enabled when it will be used inside a harness. Every artifact keeps its lineage, so an adapter points at the model it was trained from and the run that produced it. See [Models and inference](inference.md).

## Inference

Chat against any connection, local or remote. Pick a second model to run two independent conversations side by side from the same prompts. Tool calls are shown but never executed here, this page is for looking at answers.

## Training

Train direct patch generation with GRPO on the train split of a suite, then evaluate the base model or the adapter on held-out tasks as a separate job. The reward curve during training is not a benchmark score, it is computed on training tasks. See [Training](training.md).

## Console

Console reads the persisted events of one job. It has search, event kind filters, auto-scroll and a download of the current view. Service logs of the platform itself are not here, those come from `pg-gym platform logs`.

# Collecting trajectories

Supervised fine-tuning of an agent needs examples of an agent doing the job. This is the tooling that records a strong teacher model solving tasks through the Goose-based harness, tool calls included, and turns the recordings into a dataset.

It lives in two scripts over `postgres_gym.collect` and needs the `collect` dependency group, which brings the harness SDK, `markov-sdk`, in.

```sh
uv sync --group collect
```

## Recording

```sh
uv run scripts/collect_teacher.py --run local/collect/teacher-2026-09-17 --suite sql-function-set --split train --task area --task cbrt
uv run scripts/collect_teacher.py --run local/collect/teacher-2026-09-17 --split train --attempts 2 --workers 2
```

Each task runs in the task container as usual. The harness runs inside it as an ACP server and is driven from the host through its SDK for one turn, while a recording proxy on the host sits between the agent and the model gateway and keeps every request and response verbatim. The teacher is reached through `MARKOV_API_KEY` from `.env`, and `--upstream` overrides the gateway host.

A run is a directory and it is resumable. Its configuration is frozen on the first episode, so a later invocation with another model or image is refused unless you pass `--force`. `--attempts` retries a task until it passes, `--workers` sets how many containers run at once, and `--limit` caps the tasks per suite for a smoke test.

| Option | Default | What it bounds |
| --- | --- | --- |
| `--max-turns` | 60 | Tool calls in one episode |
| `--token-budget` | 28000 | Prompt tokens before the episode is cut |
| `--agent-timeout` | 1800 | Seconds for the turn |

An episode that ends because of one of these limits is recorded with that reason, so a dataset can leave it out.

The container gets two more minutes than the SDK on the host, so a turn that overruns `--agent-timeout` is always cancelled from the host first. An attempt that breaks in the host process itself, for example when the SDK loses its connection, is recorded as `execution_error` with the traceback under `host_tail`, counts as an attempt and does not stop the run.

```sh
uv run scripts/collect_teacher.py --run local/collect/teacher-2026-09-17 --summary
```

`--summary` recomputes `summary.json` for the run without running anything, which is how you check progress from another terminal.

## Building the dataset

```sh
uv run scripts/build_dataset.py --run local/collect/teacher-2026-09-17 --out local/datasets/agent-sft-2026-09-17
```

The builder reads one or more runs, keeps the episodes that passed their grader and ended on a normal finish reason, and writes `train.jsonl`, `dev.jsonl` and `rejected.jsonl` next to a `manifest.json` that lists the sources, the counts and the checksums. Records follow the `agent-target-v1` format, one example per assistant turn with the conversation before it and the tools the agent had. The dev split holds out whole task groups with `--dev-fraction` and `--seed`, so a task never appears on both sides.

`rejected.jsonl` says why each dropped episode was dropped. Read it before deciding a run is big enough.

# Python library

`postgres_gym` is the engine underneath the platform. It loads a suite, packs a task into a payload, runs an agent on it in a disposable container and reads the record back. The worker calls it, `pg-gym benchmark run` calls it, and so can you.

```python
from postgres_gym import Gym

gym = Gym("sql-function-set")
print(gym.tasks(split="test"))

task = gym.task("area")
print(task.prompt)

result = gym.run(task.name, "cli:opencode")
print(result.ok, result.reward)
```

[`Gym`][postgres_gym.Gym] takes a suite id and an execution backend, `docker` unless told otherwise. `tasks` lists the runnable task names, optionally of one split. `task` returns a [`TaskSpec`][postgres_gym.TaskSpec] with the prompt, the public task data and the task hash. `run` executes one agent on one task and returns an [`EpisodeResult`][postgres_gym.EpisodeResult].

## What comes back

`result.execution` is the raw outcome of the container: return code, output and the record files it produced. `result.record` is the parsed record for this task and agent, or `None` when the run did not leave one. `ok` is true when both are fine and `reward` is the grader's number.

```python
result = gym.run("area", "cli:opencode", level="L1", judge=True)
if not result.ok:
    print(result.execution.stderr)
else:
    print(result.record["check"])
```

`level` picks the prompt level. `judge` adds an LLM judge score to the record, with `judge_model` and `judge_base_url` overriding the defaults from the environment. `environment` passes extra variables into the container, and `completion` hands a ready-made patch to the `patch` agent instead of running a model.

## Agents

The agent name says who edits the tree.

| Name | Who |
| --- | --- |
| `cli:opencode` | OpenCode inside the container, driven through its CLI |
| `cli:markov` | The Goose-based harness inside the container, the same way |
| `acp:markov` | The Goose-based harness as a server inside the container, driven from outside over ACP |
| `patch` | The patch you passed as `completion` |
| `replay`, `noop`, `cheat`, `probe` | The fixed agents that check the harness |

The external agents need a provider key, whichever harness they run. `MARKOV_API_KEY` is read from the environment or from `.env` at the repository root, and the run refuses to start without one.

## Shaping a request

`run` is `request` followed by `execute`. Split them when the request needs something extra, like a port or a label.

```python
from dataclasses import replace

request = gym.request("area", "acp:markov")
request = replace(request, ports=(9000,), labels={"experiment": "teacher"})
result = gym.execute(request)
```

[`TaskRequest`][postgres_gym.execution.TaskRequest] is what a backend runs. It has the payload, the agent, the level, the extra arguments and the environment, and it is immutable, so `dataclasses.replace` is how you change it.

## Verifying a task

`verify` runs the reference solution and then no change at all, and records whether the task is usable: the reference must pass and the untouched tree must fail exactly the expected tests.

```python
report = gym.verify("area")
print(report["status"], report["usable"])
```

## Backends

An [`ExecutionBackend`][postgres_gym.execution.ExecutionBackend] knows how to run a [`TaskRequest`][postgres_gym.execution.TaskRequest]. The Docker backend is the only one shipped. It runs the task image, sends the payload over stdin and collects the records the container writes. Pass a backend object to `Gym` to use your own, or a name to have [`load_backend`][postgres_gym.execution.load_backend] pick it.

## Settings

The library is configured from the environment, and a `.env` at the repository root is read on import.

| Variable | Default | What it does |
| --- | --- | --- |
| `POSTGRES_GYM_ROOT` | the checkout, or the installed data package | Where suites live |
| `POSTGRES_GYM_SUITE` | `sql-function-set` | Suite when `Gym` gets none |
| `POSTGRES_GYM_RUNS` | `local/runs` | Where records land |
| `POSTGRES_GYM_BACKEND` | `docker` | Execution backend |
| `POSTGRES_GYM_TASK_IMAGE` | `postgres-gym-task:17.11` | Image the backend runs |
| `POSTGRES_GYM_DOCKER_CONTEXT` | empty | Docker context to run in |
| `POSTGRES_GYM_AGENT_TIMEOUT` | `1800` | Seconds an agent may take |
| `POSTGRES_GYM_CONTAINER_TIMEOUT` | agent timeout plus 900 | Seconds a container may live |
| `MARKOV_API_KEY` | none | Provider key for the external agents |
| `POSTGRES_GYM_JUDGE_BASE_URL` | OpenRouter | Judge endpoint |
| `POSTGRES_GYM_JUDGE_MODEL` | `z-ai/glm-5.3` | Judge model |
| `OPENROUTER_API_KEY` | none | Judge key |

`POSTGRES_GYM_STAND`, `POSTGRES_GYM_SRC` and `POSTGRES_GYM_PG_MIRROR` place the PostgreSQL stand the task image is built from. `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_URL` send traces to a Langfuse instance when set.

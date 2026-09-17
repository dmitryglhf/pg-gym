# Benchmarks

A benchmark gives an agent a PostgreSQL task, lets it edit the source tree in a disposable container, builds the result and runs the tests that the task's reference change is known to fix. The reward is what the grader says, not what the model claims.

## Suites and tasks

Two suites ship with the repository.

| Suite | Tasks | What the agent does |
| --- | --- | --- |
| `sql-function-set` | 104 | Implement a SQL function with the required signatures so its regression tests pass |
| `commit` | 85 | Fix a described bug the way a real upstream commit did, graded by a hidden regression test |

Each suite has `train` and `test` splits, and the tasks that are runnable are a deliberate selection of the source data. A task has three prompt levels, `L0` to `L2`, from the barest statement to the most guided one.

```sh
pg-gym suites list
pg-gym tasks list sql-function-set --split test
pg-gym tasks show sql-function-set area
```

Every task carries a hash of its data. Results keep that hash together with the protocol name and the submitted configuration, so two evaluations that are not comparable can be told apart afterwards.

## Harnesses

The agent is OpenCode or a Goose-based harness, `opencode` and `markov` on the command line, running inside the task container and talking to the model connection you chose. The harness gets the prompt, the tree and its tools, and nothing else. It does not see the suite data, the oracle solution or earlier runs.

A profile fixes the harness settings: turn limit, timeout, temperature and the context strategy. Without one the defaults apply. Profiles are edited in Settings or created from a file.

```sh
pg-gym profiles create --config profile.json
```

## Submitting

```sh
pg-gym benchmark submit sql-function-set --split test --harness opencode --connection CONNECTION_ID --wait
pg-gym benchmark submit sql-function-set --task area --task cbrt --harness markov --connection CONNECTION_ID --profile PROFILE_ID
pg-gym benchmark inspect JOB_ID
```

`--config` takes a JSON or YAML file with the whole specification, which is the form to keep in a repository. Command line options fill in what the file leaves out, and `--name` overrides the display name.

```json
{
  "name": "nightly opencode",
  "suite": "sql-function-set",
  "split": "test",
  "harness": "opencode",
  "connection_id": "CONNECTION_ID",
  "timeout": 1800,
  "max_turns": 50
}
```

For CI, `--min-solve-rate 0.5 --wait` exits with code 6 when fewer than half the tasks pass. The exit codes are listed in [The CLI](cli.md#exit-codes).

## Reading a result

A job goes through `queued`, `preparing` and `running` before it ends in `succeeded`, `failed` or `cancelled`. The result carries one episode per task with its reward, the patch the agent left behind, the build and test output and the time it took.

```sh
pg-gym jobs logs JOB_ID --follow
pg-gym --output json jobs show JOB_ID
```

Agentic benchmarks use the `agentic-benchmark.v1` protocol. Held-out patch evaluation of a trained model uses `direct-diff-evaluation.v1`. A training reward, a held-out patch score and a harness benchmark measure different things and must not be averaged together.

## Running locally

The library can run a task without a platform. It needs Docker, the task image and the provider key the harness will use, read from `MARKOV_API_KEY` whichever harness it is.

```sh
export MARKOV_API_KEY=...
pg-gym benchmark run sql-function-set --task area --agent cli:opencode --level L0
pg-gym benchmark run sql-function-set --split test --agent cli:markov --since 2026-09-01T00:00:00
```

This does not create a platform job. The records land under `local/runs` and the command reports the tasks whose execution failed. `--judge` scores the submission with an LLM judge as well, using `--judge-model` and `--judge-base-url` or the defaults from the environment.

Besides the two harnesses there are four fixed agents that exist to check the harness itself.

| Agent | What it does | What it should score |
| --- | --- | --- |
| `replay` | Applies the reference solution | Everything passes |
| `noop` | Changes nothing | The expected tests fail |
| `cheat` | Strips the function from the reference tests instead of implementing it | Caught by the grader |
| `probe` | Looks for leaked answers in the container | Finds nothing |

```sh
pg-gym dev verify --suite sql-function-set --task area
pg-gym dev selftest --suite sql-function-set --task area
```

`verify` runs `replay` and `noop` on a task and records whether it is usable. `selftest` runs all four agents. Run both on a fresh task image before trusting a number from it.

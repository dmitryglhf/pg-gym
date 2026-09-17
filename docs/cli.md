# The CLI

`pg-gym` is one command with two halves. `benchmark run`, `dev` and `doctor` work on this machine with the library. Everything else talks to a platform over its REST API and needs a context.

```sh
uv tool install .
pg-gym doctor
```

The base install does not pull in PyTorch or FastAPI. The `platform` extra is for hosting the API and the worker, not for connecting to them.

## Contexts and login

A context is a saved platform address with a token.

```sh
pg-gym context add local --url http://localhost:9432
pg-gym context add lab --url https://gym.example.com
pg-gym context use lab
pg-gym context list
```

The first context you add becomes active. `--context NAME` on any command uses another one for that call.

```sh
pg-gym auth register --username alice
pg-gym auth login --username alice
pg-gym auth status
pg-gym auth logout
```

`register` asks for the registration code, or reads it from `PG_GYM_REGISTRATION_TOKEN` or `--invitation-stdin`. On an open instance pass `--open-registration`. `login` stores a session token in the context. For automation, create an expiring API token in Settings and hand it to `login --token-stdin`, and use `--password-stdin` when a script has to log in with a password. `logout` revokes the token on the server and forgets it.

## Output

Every command prints a table by default. `--output json` and `--output jsonl` print the same data as one document or one line per item, and `--json` and `--jsonl` are shorthands. `--no-color` keeps the table plain.

```sh
pg-gym --json jobs list --kind benchmark --limit 5
pg-gym --jsonl artifacts list | jq -r .id
```

Expected failures are printed as one JSON line on stderr, with a code and a message, so a script can tell a validation error from a network one.

## Jobs

Benchmarks, imports, training runs, evaluations and deployments are all jobs, and `jobs` handles any of them.

```sh
pg-gym jobs list --all
pg-gym jobs show JOB_ID
pg-gym jobs wait JOB_ID
pg-gym jobs logs JOB_ID --follow
pg-gym jobs cancel JOB_ID
pg-gym jobs retry JOB_ID
```

`wait` blocks until the job is over and exits 1 unless it succeeded. `logs` prints the persisted events and `--follow` keeps streaming until the end; `--after N` resumes from an event number. `cancel` is immediate for a queued job and asks a running one to stop. `retry` submits a new job with the same specification, linked to the old one.

Interrupting the client never stops the remote job. Cancel it explicitly if that is what you want.

## Submitting

The commands that create jobs share a shape.

```sh
pg-gym benchmark submit sql-function-set --task area --harness opencode --connection CONNECTION_ID --wait
pg-gym models pull Qwen/Qwen2.5-Coder-3B-Instruct --wait
pg-gym rl train MODEL_ID --suite sql-function-set --split train --config training.json
pg-gym rl evaluate ADAPTER_ID --suite sql-function-set --split test
pg-gym inference deploy MODEL_ID
```

`--config` takes a JSON or YAML file with the complete specification, and the command line fills in or overrides fields. `--name` sets the display name. `--wait` blocks until the job ends. `--idempotency-key` lets you resend a submission after an uncertain response without creating a second job, and reusing the key with a different payload is an error.

## Timeouts

`--timeout` bounds one HTTP request, sixty seconds by default. `--wait-timeout` bounds how long `--wait` waits, ten minutes by default. Neither limits the job on the platform. A long import or a training run wants both raised.

```sh
pg-gym --timeout 3600 --wait-timeout 86400 rl train --config training.json --wait
```

## Resources

Connections, credentials and profiles are created from a file, listed and deleted. Editing happens in the web application.

```sh
pg-gym connections create --config connection.json
pg-gym connections list
pg-gym connections delete CONNECTION_ID
```

```json
{
  "name": "openrouter qwen",
  "base_url": "https://openrouter.ai/api/v1",
  "model": "qwen/qwen3-coder",
  "api_key_env": "OPENROUTER_API_KEY",
  "context_length": 32768,
  "max_tokens": 4096,
  "tools": true
}
```

`api_key_env` names a variable from your account's Environment. `api_key` takes the key literally instead. A credential is a name and a value, and a profile is described in [Benchmarks](benchmarks.md#harnesses).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | The job or the command failed |
| 2 | Invalid input |
| 3 | Not authenticated |
| 4 | Transport failure |
| 6 | Solve rate below `--min-solve-rate` |
| 124 | `--wait-timeout` ran out |

## Local commands

`benchmark run` executes tasks on this machine through the library and does not create a platform job. `dev` builds the task image and checks suites and tasks. Both are covered in [Benchmarks](benchmarks.md#running-locally) and [The platform](platform.md#the-task-image). `server api` and `server worker` run the platform processes in the foreground, see [The platform](platform.md#without-compose).

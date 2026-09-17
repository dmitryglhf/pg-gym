# The platform

An instance is a directory with a Compose file, an environment file, data volumes and secret files. `pg-gym platform` manages one of those.

```sh
pg-gym platform start --source .
pg-gym platform status
pg-gym platform logs --service api --follow
pg-gym platform stop
```

`start` does three things. It runs `init` when the directory does not exist yet, it builds the API, web and worker images from `--source`, and it brings the services up and waits for them to become healthy. Repeating it rebuilds the images and keeps the data and the secrets. `images` builds without starting anything, which is the step to run after pulling a new release.

The instance directory defaults to `pg-gym-instance` next to where you run the command. Pass `--directory` to put it elsewhere, and run the command as the Unix user who will own those volumes.

## What init creates

`platform init` writes `compose.yaml`, `platform.env`, the `data/`, `worker-data/` and `gpu-worker-data/` volumes and three private secret files. It refuses a directory that is not empty.

`platform.env` holds infrastructure options only. Model API keys do not belong there, they go into Settings in the web application. The master encryption key and the worker token stay operator-managed files with restrictive permissions. Losing the master key makes every saved credential unreadable, so back the directory up.

## Registration

New accounts need the registration code by default.

```sh
pg-gym platform registration-code
```

For a local or otherwise trusted instance you can skip the code with `--open-registration` on `start` or `init`. Anyone who can reach the instance can then create an account. Accounts own their runs, connections and variables. There are no projects or organisations.

A forgotten password is reset from the host, and doing so revokes every session and API token of that account.

```sh
pg-gym platform reset-password alice --directory pg-gym-instance
```

## The task image

Scored tasks run in disposable containers built from the pinned PostgreSQL source. The CPU worker can serve chat and model imports without it, but a benchmark stays queued until a worker with the image exists.

```sh
pg-gym dev stand-fetch --source .
export MARKOV_SHA256=EXPECTED_SHA256_OF_YOUR_MARKOV_AMD64_ARCHIVE
pg-gym dev image --source .
pg-gym dev suite-check --suite sql-function-set
pg-gym dev suite-check --suite commit
```

`stand-fetch` clones the PostgreSQL mirror and pins the pristine ref the tasks are cut from. `image` builds `deploy/task/Dockerfile`, which installs OpenCode and the Goose-based harness, downloaded from `git.postgrespro.ru`. The image needs both, so access to that service and its pinned CA is required, and on amd64 the archive checksum has to be given through `MARKOV_SHA256`, it cannot be inferred. `suite-check` validates the suite data and reports the first problems it finds.

Keep these prerequisites in your deployment automation. A worker without the task image is a worker that cannot score anything.

## GPUs

Training, direct evaluation and vLLM serving need the GPU worker.

```sh
pg-gym platform start --source . --gpu
```

Set `PG_GYM_GPU` in `platform.env` to the host GPU index and restart the GPU worker. Inside its container the worker always sees CUDA device 0. One training, evaluation or serving job holds that GPU at a time, so stop a deployment before you train. Never point two worker identities at the same physical GPU.

## HTTPS

Only the web port is published, bound to `127.0.0.1`. For remote access put a reverse proxy with TLS in front of it and initialise the instance with the public origin.

```sh
pg-gym platform start --source . --origin https://gym.example.com
```

The origin has to match `PG_GYM_ORIGIN` exactly, because cookie-authenticated requests are checked against it. Secure cookies are enabled with it. The `/internal` endpoints are not proxied by the web application and stay on the private network.

## Without Compose

The API and the worker are plain processes too, which is how the tests run them.

```sh
cp .env.example .env
pg-gym server api --port 9433
pg-gym server worker --url http://127.0.0.1:9433 --id local
```

`.env.example` lists the variables both read. The worker needs the Docker socket and the task image to score tasks, and a worker started this way is part of the trusted execution boundary just like the Compose one.

## Backups and updates

`platform backup` archives the database, the secrets and the artifact files with SQLite's online backup. Quiesce submissions and stop the workers first, so the copy is consistent.

```sh
pg-gym platform backup ./pg-gym-backup.zip --directory ./pg-gym-instance
pg-gym platform restore ./pg-gym-backup.zip --directory ./restored-instance
```

The archive contains encrypted credentials together with the key that decrypts them, so protect it like a secret. It does not contain the worker's in-flight execution directories, the Docker images or the downloaded PostgreSQL mirror. `restore` needs the API and the workers stopped and an empty destination, and it keeps the original jobs and ownership. Try a restore on a disposable instance before you rely on a backup policy.

To update, back up, stop the workers, run `platform start --source` from the new release and let it rebuild. It regenerates `compose.yaml` from the release template and adds the `platform.env` keys the new release reads while keeping your values, so review both files afterwards. The API migrates the schema forward and refuses a database written by a newer release. Keep the old images and the backup until you are sure.

## What the host is trusted with

The worker talks to the host Docker socket, which makes it part of the trusted boundary. Task containers get their payload over stdin and a temporary gateway token, never the operator's provider key, the suites, the host workspace or earlier runs. Docker is not a sandbox against hostile tenants, so use dedicated worker hosts or a stronger isolation layer before opening an instance to strangers.

SQLite holds accounts, sessions, encrypted credentials, the queue, the event history and the model manifests. Model files live on disk next to it. Keep that directory on local storage and run one API against it. There is no garbage collection or storage quota, so watch disk usage and decide on a retention policy yourself. Do not delete artifact files while their manifests are referenced.

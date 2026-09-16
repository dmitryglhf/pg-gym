# Operations

## Supported deployment boundary

This release is designed for a single Linux Docker host with local durable storage and trusted users. SQLite stores accounts, ownership, sessions, encrypted connection credentials, experiment configurations, the queue, event history, model manifests and conversations. Model files live on disk outside SQLite. The API uses WAL, foreign keys, a busy timeout, explicit transactions and schema versions. Do not place the SQLite directory on NFS or run several API replicas against it. Redis and object storage are not needed for this topology.

The worker has access to the host Docker socket and is part of the trusted execution boundary. Never expose that socket to the browser, task containers or model-serving containers. Disposable tasks receive their own payload through stdin and a temporary provider-gateway token. They receive neither the operator's provider key nor API/worker management credentials; no full suites, host workspaces or previous runs are mounted into a scored task. Docker is not a hardened sandbox for hostile tenants exploiting kernel vulnerabilities. Use dedicated worker hosts or stronger virtualization before opening the instance to untrusted public users.

Only the web service publishes a port, bound to 127.0.0.1 by default. Place a reverse proxy with TLS and request limits in front of it for remote access. Registration is restricted by a generated invitation code; public registration requires an explicit environment setting. Use individual accounts and expiring CLI tokens. There is no organization layer or administrator web console.

## Instance configuration

`pg-gym platform init` creates `compose.yaml`, `platform.env`, `data/`, `worker-data/`, `gpu-worker-data/` and private secret files. Run it as the Unix user who will own those volumes. Initialization refuses a nonempty destination. `platform.env` contains infrastructure options, not model API keys. Connections and HF credentials belong in Settings. The API's master encryption key and worker authentication token remain operator-managed files with restrictive permissions; losing the master key makes saved credentials unreadable.

`PG_GYM_ALLOWED_HOSTS` is a comma-separated allowlist for explicitly trusted private inference hosts. A connection to other private, loopback or infrastructure metadata addresses is rejected. Public DNS results are validated and pinned for upstream requests. Do not add arbitrary API, orchestration or cloud metadata hosts. Managed vLLM endpoints are registered only by the worker. All accounts share the infrastructure allowlist.

`PG_GYM_TASK_CPUS` and `PG_GYM_TASK_MEMORY` set per-task resource caps. NVIDIA GPU selection is configured per GPU worker. The default supervisor accepts up to four non-GPU tasks and one GPU job per worker; the per-account active-job limit is 20. Resource sampling reports host/worker utilization, not a claim of per-model accounting. Model downloads and artifact publication need space for both worker copies and API-owned copies; allow extra headroom for retained checkpoints and vLLM staging volumes.

## Jobs, restart and cancellation

The server atomically records submissions and idempotency keys before replying. The worker persists its claim key before requesting a job and can recover an assignment if the reply is lost. Each execution runs in a child process with a recorded PID and process creation time. Events are appended locally and uploaded with deduplication identifiers. The UI and API can resume after an event cursor.

Restart a worker with the same ID and data directory. A live child is reattached by process identity; a dead child is reported as interrupted after container cleanup. An incomplete last log line cannot hold a dead job open. Jobs are not automatically retried after a lost worker, because an ambiguous retry can double-spend resources. If a worker host or its durable directory is destroyed, reconcile its containers and jobs before starting another worker using that identity. GPU reservations remain held while cleanup is unresolved.

A queued cancellation is immediate. A running cancellation requests SIGTERM, followed by SIGKILL if the process has not exited within 30 seconds. The worker owns cleanup of task containers. Cancellation keeps partial chat outputs and recorded episode summaries. Model/training artifact publication is not an atomic transaction with cancellation: interrupted training may leave local checkpoints that have not been published to the platform. Automatic trainer resumption from those checkpoints is not implemented. Do not delete worker storage while jobs are active.

A quiet trainer may be compiling, downloading, evaluating or stalled. Heartbeats confirm contact only; inspect phase, last progress, logs and resource samples. API or web outages do not stop remote jobs. A stopped vLLM deployment leaves its configuration/history visible; start a new deployment to restore service and select the new connection.

## Backup, restore and updates

Quiesce submissions and stop workers before a consistent full backup. The backup command uses SQLite's online backup API and includes the master key, authentication secrets and artifact files. It does not include the worker's in-flight execution directories, Docker images or downloaded PostgreSQL mirror. Preserve worker directories separately if resuming in-flight processes is required.

```sh
export PG_GYM_DATA="$PWD/pg-gym-instance/data"
export PG_GYM_SECRET_DIR="$PWD/pg-gym-instance/secrets"
pg-gym storage backup ./pg-gym-backup.zip
```

Backups contain credentials in encrypted form together with their decryption key. Protect them as secrets. Restore with API/workers stopped and empty destination directories, using `pg-gym storage restore PATH`. Malformed paths and unexpected archive members are rejected. The restore keeps the original jobs and ownership; worker/process recovery still requires the corresponding worker storage and host. Run restore verification on a disposable instance before relying on a backup policy.

After changing a forgotten password with `pg-gym storage reset-password USER`, all sessions and API tokens for that user are revoked. There is no email password-reset flow.

Before updating, back up the instance, stop workers, build matching API/web/worker images from the new release, and restart. The API migrates schema versions forward and rejects a database from a newer release. Keep the old images and backup for rollback. Do not replace a newer database with older application code without restoring a compatible backup.

## Artifact retention and scaling

Ready artifact files are immutable and checked against their declared size and SHA-256 before publication. The UI and CLI expose lineage and downloads. Imports only fetch allowed model/tokenizer files and do not enable remote model code. Local model files are mounted read-only into vLLM, with HF offline mode and a per-deployment API key.

There is no automatic garbage collection or per-user storage quota in this release. Monitor disk usage and establish an operator retention policy. Do not remove artifact files directly while their manifests are referenced. A missing file is reported as a storage error, not silently recreated. S3-compatible storage can be added behind the artifact interface when multi-host storage or capacity justifies it; safetensors does not itself require MinIO.

A shared terminal is deliberately absent. Use operator SSH or Docker tools for trusted maintenance. A future task terminal must attach to one isolated job with an explicit lifetime and authorization boundary, never to the API container or arbitrary host directory.

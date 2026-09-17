import { useEffect, useRef, useState } from "preact/hooks";
import type { ChatModel } from "@/lib/chat-models.ts";
import type { Job, Worker } from "@/lib/platform.ts";
import { message, terminal } from "@/lib/platform.ts";
import { readiness } from "@/lib/readiness.ts";
import { loadDeployments, useResource } from "@/lib/query.ts";
import { startModelServer } from "@/lib/serving.ts";
import { openActivity, preparationHref, useDraft } from "@/lib/workspace.ts";
import { Notice, Status } from "../PlatformUI.tsx";

/** Chat chooses a model; the serving service owns its execution lifecycle. */
export function LocalModelLaunch(
  { model, workers, jobs, comparisonBlocked, onChanged, onLeave }: {
    model: ChatModel;
    workers: Worker[];
    jobs: Job[];
    comparisonBlocked: boolean;
    onChanged: () => void;
    onLeave: () => void;
  },
) {
  const artifact = model.artifact!;
  const [pending, setPending] = useDraft("chat-server:" + artifact.id, "");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [queueFor, setQueueFor] = useState("");
  const lock = useRef(false), lastState = useRef("");
  const watchId = model.deployment?.id || pending;
  const watched = useResource<Job>(
    watchId ? "/jobs/" + encodeURIComponent(watchId) : null,
    2000,
  );
  useEffect(() => {
    if (model.deployment && model.deployment.id !== pending) {
      setPending(model.deployment.id);
    }
  }, [model.deployment?.id, pending]);
  useEffect(() => {
    const job = watched.data;
    if (!job) return;
    const key = [
      job.id,
      job.status,
      job.result?.connection_id,
      job.cancel_requested,
    ].join(":");
    if (lastState.current === key) return;
    lastState.current = key;
    onChanged();
  }, [watched.data, onChanged]);
  const current = watched.data || model.deployment;
  const running = current && !terminal(current);
  const availability = readiness("deployment", workers, jobs);
  const canStart = artifact.status === "ready" && availability.available &&
    !comparisonBlocked &&
    (!availability.busy || queueFor === availability.busy.id);
  async function start() {
    if (lock.current || !canStart || running) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      // Reconcile first: the user may already have started this server in another tab.
      const latest = await loadDeployments("/jobs?kind=deployment&limit=200");
      const existing = latest.find((job) =>
        job.config.artifact_id === artifact.id && !terminal(job)
      );
      const job = existing || await startModelServer(artifact);
      setPending(job.id);
      onChanged();
    } catch (cause) {
      setError(message(cause));
      onChanged();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section class="local-chat-launch" aria-label={model.name + " server"}>
      <div class="local-chat-heading">
        <div>
          <strong>{model.name}</strong>
          <p class="muted">
            {artifact.kind === "model"
              ? "Downloaded model · fine-tuning is optional"
              : "Trained variant · uses its saved base model"}
          </p>
        </div>
        {current && <Status job={current} />}
      </div>
      {artifact.status !== "ready"
        ? (
          <Notice>
            The model files are not ready yet. Complete the download in Models &
            servers.
          </Notice>
        )
        : running
        ? (
          <p>
            {current.cancel_requested
              ? "The server is stopping. Wait for it to stop before restarting."
              : current.status === "queued"
              ? "Server requested and waiting for a worker. Your message draft is saved."
              : !current.worker_connected
              ? "Contact with the server worker was lost. Open its logs or inspect workers in Workspace."
              : current.result?.connection_id
              ? "Server ready. Connecting it to this chat…"
              : "Starting the model server. Your message draft is saved."}
          </p>
        )
        : (
          <p>
            Start a server to chat with these weights. It keeps a worker GPU
            occupied until you stop it.
          </p>
        )}
      {(!availability.available ||
        (availability.busy && availability.busy.id !== current?.id)) && (
        <Notice>
          {availability.reason} {!availability.available && (
            <>
              <a href="/#workers" onClick={onLeave}>Inspect workers</a>
              {" · "}
              <a
                href="/models?add&source=api&return=inference"
                onClick={onLeave}
              >
                Connect an API
              </a>
            </>
          )}
        </Notice>
      )}
      {availability.busy && !running && (
        <label class="check-field">
          <input
            type="checkbox"
            checked={queueFor === availability.busy.id}
            onChange={(event) =>
              setQueueFor(
                event.currentTarget.checked ? availability.busy!.id : "",
              )}
          />Queue explicitly; the running server will not stop automatically
        </label>
      )}
      {(error || watched.error ||
        (current && terminal(current) && current.error)) && (
        <Notice error>{error || watched.error || current?.error}</Notice>
      )}
      <div class="inline-actions">
        {!running && (
          <button
            class="button primary"
            type="button"
            disabled={busy || !canStart}
            onClick={start}
          >
            {busy
              ? "Checking server…"
              : availability.busy
              ? "Queue for chat"
              : "Start for chat"}
          </button>
        )}
        {watchId && (
          <button
            class="button secondary"
            type="button"
            onClick={() => openActivity(watchId)}
          >
            Open server logs
          </button>
        )}
        <a href={preparationHref("inference", artifact.id)} onClick={onLeave}>
          Server settings
        </a>
      </div>
    </section>
  );
}

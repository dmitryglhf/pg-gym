import { cloneElement, isValidElement, toChildArray } from "preact";
import type { ComponentChildren, JSX, VNode } from "preact";
import { useEffect, useId, useRef, useState } from "preact/hooks";
import { api, bytes, date, message, metric, terminal } from "@/lib/platform.ts";
import type { Artifact, Job, Worker } from "@/lib/platform.ts";

export function Notice(
  { children, error = false }: { children: ComponentChildren; error?: boolean },
) {
  return (
    <div
      class={`notice ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Empty({ children }: { children: ComponentChildren }) {
  return <p class="empty-state">{children}</p>;
}
export function Field(
  { label, children, hint }: {
    label: string;
    children: ComponentChildren;
    hint?: string;
  },
) {
  const id = useId();
  return (
    <label class="field">
      <span id={id}>{label}</span>
      {toChildArray(children).map((child) =>
        isValidElement(child)
          ? cloneElement(child as VNode<Record<string, unknown>>, {
            "aria-labelledby": id,
            "aria-describedby": hint ? id + "-hint" : undefined,
          })
          : child
      )}
      {hint && <small id={id + "-hint"}>{hint}</small>}
    </label>
  );
}
export function Form(
  { onSubmit, children, submit, disabled = false }: {
    onSubmit: (data: FormData) => Promise<string | void>;
    children: ComponentChildren;
    submit: string;
    disabled?: boolean;
  },
) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  const lock = useRef(false);
  async function send(event: JSX.TargetedEvent<HTMLFormElement, SubmitEvent>) {
    event.preventDefault();
    if (lock.current || disabled) return;
    lock.current = true;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      setSuccess(await onSubmit(data) || "");
    } catch (cause) {
      setError(message(cause));
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <form onSubmit={send} aria-busy={busy}>
      <fieldset disabled={busy} class="form-body">{children}</fieldset>
      {error && <Notice error>{error}</Notice>}
      {success && <Notice>{success}</Notice>}
      <div class="form-actions">
        <button
          class="button primary"
          type="submit"
          disabled={busy || disabled}
        >
          {busy ? "Working…" : submit}
        </button>
      </div>
    </form>
  );
}
export function Status({ job }: { job: Job }) {
  const label =
    !terminal(job) && job.status !== "queued" && !job.worker_connected
      ? "Contact lost"
      : job.kind === "deployment" && !terminal(job) &&
          job.result?.connection_id && !job.cancel_requested
      ? "Ready"
      : job.cancel_requested && !terminal(job)
      ? "Stopping"
      : job.status;
  return (
    <span
      class={`status-chip status-${
        label === "Contact lost" ? "unknown" : job.status
      }`}
    >
      {label}
    </span>
  );
}
export function JobTable(
  { jobs, compare = false }: { jobs: Job[]; compare?: boolean },
) {
  const [selected, setSelected] = useState<string[]>([]);
  if (!jobs.length) {
    return (
      <Empty>
        No jobs yet. Submitted jobs and their results will appear here.
      </Empty>
    );
  }
  return (
    <>
      {compare && selected.length > 0 && (
        <div class="selection-bar">
          <span>{selected.length} selected</span>
          <a
            class="button secondary"
            href={selected.length > 1
              ? `/results?compare=${selected.join(",")}`
              : undefined}
            aria-disabled={selected.length < 2}
          >
            Compare
          </a>
          <button
            type="button"
            class="text-button"
            onClick={() => setSelected([])}
          >
            Clear
          </button>
        </div>
      )}
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              {compare && (
                <th>
                  <span class="sr-only">Compare</span>
                </th>
              )}
              <th>Experiment</th>
              <th>Status</th>
              <th>Model / harness</th>
              <th class="num">Result</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                {compare && (
                  <td>
                    <input
                      aria-label={`Compare ${job.name}`}
                      type="checkbox"
                      checked={selected.includes(job.id)}
                      disabled={!terminal(job) ||
                        !["benchmark", "evaluation"].includes(job.kind) ||
                        (!selected.includes(job.id) && selected.length >= 4)}
                      onChange={(e) =>
                        setSelected(
                          e.currentTarget.checked
                            ? [...selected, job.id]
                            : selected.filter((id) => id !== job.id),
                        )}
                    />
                  </td>
                )}
                <td>
                  <a class="row-link" href={`/jobs/${job.id}`}>{job.name}</a>
                  <small>
                    {job.kind.replaceAll("_", " ")} · {job.id.slice(0, 8)}
                  </small>
                </td>
                <td>
                  <Status job={job} />
                </td>
                <td>
                  {job.config.connection?.model ||
                    (typeof job.config.repository === "string"
                      ? job.config.repository
                      : job.config.artifact_id?.slice(0, 12)) ||
                    "—"}
                  <small>
                    {job.config.harness || job.config.protocol || ""}
                  </small>
                </td>
                <td class="num">
                  {["benchmark", "evaluation"].includes(job.kind)
                    ? (
                      <>
                        {metric(job.result?.mean_reward)}
                        <small>
                          Scored reward ·{" "}
                          {String(job.result?.execution_errors ?? "—")}{" "}
                          execution errors
                        </small>
                      </>
                    )
                    : job.kind === "deployment"
                    ? (job.result?.connection_id && !terminal(job)
                      ? "Server ready"
                      : terminal(job)
                      ? "Server inactive"
                      : "Starting server")
                    : job.kind === "model_import"
                    ? (job.status === "succeeded"
                      ? "Files downloaded"
                      : "Download")
                    : job.kind === "training"
                    ? (job.result?.artifact_id
                      ? "Adapter available"
                      : "Training")
                    : "Conversation"}
                </td>
                <td class="nowrap">{date(job.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
export function Resources({ workers }: { workers: Worker[] }) {
  return (
    <section class="panel">
      <div class="panel-heading">
        <h2>Workers</h2>
        <span class="muted">
          {workers.filter((w) => w.connected).length} connected
        </span>
      </div>
      {!workers.length
        ? (
          <Empty>
            No worker has connected. Jobs will remain queued until a capable
            worker is online.
          </Empty>
        )
        : (
          <div class="worker-grid">
            {workers.map((w) => (
              <div class="worker" key={w.id}>
                <div class="split-line">
                  <strong>{w.id}</strong>
                  <span
                    class={`status-chip ${
                      w.connected ? "status-succeeded" : "status-unknown"
                    }`}
                  >
                    {w.connected ? "Connected" : "Offline"}
                  </span>
                </div>
                <small>Sample: {date(w.sample_at)}</small>
                <div class="resource-values">
                  <span>
                    CPU{" "}
                    <strong>
                      {w.connected
                        ? metric(w.resources.cpu_percent, 0) + "%"
                        : "—"}
                    </strong>
                  </span>
                  <span>
                    RAM{" "}
                    <strong>
                      {w.connected ? bytes(w.resources.ram_used) : "—"} /{" "}
                      {bytes(w.resources.ram_total)}
                    </strong>
                  </span>
                </div>
                {w.resources.gpus?.map((gpu) => (
                  <div key={gpu.index}>
                    <div class="split-line">
                      <span>{gpu.name}</span>
                      <strong>
                        {w.connected ? metric(gpu.utilization, 0) + "%" : "—"}
                      </strong>
                    </div>
                    <small>
                      VRAM {w.connected ? bytes(gpu.memory_used) : "—"} /{" "}
                      {bytes(gpu.memory_total)}
                    </small>
                  </div>
                ))}
                <small>{w.capabilities.join(" · ")}</small>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}
export function ArtifactSelect(
  {
    artifacts,
    name = "artifact_id",
    modelsOnly = false,
    initial = "",
    "aria-labelledby": labelledBy,
  }: {
    "aria-labelledby"?: string;
    artifacts: Artifact[];
    name?: string;
    modelsOnly?: boolean;
    initial?: string;
  },
) {
  const [selected, setSelected] = useState(initial);
  return (
    <select
      name={name}
      required
      value={selected}
      onChange={(e) => setSelected(e.currentTarget.value)}
      aria-labelledby={labelledBy}
    >
      <option value="">
        Select a {modelsOnly ? "base model" : "model or adapter"}
      </option>
      {artifacts.filter((a) =>
        a.status === "ready" &&
        (a.kind === "model" || (!modelsOnly && a.kind === "adapter"))
      ).map((a) => (
        <option value={a.id} key={a.id}>{a.name} · {a.id.slice(0, 8)}</option>
      ))}
    </select>
  );
}
export function usePoll<T>(path: string, interval = 5000) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    setData(null);
    async function read() {
      try {
        const value = await api<T>(path);
        if (!stopped) {
          setData(value);
          setError("");
        }
      } catch (cause) {
        if (!stopped) setError(message(cause));
      } finally {
        if (!stopped) timer = setTimeout(read, interval);
      }
    }
    read();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [path, interval]);
  return { data, error };
}

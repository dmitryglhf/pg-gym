import { useEffect, useRef, useState } from "preact/hooks";
import { api, bytes, date, message, metric, terminal } from "@/lib/platform.ts";
import type {
  Artifact,
  ChatOutput,
  Episode,
  Event,
  Job,
} from "@/lib/platform.ts";
import { ActivityStatus, useActivityClock } from "./ActivityStatus.tsx";
import { DiffView } from "./DiffView.tsx";
import { Empty, Notice, Status } from "./PlatformUI.tsx";

export function JobMonitor(
  { id, compact = false, connectionNames = {} }: {
    id: string;
    compact?: boolean;
    connectionNames?: Record<string, string>;
  },
) {
  const [job, setJob] = useState<Job | null>(null),
    [events, setEvents] = useState<Event[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [follow, setFollow] = useState(true);
  const [outputs, setOutputs] = useState<Record<string, ChatOutput>>({});
  const logs = useRef<HTMLPreElement>(null);
  const now = useActivityClock(!job || !terminal(job));
  useEffect(() => {
    let stopped = false, cursor = 0, timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const [current, batch] = await Promise.all([
          api<Job>(`/jobs/${id}`),
          api<{ items: Event[]; next: number }>(
            `/jobs/${id}/events?after=${cursor}`,
          ),
        ]);
        if (stopped) return;
        cursor = batch.next;
        setJob(current);
        setError("");
        if (batch.items.length) {
          setEvents((old) => [...old, ...batch.items].slice(-5000));
          setOutputs((old) => {
            const next = structuredClone(old);
            for (const event of batch.items) {
              if (event.kind !== "delta") continue;
              const key = String(event.payload.connection_id);
              const target = next[key] ||= {
                text: "",
                reasoning: "",
                seconds: 0,
              };
              target.text += String(event.payload.text || "");
              target.reasoning += String(event.payload.reasoning || "");
            }
            return next;
          });
        }
        if (!terminal(current) || batch.items.length) {
          timer = setTimeout(read, batch.items.length === 500 ? 20 : 2000);
        }
      } catch (cause) {
        if (!stopped) {
          setError(message(cause));
          timer = setTimeout(read, 5000);
        }
      }
    }
    read();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id]);
  useEffect(() => {
    if (follow && logs.current) {
      logs.current.scrollTop = logs.current.scrollHeight;
    }
  }, [events, follow]);
  async function command(action: string) {
    setBusy(true);
    try {
      const value = await api<Job>(`/jobs/${id}/${action}`, "POST");
      if (action === "retries") location.assign(`/jobs/${value.id}`);
      else setJob(value);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  if (!job) {
    return error
      ? <Notice error>{error}</Notice>
      : <p role="status" class="loading-state">Loading job…</p>;
  }
  const phase = events.findLast((e) => e.kind === "phase");
  const progress = events.findLast((e) =>
    ["phase", "log", "metrics", "episode", "delta"].includes(e.kind)
  );
  const title = job.status === "queued"
    ? "Waiting for a capable worker"
    : job.cancel_requested
    ? "Stopping execution"
    : String(phase?.payload.phase || job.status).replaceAll("_", " ");
  const completed = job.result?.episodes ||
    events.filter((e) => e.kind === "episode").map((e) => e.payload as Episode);
  const messages = { ...outputs, ...job.result?.outputs };
  const metrics = events.filter((e) => e.kind === "metrics");
  const metricKeys = [
    ...new Set(metrics.flatMap((e) => Object.keys(e.payload))),
  ].filter((k) =>
    !["step", "total", "epoch"].includes(k) &&
    metrics.some((e) => typeof e.payload[k] === "number")
  );
  const resources = events.findLast((e) => e.kind === "resource")?.payload;
  return (
    <div class={`job-monitor ${compact ? "compact-monitor" : ""}`}>
      {!compact && (
        <div class="page-heading">
          <div>
            <a class="back-link" href="/results">← Results</a>
            <h1>{job.name}</h1>
            <span class="muted">
              {job.kind.replaceAll("_", " ")} · {id.slice(0, 12)} ·{" "}
              {date(job.created_at)}
            </span>
          </div>
          <div class="inline-actions">
            <Status job={job} />
            {terminal(job) && job.kind !== "chat" && (
              <button
                type="button"
                class="button secondary"
                disabled={busy}
                onClick={() => command("retries")}
              >
                Run again
              </button>
            )}
          </div>
        </div>
      )}
      {error && <Notice error>{error}</Notice>}
      {!terminal(job)
        ? (
          <ActivityStatus
            now={now}
            title={title}
            startedAt={(job.started_at || job.created_at) * 1000}
            queued={job.status === "queued"}
            contact={job.status !== "queued"
              ? {
                label: "Worker heartbeat",
                at: job.heartbeat_at ? job.heartbeat_at * 1000 : null,
              }
              : undefined}
            progress={progress
              ? { label: "Last activity", at: progress.at * 1000 }
              : undefined}
            disconnected={!!error ||
              (job.status !== "queued" && !job.worker_connected)}
            staleAfter={30}
            quietAfter={60}
            quietMessage="The worker is responding, but has reported no recent progress. Inspect the logs or stop the job if needed."
            note={job.status === "queued"
              ? "You can leave this page. This job is stored on the server."
              : typeof phase?.payload.task === "string"
              ? `Task: ${phase.payload.task}`
              : undefined}
            actions={
              <button
                type="button"
                class="button secondary"
                disabled={busy || job.cancel_requested}
                onClick={() => command("cancel")}
              >
                {job.cancel_requested ? "Stop requested" : "Stop"}
              </button>
            }
            compact={compact}
          />
        )
        : compact && (
          <div class="chat-job-state">
            <Status job={job} />
            <a href={`/jobs/${id}`}>Run details</a>
          </div>
        )}
      {job.error && <Notice error>{job.error}</Notice>}
      {job.kind === "chat" && (
        <div
          class={`chat-outputs ${
            Object.keys(messages).length > 1 ? "two" : ""
          }`}
        >
          {Object.entries(messages).map(([key, value]) => (
            <div class="model-message" key={key}>
              <div class="split-line">
                <strong>{connectionNames[key] || key.slice(0, 12)}</strong>
                {!!value.seconds && (
                  <small>
                    {metric(value.seconds, 1)}s ·{" "}
                    {value.usage?.completion_tokens ?? "—"} tokens
                  </small>
                )}
              </div>
              {value.reasoning && (
                <details>
                  <summary>Reasoning</summary>
                  <pre class="message-text">{value.reasoning}</pre>
                </details>
              )}
              <pre class="message-text">{value.text || "Waiting for response…"}</pre>
              {value.tool_calls?.length
                ? (
                  <details>
                    <summary>Tool calls (not executed in chat)</summary>
                    <pre class="json-view">{JSON.stringify(value.tool_calls, null, 2)}</pre>
                  </details>
                )
                : null}
              <button
                type="button"
                class="text-button"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(value.text);
                  } catch {
                    setError(
                      "Copy failed. Select the response text to copy it.",
                    );
                  }
                }}
              >
                Copy response
              </button>
            </div>
          ))}
        </div>
      )}
      {!compact && (
        <>
          {job.result?.connection_id && !terminal(job) && (
            <div class="panel inline-actions">
              <a class="button primary" href="/inference">Open chat</a>
              <a
                class="button secondary"
                href={`/benchmark?connection=${job.result.connection_id}`}
              >
                Benchmark this model
              </a>
            </div>
          )}
          {(job.result?.mean_reward !== undefined || completed.length > 0) && (
            <section class="panel summary-strip">
              <div>
                <small>Mean scored reward</small>
                <strong>{metric(job.result?.mean_reward)}</strong>
              </div>
              <div>
                <small>Solve rate</small>
                <strong>
                  {job.result?.solve_rate == null
                    ? "—"
                    : metric(job.result.solve_rate * 100, 1) + "%"}
                </strong>
              </div>
              <div>
                <small>Completed episodes</small>
                <strong>{completed.length}</strong>
              </div>
              <div>
                <small>Execution errors</small>
                <strong>{completed.filter((e) => e.error).length}</strong>
              </div>
            </section>
          )}
          {metrics.length > 0 && (
            <section class="panel">
              <div class="panel-heading">
                <h2>Training metrics</h2>
                <span class="muted">
                  Step {String(metrics.at(-1)?.payload.step ?? "—")} /{" "}
                  {String(metrics.at(-1)?.payload.total ?? "—")}
                </span>
              </div>
              <div class="metric-charts">
                {metricKeys.map((key) => (
                  <MetricChart
                    key={key}
                    label={key}
                    points={metrics.map((e) => ({
                      x: Number(e.payload.step),
                      y: Number(e.payload[key]),
                    })).filter((p) =>
                      Number.isFinite(p.x) && Number.isFinite(p.y)
                    )}
                  />
                ))}
              </div>
            </section>
          )}
          {resources && (
            <section class="panel resource-values">
              <span>
                Worker CPU <strong>{metric(resources.cpu_percent, 0)}%</strong>
              </span>
              <span>
                RAM{" "}
                <strong>
                  {bytes(resources.ram_used)} / {bytes(resources.ram_total)}
                </strong>
              </span>
              <span class="muted">
                Last recorded sample{terminal(job) || !job.worker_connected
                  ? " · historical"
                  : ""}
              </span>
            </section>
          )}
          {completed.length > 0 && (
            <section class="panel">
              <div class="panel-heading">
                <h2>Episodes</h2>
                <span class="muted">{job.config.protocol}</span>
              </div>
              {completed.map((episode, index) => (
                <EpisodeDetails
                  key={index}
                  episode={episode}
                  artifactId={job.result?.artifact_id}
                />
              ))}
            </section>
          )}
          <section class="panel">
            <div class="panel-heading">
              <h2>Activity & logs</h2>
              <a href={`/console?job=${encodeURIComponent(id)}`}>
                Open console →
              </a>
              <label class="check-field">
                <input
                  type="checkbox"
                  checked={follow}
                  onChange={(e) => setFollow(e.currentTarget.checked)}
                />{" "}
                Follow
              </label>
            </div>
            <pre
              class="log-view"
              ref={logs}
              tabIndex={0}
              aria-label="Execution logs"
            >{events.filter((e) => !["resource", "delta"].includes(e.kind)).slice(-1000).map((e) => `${new Date(e.at * 1000).toLocaleTimeString()}  ${e.kind === "log" ? String(e.payload.text || "") : e.kind + " " + JSON.stringify(e.payload)}`).join("\n") || "No execution events yet."}</pre>
            <small class="log-caption">
              Latest 1,000 events shown. Full events remain available through
              the API and pg-gym jobs logs.
            </small>
          </section>
          <Artifacts jobId={id} />
          <section class="panel">
            <details>
              <summary>Recorded configuration</summary>
              <pre class="json-view">{JSON.stringify(job.config, null, 2)}</pre>
              {job.parent_id && (
                <a href={`/jobs/${job.parent_id}`}>Previous attempt</a>
              )}
            </details>
          </section>
        </>
      )}
    </div>
  );
}

function MetricChart(
  { label, points }: { label: string; points: { x: number; y: number }[] },
) {
  if (!points.length) return null;
  const low = Math.min(...points.map((p) => p.y)),
    high = Math.max(...points.map((p) => p.y));
  const minX = points[0].x, maxX = points.at(-1)!.x;
  const line = points.map((p) =>
    `${12 + (p.x - minX) / (maxX - minX || 1) * 276},${
      78 - (p.y - low) / (high - low || 1) * 64
    }`
  ).join(" ");
  return (
    <figure class="metric-chart">
      <figcaption>
        <span>{label}</span>
        <strong>{metric(points.at(-1)?.y, 4)}</strong>
      </figcaption>
      <svg
        viewBox="0 0 300 90"
        role="img"
        aria-label={`${label}, ${points.length} samples, minimum ${low}, maximum ${high}`}
      >
        <line x1="12" y1="80" x2="288" y2="80" stroke="var(--line)" />
        <polyline
          points={line}
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        />
      </svg>
      <small>Steps {minX}–{maxX} · {metric(low, 4)}–{metric(high, 4)}</small>
    </figure>
  );
}

function EpisodeDetails(
  { episode, artifactId }: { episode: Episode; artifactId?: string },
) {
  const [data, setData] = useState<Record<string, unknown> | null>(null),
    [error, setError] = useState("");
  async function load() {
    if (data || !artifactId || !episode.file) return;
    try {
      setData(
        await api<Record<string, unknown>>(
          `/artifacts/${artifactId}/files/${encodeURIComponent(episode.file)}`,
        ),
      );
    } catch (cause) {
      setError(message(cause));
    }
  }
  const record = data?.record as Record<string, unknown> | undefined;
  const diff = record?.diff || record?.patch || data?.patch;
  return (
    <details
      class="episode-detail"
      onToggle={(e) => {
        if (e.currentTarget.open) load();
      }}
    >
      <summary>
        <span>{episode.task}</span>
        <span class="episode-outcome">
          {episode.error
            ? "Execution error"
            : episode.passed
            ? "Solved"
            : "Unsolved"} · {metric(episode.reward)}
        </span>
      </summary>
      <div class="episode-content">
        {episode.error && <Notice error>{episode.error}</Notice>}
        {error && <Notice error>{error}</Notice>}
        {typeof data?.prompt === "string" && (
          <>
            <p class="task-prompt">{data.prompt}</p>
            <div class="inline-actions">
              <button
                type="button"
                class="button secondary"
                onClick={() => {
                  sessionStorage.setItem("pg-task-prompt", String(data.prompt));
                  location.assign("/inference");
                }}
              >
                Open in Inference
              </button>
            </div>
          </>
        )}
        {typeof diff === "string" && <DiffView diff={diff} />}
        {data && (
          <details>
            <summary>Full episode record</summary>
            <pre class="json-view">{JSON.stringify(data, null, 2)}</pre>
          </details>
        )}
        {artifactId && episode.file
          ? (
            <a
              href={`/api/v1/artifacts/${artifactId}/files/${
                encodeURIComponent(episode.file)
              }`}
              download
            >
              Download episode JSON
            </a>
          )
          : (
            <p class="muted">
              Detailed files are published when the job finishes.
            </p>
          )}
      </div>
    </details>
  );
}

function Artifacts({ jobId }: { jobId: string }) {
  const [items, setItems] = useState<Artifact[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const data = await api<Artifact[]>("/artifacts");
        if (!stopped) {
          setItems(data.filter((a) => a.job_id === jobId));
          setError("");
        }
      } catch (cause) {
        if (!stopped) setError(message(cause));
      }
      if (!stopped) timer = setTimeout(read, 10000);
    }
    read();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [jobId]);
  return (
    <section class="panel">
      <div class="panel-heading">
        <h2>Artifacts</h2>
      </div>
      {error && <Notice error>{error}</Notice>}
      {!items.length && <Empty>No files published yet.</Empty>}
      {items.map((a) => (
        <details class="artifact-detail" key={a.id}>
          <summary>
            {a.name} <small>{a.kind} · {a.status}</small>
          </summary>
          {a.kind === "adapter" && (
            <div class="inline-actions">
              <a class="button secondary" href={`/inference?artifact=${a.id}`}>
                Open in Inference
              </a>
              <a
                class="button secondary"
                href={`/rl?artifact=${a.id}&mode=evaluate`}
              >
                Evaluate
              </a>
            </div>
          )}
          <pre class="json-view">{JSON.stringify({id: a.id, ...a.metadata}, null, 2)}</pre>
          {a.files.map((f) => (
            <div class="artifact-file" key={f.path}>
              <a
                href={`/api/v1/artifacts/${a.id}/files/${
                  f.path.split("/").map(encodeURIComponent).join("/")
                }`}
                download
              >
                {f.path}
              </a>
              <span>{(f.size / 1024 ** 2).toFixed(2)} MB</span>
              <code title={f.sha256}>{f.sha256.slice(0, 16)}…</code>
            </div>
          ))}
        </details>
      ))}
    </section>
  );
}

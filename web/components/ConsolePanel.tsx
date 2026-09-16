import { useEffect, useRef, useState } from "preact/hooks";
import { api, message, terminal } from "@/lib/platform.ts";
import type { Event, Job } from "@/lib/platform.ts";
import { Field, Notice, Status } from "./PlatformUI.tsx";
import { Icon } from "./Icon.tsx";

export function ConsolePanel(
  { jobs, next }: { jobs: Job[]; next: string | null },
) {
  const [selected, setSelected] = useState(
    typeof location === "undefined"
      ? ""
      : new URLSearchParams(location.search).get("job") || "",
  );
  const [older, setOlder] = useState<Job[]>([]);
  const [cursor, setCursor] = useState(next);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!older.length) setCursor(next);
  }, [next, older.length]);
  const combined = [
    ...jobs,
    ...older.filter((j) => !jobs.some((recent) => recent.id === j.id)),
  ];
  const id = selected || combined.find((j) => !terminal(j))?.id ||
    combined[0]?.id || "";
  useEffect(() => {
    if (!selected && id) setSelected(id);
  }, [selected, id]);
  return (
    <section class="panel console-panel">
      <div class="panel-heading">
        <div>
          <h2>Execution console</h2>
          <p class="muted">Follow logs and events from your runs.</p>
        </div>
        <span class="status-chip">Read only</span>
      </div>
      <div class="console-picker">
        <Field label="Job">
          <select
            value={id}
            onChange={(e) => {
              const value = e.currentTarget.value;
              setSelected(value);
              const url = new URL(location.href);
              url.searchParams.set("job", value);
              history.replaceState(null, "", url);
            }}
          >
            {!combined.length && !id && <option value="">No jobs yet</option>}
            {id && !combined.some((j) => j.id === id) && (
              <option value={id}>{id}</option>
            )}
            {combined.map((j) => (
              <option key={j.id} value={j.id}>
                {j.name} · {j.status} · {j.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </Field>
        {cursor && (
          <button
            type="button"
            class="button secondary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const batch = await api<{ items: Job[]; next: string | null }>(
                  `/jobs?before=${encodeURIComponent(cursor)}`,
                );
                setOlder((old) => [...old, ...batch.items]);
                setCursor(batch.next);
                setError("");
              } catch (cause) {
                setError(message(cause));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Loading…" : "Load older jobs"}
          </button>
        )}
      </div>
      {error && <Notice error>{error}</Notice>}
      {id ? <LogStream key={id} id={id} /> : (
        <div class="console-empty">
          <Icon name="terminal" size={32} />
          <h3>No execution logs yet</h3>
          <p>
            Start a run to see its activity here. You can leave this page while
            it runs.
          </p>
          <a class="button secondary" href="/benchmark">New benchmark</a>
        </div>
      )}
    </section>
  );
}

function LogStream({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [follow, setFollow] = useState(true);
  const [updated, setUpdated] = useState<number | null>(null);
  const logs = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let stopped = false, cursor = 0, timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const path = `/jobs/${encodeURIComponent(id)}`;
        const [current, batch] = await Promise.all([
          api<Job>(path),
          api<{ items: Event[]; next: number }>(
            `${path}/events?after=${cursor}`,
          ),
        ]);
        if (stopped) return;
        cursor = batch.next;
        setJob(current);
        setEvents((old) => [...old, ...batch.items].slice(-5000));
        setUpdated(Date.now());
        setError("");
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
  const visible = events.filter((event) =>
    (!kind || event.kind === kind) &&
    format(event).toLowerCase().includes(search.toLowerCase())
  );
  const text = visible.map(format).join("\n");
  useEffect(() => {
    if (follow && logs.current) {
      logs.current.scrollTop = logs.current.scrollHeight;
    }
  }, [text, follow]);
  return (
    <>
      <div class="console-meta">
        <div class="inline-actions">
          {job && <Status job={job} />}
          <span class="muted">
            {updated
              ? `Last checked ${new Date(updated).toLocaleTimeString()}`
              : "Connecting…"}
          </span>
        </div>
        <a href={`/jobs/${encodeURIComponent(id)}`}>Run details →</a>
      </div>
      {error && <Notice error>{error} Reconnecting…</Notice>}
      <div class="console-toolbar">
        <Field label="Search logs">
          <input
            type="search"
            placeholder="Find text in loaded events"
            value={search}
            onInput={(e) => setSearch(e.currentTarget.value)}
          />
        </Field>
        <Field label="Event type">
          <select value={kind} onChange={(e) => setKind(e.currentTarget.value)}>
            <option value="">All events</option>
            {[...new Set(events.map((event) => event.kind))].sort().map((
              value,
            ) => <option key={value}>{value}</option>)}
          </select>
        </Field>
        <label class="check-field">
          <input
            type="checkbox"
            checked={follow}
            onChange={(e) => setFollow(e.currentTarget.checked)}
          />{" "}
          Auto-scroll
        </label>
        <button
          type="button"
          class="button secondary"
          disabled={!visible.length}
          onClick={() => {
            const url = URL.createObjectURL(
              new Blob([text + "\n"], { type: "text/plain;charset=utf-8" }),
            );
            const link = document.createElement("a");
            link.href = url;
            link.download = `job-${id.replace(/[^a-zA-Z0-9_-]/g, "_")}.log`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }}
        >
          <Icon name="download" size={16} /> Download view
        </button>
      </div>
      <pre
        class="log-view console-output"
        ref={logs}
        tabIndex={0}
        aria-label="Execution logs"
      >{text || (events.length ? "No events match your filters." : job?.status === "queued" ? "Waiting for a capable worker. Execution logs will appear when the job starts." : "No execution events yet.")}</pre>
      <small class="log-caption">
        {visible.length} matching / {events.length}{" "}
        loaded events. Latest 5,000 retained in this view. Full history is
        available through pg-gym jobs logs.
      </small>
    </>
  );
}

function format(event: Event): string {
  return `${new Date(event.at * 1000).toLocaleString()}  [${event.kind}]  ${
    event.kind === "log"
      ? String(event.payload.text || "")
      : JSON.stringify(event.payload)
  }`;
}

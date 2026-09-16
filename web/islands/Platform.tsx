import { useEffect, useState } from "preact/hooks";
import { api, message, metric, terminal } from "@/lib/platform.ts";
import type {
  Artifact,
  Connection,
  Job,
  Suite,
  Worker,
} from "@/lib/platform.ts";
import { ConsolePanel } from "@/components/ConsolePanel.tsx";
import { WorkspacePanel } from "@/components/WorkspacePanel.tsx";
import { BenchmarkPanel } from "@/components/BenchmarkPanel.tsx";
import type { Profile } from "@/components/BenchmarkPanel.tsx";
import { TrainingPanel } from "@/components/TrainingPanel.tsx";
import { InferencePanel } from "@/components/InferencePanel.tsx";
import { SettingsPanel } from "@/components/SettingsPanel.tsx";
import { JobMonitor } from "@/components/JobMonitor.tsx";
import {
  Field,
  JobTable,
  Notice,
  Resources,
} from "@/components/PlatformUI.tsx";

type Data = {
  suites: Suite[];
  connections: Connection[];
  profiles: Profile[];
  credentials: { id: string; name: string }[];
  artifacts: Artifact[];
  workers: Worker[];
  jobs: Job[];
  next: string | null;
};
export default function Platform({ page, id }: { page: string; id?: string }) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0);
  useEffect(() => {
    if (id) return;
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const [
          suites,
          connections,
          profiles,
          credentials,
          artifacts,
          capabilities,
          jobs,
        ] = await Promise.all([
          api<Suite[]>("/suites"),
          api<Connection[]>("/connections"),
          api<Profile[]>("/harness-profiles"),
          api<{ id: string; name: string }[]>("/secrets"),
          api<Artifact[]>("/artifacts"),
          api<{ workers: Worker[] }>("/capabilities"),
          api<{ items: Job[]; next: string | null }>("/jobs"),
        ]);
        if (!stopped) {
          setData({
            suites,
            connections,
            profiles,
            credentials,
            artifacts,
            workers: capabilities.workers,
            jobs: jobs.items,
            next: jobs.next,
          });
          setError("");
        }
      } catch (cause) {
        if (!stopped) setError(message(cause));
      } finally {
        if (!stopped) timer = setTimeout(refresh, 5000);
      }
    }
    refresh();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id, revision]);
  if (id) {
    return (
      <main id="main-content" class="wrap platform">
        <JobMonitor id={id} />
      </main>
    );
  }
  const title = ({
    home: "Workspace",
    benchmark: "Benchmark",
    results: "Results",
    rl: "RL",
    inference: "Inference",
    settings: "Settings",
    console: "Console",
  } as Record<string, string>)[page];
  return (
    <main id="main-content" class="wrap platform">
      <div class="page-heading">
        <h1>{title}</h1>
        {page === "home" && (
          <a class="button primary" href="/benchmark">New benchmark</a>
        )}
      </div>
      {error && (
        <Notice error>
          {error}
          <button
            type="button"
            class="text-button"
            onClick={() => setRevision(revision + 1)}
          >
            Retry
          </button>
        </Notice>
      )}
      {!data && !error && (
        <p class="loading-state" role="status">Loading workspace…</p>
      )}
      {data && (
        <>
          {page === "benchmark" && (
            <BenchmarkPanel
              suites={data.suites}
              connections={data.connections}
              profiles={data.profiles}
            />
          )}
          {page === "home" && <WorkspacePanel {...data} />}
          {page === "console" && (
            <ConsolePanel jobs={data.jobs} next={data.next} />
          )}
          {page === "results" && <Results jobs={data.jobs} next={data.next} />}
          {page === "rl" && (
            <>
              <TrainingPanel artifacts={data.artifacts} suites={data.suites} />
              <Resources workers={data.workers} />
              <section class="panel">
                <div class="panel-heading">
                  <h2>Training & evaluation history</h2>
                  <a href="/results">View all</a>
                </div>
                <JobTable
                  jobs={data.jobs.filter((j) =>
                    ["training", "evaluation"].includes(j.kind)
                  )}
                />
              </section>
            </>
          )}
          {page === "inference" && (
            <InferencePanel
              artifacts={data.artifacts}
              connections={data.connections}
              jobs={data.jobs}
              credentials={data.credentials}
            />
          )}
          {page === "settings" && (
            <>
              <SettingsPanel
                connections={data.connections}
                profiles={data.profiles}
                credentials={data.credentials}
                refresh={() => setRevision(revision + 1)}
              />
              <div id="workers">
                <Resources workers={data.workers} />
              </div>
            </>
          )}
        </>
      )}
    </main>
  );
}

function Results({ jobs, next }: { jobs: Job[]; next: string | null }) {
  const [kind, setKind] = useState(""),
    [status, setStatus] = useState(""),
    [search, setSearch] = useState(""),
    [older, setOlder] = useState<Job[]>([]),
    [cursor, setCursor] = useState(next),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [compare, setCompare] = useState<Job[]>([]);
  useEffect(() => {
    if (!older.length) setCursor(next);
  }, [next, older.length]);
  useEffect(() => {
    const ids = new URLSearchParams(location.search).get("compare")?.split(",")
      .slice(0, 4);
    if (ids?.length) {
      Promise.all(ids.map((id) => api<Job>("/jobs/" + encodeURIComponent(id))))
        .then(setCompare).catch((cause) => setError(message(cause)));
    }
  }, []);
  const combined = [
    ...jobs,
    ...older.filter((item) => !jobs.some((j) => item.id === j.id)),
  ];
  const filtered = combined.filter((j) =>
    (!kind || kind === j.kind) && (!status || status === j.status) &&
    `${j.id} ${j.name} ${j.config.suite || ""} ${
      j.config.connection?.model || ""
    }`.toLowerCase().includes(search.toLowerCase())
  );
  const comparable = compare.length > 1 &&
    compare.every((j) =>
      j.config.protocol === compare[0].config.protocol &&
      j.config.suite === compare[0].config.suite &&
      JSON.stringify(j.config.task_hashes) ===
        JSON.stringify(compare[0].config.task_hashes) &&
      j.config.split === compare[0].config.split && terminal(j)
    );
  return (
    <>
      {compare.length > 0 && (
        <section class="panel">
          <div class="panel-heading">
            <h2>Comparison</h2>
            <a href="/results">Close</a>
          </div>
          {!comparable && (
            <Notice>
              These runs have different task sets, protocols, splits, or
              unfinished results. Their aggregate rewards are not directly
              comparable.
            </Notice>
          )}
          <JobTable jobs={compare} />
          <div class="comparison-grid">
            {compare.map((j) => (
              <div key={j.id}>
                <h3>{j.name}</h3>
                <dl>
                  <dt>Protocol</dt>
                  <dd>{j.config.protocol || "—"}</dd>
                  <dt>Split</dt>
                  <dd>{String(j.config.split || "All")}</dd>
                  <dt>Solve rate</dt>
                  <dd>
                    {j.result?.solve_rate == null
                      ? "—"
                      : metric(j.result.solve_rate * 100) + "%"}
                  </dd>
                  <dt>Execution errors</dt>
                  <dd>{String(j.result?.execution_errors ?? "—")}</dd>
                </dl>
                <details>
                  <summary>Configuration</summary>
                  <pre class="json-view">{JSON.stringify(j.config, null, 2)}</pre>
                </details>
              </div>
            ))}
          </div>
        </section>
      )}
      <section class="panel">
        <div class="fields three result-filters">
          <Field label="Search">
            <input
              type="search"
              placeholder="Name, model, suite or ID"
              value={search}
              onInput={(e) => setSearch(e.currentTarget.value)}
            />
          </Field>
          <Field label="Type">
            <select
              value={kind}
              onChange={(e) => setKind(e.currentTarget.value)}
            >
              <option value="">All types</option>
              {[
                "benchmark",
                "training",
                "evaluation",
                "deployment",
                "model_import",
                "chat",
              ].map((k) => <option key={k}>{k}</option>)}
            </select>
          </Field>
          <Field label="Status">
            <select
              value={status}
              onChange={(e) => setStatus(e.currentTarget.value)}
            >
              <option value="">All statuses</option>
              {[
                "queued",
                "preparing",
                "running",
                "cancelling",
                "succeeded",
                "failed",
                "cancelled",
              ].map((s) => <option key={s}>{s}</option>)}
            </select>
          </Field>
        </div>
        {error && <Notice error>{error}</Notice>}
        <JobTable jobs={filtered} compare />
        {cursor !== null && (
          <div class="panel-footer">
            <small>Filters apply to {combined.length} loaded jobs.</small>
            <button
              type="button"
              class="button secondary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const value = await api<
                    { items: Job[]; next: string | null }
                  >(`/jobs?before=${cursor}`);
                  setOlder([...older, ...value.items]);
                  setCursor(value.next);
                } catch (cause) {
                  setError(message(cause));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Loading…" : "Load older jobs"}
            </button>
          </div>
        )}
      </section>
    </>
  );
}

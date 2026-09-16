import { useEffect, useState } from "preact/hooks";
import { api, message, metric, terminal } from "@/lib/platform.ts";
import type { Job } from "@/lib/platform.ts";
import { Field, JobTable, Notice } from "./PlatformUI.tsx";
export function ResultsPanel(
  { jobs, next }: { jobs: Job[]; next: string | null },
) {
  const [category, setCategory] = useState("experiments"),
    [initialized, setInitialized] = useState(false);
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
    const query = new URLSearchParams(location.search);
    setCategory(query.get("category") || "experiments");
    setKind(query.get("kind") || "");
    setStatus(query.get("status") || "");
    setSearch(query.get("q") || "");
    setInitialized(true);
    const ids = query.get("compare")?.split(",")
      .slice(0, 4);
    if (ids?.length) {
      Promise.all(ids.map((id) => api<Job>("/jobs/" + encodeURIComponent(id))))
        .then(setCompare).catch((cause) => setError(message(cause)));
    }
  }, []);
  useEffect(() => {
    if (!initialized) return;
    const url = new URL(location.href);
    for (
      const [key, value] of Object.entries({
        category,
        kind,
        status,
        q: search,
      })
    ) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState({}, "", url);
  }, [category, kind, status, search, initialized]);
  const categories: Record<string, string[]> = {
    experiments: ["benchmark", "training", "evaluation"],
    models: ["model_import", "deployment"],
    chats: ["chat"],
  };
  const combined = [
    ...jobs,
    ...older.filter((item) => !jobs.some((j) => item.id === j.id)),
  ];
  const filtered = combined.filter((j) =>
    (!categories[category] || categories[category].includes(j.kind)) &&
    (!kind || kind === j.kind) && (!status || status === j.status) &&
    `${j.id} ${j.name} ${j.config.suite || ""} ${
      j.config.connection?.model || ""
    }`.toLowerCase().includes(search.toLowerCase())
  );
  const hashes = (job: Job) =>
    job.config.task_hashes && typeof job.config.task_hashes === "object"
      ? JSON.stringify(
        Object.entries(job.config.task_hashes).sort(([a], [b]) =>
          a.localeCompare(b)
        ),
      )
      : null;
  const comparable = compare.length > 1 &&
    compare.every((job) =>
      ["benchmark", "evaluation"].includes(job.kind) &&
      job.kind === compare[0].kind &&
      !!job.config.protocol &&
      job.config.protocol === compare[0].config.protocol &&
      job.config.suite === compare[0].config.suite && hashes(job) !== null &&
      hashes(job) === hashes(compare[0]) &&
      job.config.split === compare[0].config.split && terminal(job) &&
      job.status === "succeeded" &&
      !job.result?.execution_errors && job.result?.mean_reward != null
    );
  return (
    <>
      <div class="page-tabs" role="group" aria-label="Run category">
        {[["experiments", "Experiments"], ["models", "Models & servers"], [
          "chats",
          "Chats",
        ], ["all", "All activity"]].map(([value, label]) => (
          <button
            key={value}
            type="button"
            class={category === value ? "selected" : ""}
            aria-pressed={category === value}
            onClick={() => {
              setCategory(value);
              setKind("");
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {compare.length > 0 && (
        <section class="panel">
          <div class="panel-heading">
            <h2>Comparison</h2>
            <a href="/results">Close</a>
          </div>
          {!comparable && (
            <Notice>
              These runs are not a complete compatible comparison: check task
              identities, protocols, splits, completion and execution errors.
              Their aggregate rewards are not directly comparable.
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
        <p class="muted">
          Search and filters cover {combined.length}{" "}
          loaded runs{cursor ? "; load older runs to extend the search" : ""}.
        </p>
        <JobTable
          jobs={filtered}
          compare={category === "experiments" || category === "all"}
        />
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
                  >(`/jobs?limit=200&before=${encodeURIComponent(cursor)}`);
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

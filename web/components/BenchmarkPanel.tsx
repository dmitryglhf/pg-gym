import { useEffect, useState } from "preact/hooks";
import { api, field, numeric } from "@/lib/platform.ts";
import type { Connection, Job, Suite } from "@/lib/platform.ts";
import { Field, Form, Notice, usePoll } from "./PlatformUI.tsx";

export type Profile = {
  id: string;
  name: string;
  harness: string;
  max_turns: number;
  timeout: number;
  temperature: number;
  context_strategy: string;
};
export function BenchmarkPanel(
  { suites, connections, profiles }: {
    suites: Suite[];
    connections: Connection[];
    profiles: Profile[];
  },
) {
  const [suite, setSuite] = useState(suites[0]?.id || ""),
    [scope, setScope] = useState("task"),
    [split, setSplit] = useState(""),
    [task, setTask] = useState(""),
    [harness, setHarness] = useState("markov"),
    [connection, setConnection] = useState(
      typeof location === "undefined"
        ? ""
        : new URLSearchParams(location.search).get("connection") || "",
    );
  const tasks = usePoll<{ name: string }[]>(
    `/suites/${encodeURIComponent(suite)}/tasks${
      split ? "?split=" + encodeURIComponent(split) : ""
    }`,
    60000,
  );
  useEffect(() => {
    if (tasks.data && !tasks.data.some((t) => t.name === task)) {
      setTask(tasks.data[0]?.name || "");
    }
  }, [tasks.data, task]);
  const preview = usePoll<{ prompt: string; task_hash: string }>(
    task
      ? `/suites/${encodeURIComponent(suite)}/tasks/${encodeURIComponent(task)}`
      : "/me",
    60000,
  );
  const available = suites.find((s) => s.id === suite);
  return (
    <div class="main-grid">
      <section class="panel">
        <div class="panel-heading">
          <h2>New benchmark</h2>
        </div>
        <Form
          submit="Run benchmark"
          disabled={!connections.some((c) => c.tools) || !tasks.data?.length}
          onSubmit={async (data) => {
            const job = await api<Job>("/benchmarks", "POST", {
              name: field(data, "name") || `${suite} · ${harness}`,
              suite,
              tasks: scope === "task" ? [task] : [],
              split: split || null,
              harness,
              connection_id: field(data, "connection_id"),
              profile_id: field(data, "profile_id") || null,
              timeout: numeric(data, "timeout"),
              max_turns: numeric(data, "max_turns"),
            });
            location.assign(`/jobs/${job.id}`);
          }}
        >
          <div class="scope-control" role="group" aria-label="Run scope">
            {[["task", "Single task"], ["suite", "Suite / split"]].map((
              [value, label],
            ) => (
              <button
                key={value}
                type="button"
                class={`button ${scope === value ? "primary" : "secondary"}`}
                aria-pressed={scope === value}
                onClick={() => setScope(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div class="fields three">
            <Field label="Suite">
              <select
                value={suite}
                onChange={(e) => {
                  setSuite(e.currentTarget.value);
                  setTask("");
                  setSplit("");
                }}
              >
                {suites.map((s) => (
                  <option key={s.id} value={s.id}>{s.id}</option>
                ))}
              </select>
            </Field>
            <Field label="Split">
              <select
                value={split}
                onChange={(e) => {
                  setSplit(e.currentTarget.value);
                  setTask("");
                }}
              >
                <option value="">All runnable tasks</option>
                {available?.splits.map((s) => <option key={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="Task">
              <select
                value={task}
                disabled={scope !== "task" || !tasks.data}
                onChange={(e) => setTask(e.currentTarget.value)}
              >
                {tasks.data?.map((t) => <option key={t.name}>{t.name}</option>)}
              </select>
            </Field>
          </div>
          <div class="fields two">
            <Field label="Harness">
              <select
                value={harness}
                onChange={(e) => setHarness(e.currentTarget.value)}
              >
                <option value="markov">Markov</option>
                <option value="opencode">OpenCode</option>
              </select>
            </Field>
            <Field label="Model connection">
              <select
                name="connection_id"
                required
                value={connection}
                onChange={(e) => setConnection(e.currentTarget.value)}
              >
                <option value="">Select a connection</option>
                {connections.filter((c) => c.tools).map((c) => (
                  <option value={c.id} key={c.id}>{c.name} · {c.model}</option>
                ))}
              </select>
            </Field>
          </div>
          {!connections.length && (
            <Notice>
              <a href="/settings">Add a model connection</a>{" "}
              or deploy a model in Inference.
            </Notice>
          )}
          <details class="advanced">
            <summary>Configuration</summary>
            <div class="fields two">
              <Field label="Run name">
                <input
                  name="name"
                  maxLength={100}
                  placeholder={`${suite} · ${harness}`}
                />
              </Field>
              <Field
                label="Harness profile"
                hint="A saved profile overrides the limits below."
              >
                <select name="profile_id" key={harness}>
                  <option value="">Custom limits</option>
                  {profiles.filter((p) => p.harness === harness).map((p) => (
                    <option value={p.id} key={p.id}>{p.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Agent timeout (seconds)">
                <input
                  type="number"
                  name="timeout"
                  min={30}
                  max={86400}
                  defaultValue={1800}
                  required
                />
              </Field>
              <Field label="Maximum turns">
                <input
                  type="number"
                  name="max_turns"
                  min={1}
                  max={1000}
                  defaultValue={50}
                  required
                />
              </Field>
            </div>
          </details>
          <p class="muted selection-count">
            {scope === "task"
              ? "1 episode"
              : `${tasks.data?.length || 0} episodes`} selected
          </p>
          {tasks.error && <Notice error>{tasks.error}</Notice>}
        </Form>
      </section>
      <aside class="panel task-preview">
        <small>{suite}</small>
        <h2>{scope === "task" ? task : split || "All runnable tasks"}</h2>
        {scope === "task"
          ? (
            <>
              <p class="task-prompt">{preview.data?.prompt}</p>
              <details>
                <summary>Task identity</summary>
                <code class="break-all">{preview.data?.task_hash}</code>
              </details>
            </>
          )
          : (
            <p>
              {tasks.data?.length || 0}{" "}
              tasks will run sequentially in disposable containers.
            </p>
          )}
        <div class="metadata-line">
          <span>Protocol</span>
          <span>Agentic benchmark</span>
        </div>
        <p class="muted">
          The harness uses the selected model to edit PostgreSQL and run tools.
          Results include execution errors separately from scored rewards.
        </p>
      </aside>
    </div>
  );
}

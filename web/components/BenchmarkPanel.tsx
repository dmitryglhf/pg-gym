import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "@/lib/platform.ts";
import type { Connection, Job, Suite, Worker } from "@/lib/platform.ts";
import { useResource } from "@/lib/query.ts";
import { connectionStatus, readiness } from "@/lib/readiness.ts";
import { preparationHref, useDraft } from "@/lib/workspace.ts";
import { Field, Form, Notice } from "./PlatformUI.tsx";
import { OperationCard } from "./OperationCard.tsx";
import { ProfilesPanel } from "./ProfilesPanel.tsx";

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
  { suites, connections, profiles, deployments, workers, jobs, refresh }: {
    suites: Suite[];
    connections: Connection[];
    profiles: Profile[];
    deployments: Job[];
    workers: Worker[];
    jobs: Job[];
    refresh: () => void;
  },
) {
  const [draft, setDraft, restored] = useDraft("benchmark", {
    suite: suites[0]?.id || "",
    scope: "task",
    copiedTasks: [] as string[],
    split: "",
    task: "",
    harness: "markov",
    connection: "",
    profile: "",
    name: "",
    timeout: 1800,
    turns: 50,
  });
  const [pending, setPending] = useDraft("benchmark-pending", "");
  const [cloneError, setCloneError] = useState(""),
    [cloning, setCloning] = useState(false);
  const initialized = useRef(false);
  useEffect(() => {
    if (!restored || initialized.current) return;
    initialized.current = true;
    const query = new URLSearchParams(location.search);
    const connection = query.get("connection"), clone = query.get("clone");
    if (connection) setDraft((old) => ({ ...old, connection }));
    query.delete("connection");
    history.replaceState(
      {},
      "",
      "/benchmark" + (query.size ? "?" + query : ""),
    );
    let mounted = true;
    if (clone) {
      setCloning(true);
      api<Job>("/jobs/" + encodeURIComponent(clone)).then((job) => {
        if (!mounted) return;
        if (job.kind !== "benchmark") {
          throw new Error("This run is not a benchmark.");
        }
        const c = job.config, profile = c.profile as Profile | undefined;
        setDraft({
          suite: c.suite || "",
          scope: c.tasks?.length === 1 ? "task" : "copied",
          copiedTasks: c.tasks || [],
          split: String(c.split || ""),
          task: c.tasks?.[0] || "",
          harness: c.harness || "markov",
          connection: String(c.connection_id || ""),
          profile: "",
          name: (job.name + " · copy").slice(0, 100),
          timeout: profile?.timeout || Number(c.timeout || 1800),
          turns: profile?.max_turns || Number(c.max_turns || 50),
        });
        setCloneError(
          "Copied the saved task set and limits. Task contents are resolved again at submission; identities remain visible in the run. If the source used a profile, choose it to restore temperature and context strategy.",
        );
        query.delete("clone");
        history.replaceState(
          {},
          "",
          "/benchmark" + (query.size ? "?" + query : ""),
        );
      }).catch((cause) => {
        if (mounted) setCloneError(String(cause));
      }).finally(() => {
        if (mounted) setCloning(false);
      });
    }
    return () => {
      mounted = false;
    };
  }, [restored]);
  const tasks = useResource<{ name: string }[]>(
    draft.suite
      ? `/suites/${encodeURIComponent(draft.suite)}/tasks${
        draft.split ? "?split=" + encodeURIComponent(draft.split) : ""
      }`
      : null,
    60000,
  );
  const preview = useResource<{ prompt: string; task_hash: string }>(
    draft.suite && draft.task
      ? `/suites/${encodeURIComponent(draft.suite)}/tasks/${
        encodeURIComponent(draft.task)
      }`
      : null,
    60000,
  );
  const available = suites.find((suite) => suite.id === draft.suite);
  const connection = connections.find((item) => item.id === draft.connection);
  const modelReady = connection && connection.tools &&
    connectionStatus(connection, deployments).usable;
  const worker = readiness("benchmark", workers, jobs);
  const validTasks = !!tasks.data?.length &&
    (draft.scope === "suite"
      ? true
      : draft.scope === "copied"
      ? draft.copiedTasks.length > 0 && draft.copiedTasks.every((name) =>
        tasks.data!.some((item) => item.name === name)
      )
      : tasks.data.some((task) => task.name === draft.task));
  const profile = profiles.find((item) =>
    item.id === draft.profile && item.harness === draft.harness
  );
  return (
    <div class="workspace-sections">
      {pending && <OperationCard id={pending} />}
      <div class="main-grid">
        <section class="panel">
          <div class="panel-heading">
            <h2>New benchmark</h2>
            <a href={preparationHref("benchmark")}>Prepare a model</a>
          </div>
          {cloneError && <Notice>{cloneError}</Notice>}
          <Form
            submit="Run benchmark"
            locked={cloning}
            disabled={!restored || cloning || !modelReady ||
              !worker.available || !validTasks || (!!draft.profile && !profile)}
            onSubmit={async () => {
              const job = await api<Job>("/benchmarks", "POST", {
                name: draft.name || `${draft.suite} · ${draft.harness}`,
                suite: draft.suite,
                tasks: draft.scope === "task"
                  ? [draft.task]
                  : draft.scope === "copied"
                  ? draft.copiedTasks
                  : [],
                split: draft.split || null,
                harness: draft.harness,
                connection_id: draft.connection,
                profile_id: draft.profile || null,
                timeout: draft.timeout,
                max_turns: draft.turns,
              });
              setPending(job.id);
              refresh();
            }}
          >
            <Field label="Model connection">
              <select
                required
                value={draft.connection}
                onChange={(event) =>
                  setDraft({ ...draft, connection: event.currentTarget.value })}
              >
                <option value="">Select a model with tool calling</option>
                {connections.map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    disabled={!item.tools ||
                      !connectionStatus(item, deployments).usable}
                  >
                    {item.name} · {!item.tools
                      ? "Chat only"
                      : connectionStatus(item, deployments).label}
                  </option>
                ))}
              </select>
            </Field>
            {!modelReady && (
              <Notice>
                Benchmarking needs an available connection with tool calling.
                {" "}
                <a href={preparationHref("benchmark")}>Set one up</a>; this
                draft stays saved.
              </Notice>
            )}
            {draft.scope === "copied" && (
              <Notice>
                Original selection: {draft.copiedTasks.length}{" "}
                tasks. Selecting another scope replaces this set.
              </Notice>
            )}
            <div class="scope-control" role="group" aria-label="Run scope">
              {[["task", "Single task"], ["suite", "Suite / split"]].map((
                [value, label],
              ) => (
                <button
                  key={value}
                  type="button"
                  class={`button ${
                    draft.scope === value ? "primary" : "secondary"
                  }`}
                  aria-pressed={draft.scope === value}
                  onClick={() =>
                    setDraft({ ...draft, scope: value, copiedTasks: [] })}
                >
                  {label}
                </button>
              ))}
            </div>
            <div class="fields three">
              <Field label="Suite">
                <select
                  required
                  value={draft.suite}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      suite: event.currentTarget.value,
                      task: "",
                      split: "",
                      scope: "task",
                      copiedTasks: [],
                    })}
                >
                  <option value="">Select a suite</option>
                  {suites.map((suite) => (
                    <option key={suite.id}>{suite.id}</option>
                  ))}
                </select>
              </Field>
              <Field label="Split">
                <select
                  value={draft.split}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      split: event.currentTarget.value,
                      task: "",
                      scope: "task",
                      copiedTasks: [],
                    })}
                >
                  <option value="">All runnable tasks</option>
                  {available?.splits.map((split) => (
                    <option key={split}>{split}</option>
                  ))}
                </select>
              </Field>
              <Field label="Task">
                <select
                  value={draft.task}
                  required={draft.scope === "task"}
                  disabled={draft.scope !== "task"}
                  onChange={(event) =>
                    setDraft({ ...draft, task: event.currentTarget.value })}
                >
                  <option value="">Select a task</option>
                  {tasks.data?.map((task) => (
                    <option key={task.name}>{task.name}</option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Harness">
              <select
                value={draft.harness}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    harness: event.currentTarget.value,
                    profile: "",
                  })}
              >
                <option value="markov">Markov</option>
                <option value="opencode">OpenCode</option>
              </select>
            </Field>
            <details class="advanced">
              <summary>Run name and limits</summary>
              <div class="fields two">
                <Field label="Run name">
                  <input
                    maxLength={100}
                    value={draft.name}
                    onInput={(event) =>
                      setDraft({ ...draft, name: event.currentTarget.value })}
                    placeholder={`${draft.suite} · ${draft.harness}`}
                  />
                </Field>
                <Field label="Harness profile">
                  <select
                    value={draft.profile}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        profile: event.currentTarget.value,
                      })}
                  >
                    <option value="">Custom limits</option>
                    {profiles.filter((item) => item.harness === draft.harness)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field label="Agent timeout (seconds)">
                  <input
                    type="number"
                    min={30}
                    max={86400}
                    required
                    disabled={!!profile}
                    value={profile?.timeout ?? draft.timeout}
                    onInput={(event) =>
                      setDraft({
                        ...draft,
                        timeout: Number(event.currentTarget.value),
                      })}
                  />
                </Field>
                <Field label="Maximum turns">
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    required
                    disabled={!!profile}
                    value={profile?.max_turns ?? draft.turns}
                    onInput={(event) =>
                      setDraft({
                        ...draft,
                        turns: Number(event.currentTarget.value),
                      })}
                  />
                </Field>
              </div>
              {profile && (
                <p class="muted">
                  Profile controls these limits, temperature ({profile
                    .temperature}) and context strategy ({profile
                    .context_strategy}).
                </p>
              )}
            </details>
            <p class="muted">
              {draft.scope === "task"
                ? (draft.task ? 1 : 0)
                : draft.scope === "copied"
                ? draft.copiedTasks.length
                : tasks.data?.length || 0} episodes selected · {worker.reason}
            </p>
            {!!draft.profile && !profile && (
              <Notice error>
                The saved profile is unavailable for this harness. Choose
                another profile or custom limits.
              </Notice>
            )}
            {!validTasks && (
              <Notice>
                Select an available suite and task selection. A copied set can
                only run while all its tasks are still available.
              </Notice>
            )}
            {tasks.error && <Notice error>{tasks.error}</Notice>}
            {!worker.available && <a href="/#workers">Inspect workers</a>}
          </Form>
        </section>
        <aside class="panel task-preview">
          <small>{draft.suite}</small>
          <h2>
            {draft.scope === "task"
              ? draft.task || "Task preview"
              : draft.split || "All runnable tasks"}
          </h2>
          {draft.scope === "task"
            ? (
              <>
                <p class="task-prompt">
                  {preview.data?.prompt ||
                    "Select a task to preview its prompt."}
                </p>
                {preview.error && <Notice error>{preview.error}</Notice>}
                <details>
                  <summary>Task identity</summary>
                  <code class="break-all">
                    {preview.data?.task_hash || "—"}
                  </code>
                </details>
              </>
            )
            : (
              <p>
                {tasks.data?.length || 0}{" "}
                tasks run sequentially in disposable containers.
              </p>
            )}
          <p class="muted">
            The harness asks the model to edit PostgreSQL and execute tools.
            Execution errors are reported separately from scored rewards.
          </p>
        </aside>
      </div>
      <details class="panel" id="profiles">
        <summary>Saved harness profiles</summary>
        <ProfilesPanel profiles={profiles} refresh={refresh} />
      </details>
    </div>
  );
}

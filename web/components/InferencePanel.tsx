import { useEffect, useState } from "preact/hooks";
import { api, field, numeric, terminal } from "@/lib/platform.ts";
import type {
  Artifact,
  Connection,
  Conversation,
  Job,
} from "@/lib/platform.ts";
import {
  ArtifactSelect,
  Empty,
  Field,
  Form,
  JobTable,
  Notice,
  usePoll,
} from "./PlatformUI.tsx";
import { JobMonitor } from "./JobMonitor.tsx";

export function InferencePanel(
  { artifacts, connections, jobs, credentials }: {
    artifacts: Artifact[];
    connections: Connection[];
    jobs: Job[];
    credentials: { id: string; name: string }[];
  },
) {
  const environment = usePoll<{ names: string[] }>("/environment");
  const [tab, setTab] = useState(
    typeof location !== "undefined" &&
      new URLSearchParams(location.search).has("artifact")
      ? "servers"
      : typeof location !== "undefined" &&
          new URLSearchParams(location.search).get("tab") === "models"
      ? "models"
      : "chat",
  );
  return (
    <>
      <div class="page-tabs" role="group" aria-label="Inference view">
        {["chat", "models", "servers"].map((item) => (
          <button
            type="button"
            key={item}
            class={tab === item ? "selected" : ""}
            onClick={() => setTab(item)}
          >
            {item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      {tab === "chat" && <Chat connections={connections} />}
      {tab === "models" && (
        <>
          <section class="panel">
            <div class="panel-heading">
              <h2>Import from Hugging Face</h2>
            </div>
            <Form
              submit="Download model"
              onSubmit={async (data) => {
                const job = await api<Job>("/models/imports", "POST", {
                  repository: field(data, "repository"),
                  revision: field(data, "revision"),
                  credential_id: field(data, "credential_id").startsWith("env:")
                    ? null
                    : field(data, "credential_id") || null,
                  credential_env:
                    field(data, "credential_id").startsWith("env:")
                      ? field(data, "credential_id").slice(4)
                      : null,
                });
                location.assign(`/jobs/${job.id}`);
              }}
            >
              <div class="fields three">
                <Field label="Repository">
                  <input
                    name="repository"
                    placeholder="Qwen/Qwen2.5-Coder-3B-Instruct"
                    pattern="[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+"
                    required
                  />
                </Field>
                <Field
                  label="Revision"
                  hint="The resolved commit is recorded with the model."
                >
                  <input name="revision" defaultValue="main" required />
                </Field>
                <Field
                  label="HF credential"
                  hint="Select a variable saved in Settings → Environment."
                >
                  <select name="credential_id">
                    <option value="">Public repository</option>
                    {environment.data?.names.map((name) => (
                      <option key={name} value={`env:${name}`}>
                        {name} (environment)
                      </option>
                    ))}
                    {credentials.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </Field>
              </div>
            </Form>
          </section>
          <section class="panel">
            <div class="panel-heading">
              <h2>Model artifacts</h2>
            </div>
            {!artifacts.some((a) => ["model", "adapter"].includes(a.kind)) && (
              <Empty>
                Import a safetensors model or finish a training run.
              </Empty>
            )}
            <div class="artifact-list">
              {artifacts.filter((a) => ["model", "adapter"].includes(a.kind))
                .map((a) => (
                  <div class="artifact-row" key={a.id}>
                    <div>
                      <strong>{a.name}</strong>
                      <small>{a.kind} · {a.status} · {a.id.slice(0, 12)}</small>
                      <small>
                        {String(
                          a.metadata.revision || a.metadata.base_revision || "",
                        )}
                      </small>
                    </div>
                    <a class="button secondary" href={`/jobs/${a.job_id}`}>
                      Files & lineage
                    </a>
                    <a
                      class="button secondary"
                      href={`/rl?artifact=${a.id}${
                        a.kind === "adapter" ? "&mode=evaluate" : ""
                      }`}
                    >
                      {a.kind === "model" ? "Train" : "Evaluate"}
                    </a>
                  </div>
                ))}
            </div>
          </section>
        </>
      )}
      {tab === "servers" && (
        <>
          <section class="panel">
            <div class="panel-heading">
              <h2>Serve with vLLM</h2>
              <a href="/settings">Connect a remote server</a>
            </div>
            <Form
              submit="Start server"
              onSubmit={async (data) => {
                const job = await api<Job>("/deployments", "POST", {
                  name: field(data, "name"),
                  artifact_id: field(data, "artifact_id"),
                  max_model_len: numeric(data, "max_model_len"),
                  gpu_memory_utilization: numeric(
                    data,
                    "gpu_memory_utilization",
                  ),
                  tool_parser: field(data, "tool_parser"),
                });
                location.assign(`/jobs/${job.id}`);
              }}
            >
              <div class="fields two">
                <Field label="Model / adapter">
                  <ArtifactSelect
                    artifacts={artifacts}
                    initial={typeof location !== "undefined"
                      ? new URLSearchParams(location.search).get("artifact") ||
                        ""
                      : ""}
                  />
                </Field>
                <Field label="Server name">
                  <input
                    name="name"
                    required
                    defaultValue="Inference"
                    maxLength={80}
                  />
                </Field>
                <Field label="Context window">
                  <input
                    name="max_model_len"
                    type="number"
                    defaultValue={4096}
                    min={512}
                    max={131072}
                    required
                  />
                </Field>
                <Field label="GPU memory fraction">
                  <input
                    name="gpu_memory_utilization"
                    type="number"
                    defaultValue={0.85}
                    step={0.05}
                    min={0.1}
                    max={0.95}
                    required
                  />
                </Field>
                <Field
                  label="Tool parser"
                  hint="Required for agentic benchmarking. Select the parser supported by this model."
                >
                  <select name="tool_parser">
                    <option value="">Chat only</option>
                    {["hermes", "llama3_json", "mistral", "qwen3_xml"].map((
                      p,
                    ) => <option key={p}>{p}</option>)}
                  </select>
                </Field>
              </div>
              <p class="muted">
                The server holds the worker GPU until stopped. Training and
                evaluation wait for it to become available.
              </p>
            </Form>
          </section>
          <section class="panel">
            <div class="panel-heading">
              <h2>Servers</h2>
            </div>
            <JobTable jobs={jobs.filter((j) => j.kind === "deployment")} />
          </section>
        </>
      )}
    </>
  );
}

function Chat({ connections }: { connections: Connection[] }) {
  const [conversation, setConversation] = useState(
      typeof location === "undefined"
        ? ""
        : new URLSearchParams(location.search).get("chat") || "",
    ),
    [version, setVersion] = useState(0);
  useEffect(() => {
    const url = new URL(location.href);
    if (conversation) url.searchParams.set("chat", conversation);
    else url.searchParams.delete("chat");
    history.replaceState({}, "", url);
  }, [conversation]);
  const list = usePoll<Conversation[]>(
    "/conversations?refresh=" + version,
    5000,
  );
  const detail = usePoll<Conversation>(
    conversation ? `/conversations/${conversation}?refresh=${version}` : "/me",
    2000,
  );
  const [draft, setDraft] = useState("");
  useEffect(() => {
    const value = sessionStorage.getItem("pg-task-prompt");
    if (value) {
      setDraft(value);
      sessionStorage.removeItem("pg-task-prompt");
    }
  }, []);
  const active = detail.data?.turns?.find((t) => !terminal(t.job));
  return (
    <div class="chat-layout">
      <aside class="panel chat-sidebar">
        <div class="panel-heading">
          <h2>Conversations</h2>
        </div>
        <button
          type="button"
          class="button secondary"
          onClick={() => setConversation("")}
        >
          New chat
        </button>
        {list.error && <Notice error>{list.error}</Notice>}
        <nav aria-label="Conversations">
          {list.data?.map((c) => (
            <button
              type="button"
              class={conversation === c.id ? "selected" : ""}
              key={c.id}
              onClick={() => setConversation(c.id)}
            >
              {c.name}
            </button>
          ))}
        </nav>
      </aside>
      <section class="panel chat-main">
        {!conversation
          ? (
            <>
              <div class="panel-heading">
                <h2>New chat</h2>
              </div>
              <Form
                submit="Create conversation"
                disabled={!connections.length}
                onSubmit={async (data) => {
                  const secondary = field(data, "compare");
                  const result = await api<Conversation>(
                    "/conversations",
                    "POST",
                    {
                      name: field(data, "name"),
                      connection_ids: [
                        field(data, "connection"),
                        ...(secondary ? [secondary] : []),
                      ],
                      system_prompt: field(data, "system_prompt"),
                      temperature: numeric(data, "temperature"),
                      max_tokens: numeric(data, "max_tokens"),
                    },
                  );
                  setConversation(result.id);
                  setVersion(version + 1);
                }}
              >
                <div class="fields two">
                  <Field label="Connection">
                    <select name="connection" required>
                      <option value="">Select a model</option>
                      {connections.map((c) => (
                        <option value={c.id} key={c.id}>
                          {c.name} · {c.model}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Compare with">
                    <select name="compare">
                      <option value="">Single model</option>
                      {connections.map((c) => (
                        <option value={c.id} key={c.id}>
                          {c.name} · {c.model}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <Field label="Conversation name">
                  <input
                    name="name"
                    defaultValue="New chat"
                    maxLength={100}
                    required
                  />
                </Field>
                <details class="advanced">
                  <summary>Generation settings</summary>
                  <Field label="System prompt">
                    <textarea name="system_prompt" rows={3} maxLength={20000} />
                  </Field>
                  <div class="fields two">
                    <Field label="Temperature">
                      <input
                        name="temperature"
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        defaultValue={0.7}
                        required
                      />
                    </Field>
                    <Field label="Output token limit">
                      <input
                        name="max_tokens"
                        type="number"
                        min={1}
                        max={32768}
                        defaultValue={2048}
                        required
                      />
                    </Field>
                  </div>
                </details>
                {!connections.length && (
                  <Notice>
                    <a href="/settings">Add a connection</a> to start chatting.
                  </Notice>
                )}
              </Form>
            </>
          )
          : (
            <>
              <div class="panel-heading">
                <h2>{detail.data?.name || "Conversation"}</h2>
                <a
                  href={`/api/v1/conversations/${conversation}`}
                  download="conversation.json"
                >
                  Export JSON
                </a>
              </div>
              {detail.error && <Notice error>{detail.error}</Notice>}
              <div class="chat-turns">
                {detail.data?.turns?.map((turn) => (
                  <article key={turn.id} class="chat-turn">
                    <div class="user-message">
                      <small>You</small>
                      <p>{turn.prompt}</p>
                    </div>
                    <JobMonitor
                      id={turn.job.id}
                      compact
                      connectionNames={Object.fromEntries(
                        Object.entries(detail.data?.config.connections || {})
                          .map(([id, c]) => [id, c.name]),
                      )}
                    />
                  </article>
                ))}
              </div>
              <Form
                submit="Send"
                disabled={!!active}
                onSubmit={async (data) => {
                  await api(`/conversations/${conversation}/turns`, "POST", {
                    prompt: field(data, "prompt"),
                  });
                  setDraft("");
                  setVersion(version + 1);
                }}
              >
                <Field label="Message">
                  <textarea
                    name="prompt"
                    rows={3}
                    required
                    maxLength={100000}
                    value={draft}
                    onInput={(e) => setDraft(e.currentTarget.value)}
                    placeholder="Ask the model…"
                  />
                </Field>
              </Form>
            </>
          )}
      </section>
    </div>
  );
}

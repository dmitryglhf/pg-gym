import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, message, terminal } from "@/lib/platform.ts";
import type { Connection, Conversation, Job, Worker } from "@/lib/platform.ts";
import { useResource } from "@/lib/query.ts";
import { connectionStatus, readiness } from "@/lib/readiness.ts";
import {
  preparationHref,
  readSession,
  useDraft,
  writeSession,
} from "@/lib/workspace.ts";
import { Field, Notice } from "./PlatformUI.tsx";
import { ChatTurn } from "./inference/ChatTurn.tsx";

export function InferencePanel(
  { connections, deployments, workers }: {
    connections: Connection[];
    deployments: Job[];
    workers: Worker[];
  },
) {
  const [id, setId] = useState(""),
    [initialized, setInitialized] = useState(false);
  const [config, setConfig, restored] = useDraft("chat-settings", {
    a: "",
    b: "",
    system: "",
    temperature: 0.7,
    tokens: 2048,
  });
  const [prompts, setPrompts] = useDraft<Record<string, string>>(
    "chat-prompts",
    {},
  );
  const [focus, setFocus] = useState(false),
    [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [uncertain, setUncertain] = useDraft("chat-create-uncertain", false);
  const [submitted, setSubmitted] = useState<
    { conversation: string; job: Job; prompt: string } | null
  >(null);
  const lock = useRef(false),
    composer = useRef<HTMLTextAreaElement>(null),
    end = useRef<HTMLDivElement>(null);
  const focusButton = useRef<HTMLButtonElement>(null);
  const list = useResource<Conversation[]>("/conversations", 10000);
  const detail = useResource<Conversation>(
    id ? `/conversations/${id}` : null,
    2000,
  );
  useEffect(() => {
    if (!restored || initialized) return;
    const query = new URLSearchParams(location.search),
      connection = query.get("connection");
    const returning = readSession<{ id: string; prompt: string } | null>(
      "chat-return",
      null,
    );
    setId(
      connection
        ? ""
        : query.get("chat") || returning?.id || readSession("chat-last-id", ""),
    );
    if (returning && connection) {
      setPrompts((old) => ({ ...old, new: returning.prompt }));
    }
    writeSession("chat-return", null);
    if (connection) {
      setConfig((old) => ({
        ...old,
        a: connection,
        b: old.b === connection ? "" : old.b,
      }));
    }
    let task: string | null = null;
    try {
      task = sessionStorage.getItem("pg-task-prompt");
    } catch { /* Optional persistence. */ }
    if (task) {
      setPrompts((old) => ({ ...old, new: task }));
      try {
        sessionStorage.removeItem("pg-task-prompt");
      } catch { /* Optional persistence. */ }
      setId("");
    }
    setInitialized(true);
  }, [restored, initialized]);
  useEffect(() => {
    if (!initialized) return;
    const url = new URL(location.href);
    url.searchParams.delete("connection");
    url.searchParams.delete("artifact");
    url.searchParams.delete("tab");
    if (id) url.searchParams.set("chat", id);
    else url.searchParams.delete("chat");
    history.replaceState({}, "", url);
  }, [id, initialized]);
  useEffect(() => {
    document.body.dataset.chatFocus = String(focus);
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && focus) {
        setFocus(false);
        focusButton.current?.focus();
      }
    };
    const revealActivity = () => setFocus(false);
    addEventListener("pg-open-activity", revealActivity);
    addEventListener("keydown", escape);
    return () => {
      delete document.body.dataset.chatFocus;
      removeEventListener("keydown", escape);
      removeEventListener("pg-open-activity", revealActivity);
    };
  }, [focus]);
  const conversation = detail.data?.id === id ? detail.data : null;
  const ids = id
    ? conversation?.config.connection_ids ||
      (submitted?.conversation === id
        ? [config.a, config.b].filter(Boolean)
        : [])
    : [config.a, config.b].filter(Boolean);
  const turns = conversation?.turns || [];
  const visibleTurns = submitted?.conversation === id &&
      !turns.some((turn) => turn.job.id === submitted.job.id)
    ? [...turns, {
      id: submitted.job.id,
      prompt: submitted.prompt,
      job: submitted.job,
    }]
    : turns;
  const active = visibleTurns.some((turn) => !terminal(turn.job));
  const unavailable = ids.some((key) => {
    const connection = connections.find((item) => item.id === key);
    return !connection || !connectionStatus(connection, deployments).usable;
  });
  const worker = readiness("chat", workers, []);
  const ready = initialized && worker.available &&
    (id ||
      (config.temperature >= 0 && config.temperature <= 2 &&
        config.tokens >= 1 && config.tokens <= 32768 &&
        Number.isInteger(config.tokens))) &&
    ids.length > 0 && new Set(ids).size === ids.length && !unavailable &&
    (!id || !!conversation);
  const prompt = prompts[id || "new"] || "";
  const changePrompt = (value: string) =>
    setPrompts((old) => ({ ...old, [id || "new"]: value }));
  const rememberReturn = () => writeSession("chat-return", { id, prompt });
  function choose(next: string) {
    if (busy) return;
    setId(next);
    writeSession("chat-last-id", next);
    setError("");
    setShowHistory(false);
  }
  async function send(event: SubmitEvent) {
    event.preventDefault();
    if (
      lock.current || !ready || active || !prompt.trim() || (!id && uncertain)
    ) return;
    lock.current = true;
    setBusy(true);
    setError("");
    let target = id;
    try {
      if (!target) {
        let created: Conversation;
        try {
          created = await api<Conversation>("/conversations", "POST", {
            name: prompt.trim().slice(0, 100),
            connection_ids: ids,
            system_prompt: config.system,
            temperature: config.temperature,
            max_tokens: config.tokens,
          });
        } catch (cause) {
          if (
            cause instanceof ApiError &&
            (cause.status === 0 || cause.status >= 500)
          ) {
            setUncertain(true);
            list.refresh();
            throw new Error(
              "Conversation creation was not confirmed. Check History before creating another conversation. Your prompt is saved.",
            );
          }
          throw cause;
        }
        target = created.id;
        writeSession("chat-last-id", target);
        const createdUrl = new URL(location.href);
        createdUrl.searchParams.set("chat", target);
        createdUrl.searchParams.delete("connection");
        history.replaceState({}, "", createdUrl);
        setPrompts((old) => ({ ...old, [target]: prompt, new: "" }));
        setId(target);
        list.refresh();
      }
      const job = await api<Job>(`/conversations/${target}/turns`, "POST", {
        prompt,
      });
      setSubmitted({ conversation: target, job, prompt });
      setPrompts((old) => ({ ...old, [target]: "" }));
      detail.refresh();
      list.refresh();
      end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    } catch (cause) {
      setError(message(cause));
    } finally {
      lock.current = false;
      setBusy(false);
      composer.current?.focus();
    }
  }
  return (
    <div class={`inference-workspace ${showHistory ? "with-history" : ""}`}>
      <div class="chat-toolbar">
        <div class="inline-actions">
          <button
            type="button"
            class="button secondary"
            aria-expanded={showHistory}
            onClick={() => {
              setFocus(false);
              setShowHistory(!showHistory);
            }}
          >
            History
          </button>
          <button
            type="button"
            class="button secondary"
            disabled={busy}
            onClick={() =>
              choose("")}
          >
            New chat
          </button>
        </div>
        <div class="inline-actions">
          <a href={preparationHref("inference")} onClick={rememberReturn}>
            Models & servers
          </a>
          <button
            ref={focusButton}
            type="button"
            class="button secondary"
            aria-pressed={focus}
            onClick={() => setFocus(!focus)}
          >
            {focus ? "Exit full screen" : "Full screen"}
          </button>
        </div>
      </div>
      <div class="inference-body">
        {showHistory && (
          <aside class="panel conversation-history">
            <h2>History</h2>
            {list.error && <Notice error>{list.error}</Notice>}
            <p class="muted">Most recent conversations</p>
            <nav aria-label="Conversations">
              {list.data?.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  disabled={busy}
                  class={id === item.id ? "selected" : ""}
                  aria-current={id === item.id ? "true" : undefined}
                  onClick={() => choose(item.id)}
                >
                  {item.name}
                  <small>
                    {item.config.connection_ids.length === 2
                      ? "A/B comparison"
                      : "Single model"}
                  </small>
                </button>
              ))}
            </nav>
            {!list.data?.length && <p>No conversations yet.</p>}
          </aside>
        )}
        <section class="chat-canvas">
          <div class="chat-model-bar">
            {id
              ? (
                <>
                  <h2>{conversation?.name || "Loading conversation…"}</h2>
                  <p class="muted">
                    {ids.map((key, index) =>
                      `${ids.length > 1 ? (index ? "B · " : "A · ") : ""}${
                        conversation?.config.connections[key]?.name || key
                      }`
                    ).join(" / ")}
                  </p>
                  <details>
                    <summary>Saved generation settings</summary>
                    <pre class="json-view">{JSON.stringify({ system_prompt: conversation?.config.system_prompt, temperature: conversation?.config.temperature, max_tokens: conversation?.config.max_tokens }, null, 2)}</pre>
                    <p class="muted">
                      Model selection and settings are fixed for this
                      conversation. Use New chat to change them.
                    </p>
                  </details>
                </>
              )
              : (
                <>
                  <div class="fields two">
                    <Field label="Model A">
                      <select
                        disabled={busy}
                        value={config.a}
                        onChange={(event) =>
                          setConfig({
                            ...config,
                            a: event.currentTarget.value,
                          })}
                      >
                        <option value="">Select a model</option>
                        {connections.map((connection) => (
                          <option
                            key={connection.id}
                            value={connection.id}
                            disabled={!connectionStatus(connection, deployments)
                              .usable || connection.id === config.b}
                          >
                            {connection.name} ·{" "}
                            {connectionStatus(connection, deployments).label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Model B · optional">
                      <select
                        disabled={busy}
                        value={config.b}
                        onChange={(event) =>
                          setConfig({
                            ...config,
                            b: event.currentTarget.value,
                          })}
                      >
                        <option value="">Single model</option>
                        {connections.map((connection) => (
                          <option
                            key={connection.id}
                            value={connection.id}
                            disabled={!connectionStatus(connection, deployments)
                              .usable || connection.id === config.a}
                          >
                            {connection.name} ·{" "}
                            {connectionStatus(connection, deployments).label}
                          </option>
                        ))}
                      </select>
                    </Field>
                  </div>
                  <details class="chat-settings">
                    <summary>Generation settings</summary>
                    <Field label="System prompt">
                      <textarea
                        rows={3}
                        maxLength={20000}
                        value={config.system}
                        onInput={(event) =>
                          setConfig({
                            ...config,
                            system: event.currentTarget.value,
                          })}
                      />
                    </Field>
                    <div class="fields two">
                      <Field label="Temperature">
                        <input
                          type="number"
                          min={0}
                          max={2}
                          step={0.1}
                          value={config.temperature}
                          onInput={(event) =>
                            setConfig({
                              ...config,
                              temperature: Number(event.currentTarget.value),
                            })}
                        />
                      </Field>
                      <Field label="Output token limit">
                        <input
                          type="number"
                          min={1}
                          max={32768}
                          value={config.tokens}
                          onInput={(event) =>
                            setConfig({
                              ...config,
                              tokens: Number(event.currentTarget.value),
                            })}
                        />
                      </Field>
                    </div>
                  </details>
                </>
              )}
            {ids.length === 2 && (
              <p class="muted">
                One prompt, separate model histories. A runs first, then B. One
                GPU worker can host one local server; use an external endpoint
                for the other model. Response time is not a controlled
                performance benchmark.
              </p>
            )}
            {unavailable && (
              <Notice>
                A selected server is unavailable. Your conversation is
                preserved.{" "}
                <a href={preparationHref("inference")} onClick={rememberReturn}>
                  Prepare a model
                </a>{" "}
                and start a new chat with its connection.
              </Notice>
            )}
            {!connections.some((item) =>
              connectionStatus(item, deployments).usable
            ) && !unavailable && (
              <Notice>
                <a href={preparationHref("inference")} onClick={rememberReturn}>
                  Prepare your first model
                </a>{" "}
                to send messages. You can keep writing your draft here.
              </Notice>
            )}
          </div>
          {detail.error && <Notice error>{detail.error}</Notice>}
          <div class="conversation-transcript">
            {!id && (
              <div class="chat-welcome">
                <h2>Try a model. Compare an answer.</h2>
                <p>Select one or two models and send a message.</p>
                <div class="inline-actions">
                  {[
                    "Explain this PostgreSQL query plan",
                    "Help me reason about an index",
                    "Review a SQL query",
                  ].map((text) => (
                    <button
                      type="button"
                      class="button secondary"
                      key={text}
                      onClick={() => {
                        changePrompt(text + ":\n\n");
                        composer.current?.focus();
                      }}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {visibleTurns.map((turn) => (
              <ChatTurn
                key={turn.id}
                turn={turn}
                ids={ids}
                connections={conversation?.config.connections ||
                  Object.fromEntries(
                    connections.map((item) => [item.id, item]),
                  )}
                onReuse={(value) => {
                  changePrompt(value);
                  composer.current?.focus();
                }}
              />
            ))}
            <div ref={end} />
          </div>
          <form class="chat-composer" onSubmit={send}>
            {!worker.available && (
              <Notice>
                {worker.reason} <a href="/#workers">Inspect resources</a>
              </Notice>
            )}
            {!id &&
              !(config.temperature >= 0 && config.temperature <= 2 &&
                config.tokens >= 1 && config.tokens <= 32768 &&
                Number.isInteger(config.tokens)) &&
              (
                <Notice error>
                  Check generation settings: temperature must be 0–2; output
                  token limit must be an integer from 1 to 32768.
                </Notice>
              )}
            {error && <Notice error>{error}</Notice>}
            {!id && uncertain && (
              <Notice>
                Creation is unconfirmed.{" "}
                <button
                  type="button"
                  class="text-button"
                  onClick={() => setShowHistory(true)}
                >
                  Check History
                </button>
                <button
                  type="button"
                  class="text-button"
                  onClick={() => {
                    if (
                      confirm(
                        "Create another conversation? The previous request may already have created an empty one.",
                      )
                    ) setUncertain(false);
                  }}
                >
                  Create another anyway
                </button>
              </Notice>
            )}
            <label class="sr-only" for="chat-prompt">
              Message for {ids.length === 2 ? "both models" : "the model"}
            </label>
            <textarea
              id="chat-prompt"
              ref={composer}
              rows={3}
              maxLength={100000}
              required
              value={prompt}
              onInput={(event) => changePrompt(event.currentTarget.value)}
              placeholder={ids.length === 2
                ? "Ask both models…"
                : "Ask anything…"}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div class="split-line">
              <small>
                {active
                  ? "Generation is running. You can write your next message."
                  : "Ctrl / ⌘ + Enter to send · Shift + Enter for a new line"}
              </small>
              <button
                type="submit"
                class="button primary"
                disabled={busy || !!active || !ready || !prompt.trim() ||
                  (!id && uncertain)}
              >
                {busy ? "Sending…" : ids.length === 2 ? "Send to both" : "Send"}
              </button>
            </div>
            {id && (
              <a
                class="chat-export"
                href={`/api/v1/conversations/${id}`}
                download="conversation.json"
              >
                Export conversation
              </a>
            )}
          </form>
        </section>
      </div>
    </div>
  );
}

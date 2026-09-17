import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, message, terminal } from "@/lib/platform.ts";
import type {
  Artifact,
  Connection,
  Conversation,
  Job,
  Worker,
} from "@/lib/platform.ts";
import { useResource } from "@/lib/query.ts";
import { connectionStatus, readiness } from "@/lib/readiness.ts";
import {
  openActivity,
  preparationHref,
  readSession,
  useDraft,
  writeSession,
} from "@/lib/workspace.ts";
import { Field, Notice } from "./PlatformUI.tsx";
import { ChatTurn } from "./inference/ChatTurn.tsx";
import { Icon } from "./Icon.tsx";
import { chatModels, modelSelection } from "@/lib/chat-models.ts";
import { ModelPicker } from "./inference/ModelPicker.tsx";
import { LocalModelLaunch } from "./inference/LocalModelLaunch.tsx";

export function InferencePanel(
  {
    connections,
    deployments,
    workers,
    artifacts,
    artifactsLoaded,
    jobs,
    refresh,
  }: {
    connections: Connection[];
    deployments: Job[];
    workers: Worker[];
    artifacts: Artifact[];
    artifactsLoaded: boolean;
    jobs: Job[];
    refresh: () => void;
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
    | {
      conversation: string;
      job: Job;
      prompt: string;
      connectionIds: string[];
    }
    | null
  >(null);
  const lock = useRef(false),
    composer = useRef<HTMLTextAreaElement>(null),
    end = useRef<HTMLDivElement>(null);
  const focusButton = useRef<HTMLButtonElement>(null);
  const list = useResource<Conversation[]>("/conversations", 10000);
  useEffect(() => {
    document.body.dataset.chatPage = "true";
    return () => {
      delete document.body.dataset.chatPage;
    };
  }, []);
  useEffect(() => {
    if (submitted?.conversation === id) {
      end.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [submitted?.job.id]);
  // The conversation is re-read quickly only while a turn is generating.
  const [generating, setGenerating] = useState(false);
  const detail = useResource<Conversation>(
    id ? `/conversations/${id}` : null,
    generating ? 2000 : 15000,
  );
  useEffect(() => {
    if (!restored || initialized) return;
    const query = new URLSearchParams(location.search),
      connection = query.get("connection"),
      requested = query.get("model")
        ? "artifact:" + query.get("model")
        : connection;
    const returning = readSession<{ id: string; prompt: string } | null>(
      "chat-return",
      null,
    );
    setId(
      requested
        ? ""
        : query.get("chat") || returning?.id || readSession("chat-last-id", ""),
    );
    if (returning && requested) {
      setPrompts((old) => ({ ...old, new: returning.prompt }));
    }
    writeSession("chat-return", null);
    if (requested) writeSession("chat-last-id", "");
    if (requested) {
      setConfig((old) => ({
        ...old,
        a: requested,
        b: old.b === requested ? "" : old.b,
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
      writeSession("chat-last-id", "");
    }
    setInitialized(true);
  }, [restored, initialized]);
  useEffect(() => {
    if (!initialized) return;
    const url = new URL(location.href);
    url.searchParams.delete("connection");
    url.searchParams.delete("model");
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
  const models = chatModels(artifacts, connections, deployments);
  const selectionA = modelSelection(config.a, models, connections, deployments);
  const candidateB = modelSelection(config.b, models, connections, deployments);
  const selectionB = candidateB === selectionA ? "" : candidateB;
  useEffect(() => {
    if (candidateB && candidateB === selectionA) {
      setConfig((old) => ({ ...old, b: "" }));
    }
  }, [selectionA, candidateB]);
  const choices = [selectionA, selectionB].filter(Boolean);
  const selectedModels = choices.map((key) =>
    models.find((model) => model.key === key)
  );
  const draftIds = selectedModels.map((model) =>
    model?.usable ? model.connection?.id : undefined
  ).filter((value): value is string => !!value);
  const localSelections = selectedModels.filter((model) => !!model?.artifact);
  const comparisonBlocked = localSelections.length === 2 &&
    localSelections.some((model) => !model?.usable) &&
    workers.filter((worker) =>
        worker.connected && worker.capabilities.includes("deployment")
      ).length < 2;
  useEffect(() => {
    if (
      initialized && restored && !id && !config.a && artifactsLoaded &&
      models.length === 1
    ) setConfig((old) => ({ ...old, a: models[0].key }));
  }, [initialized, restored, id, config.a, artifactsLoaded, models]);
  const conversation = detail.data?.id === id ? detail.data : null;
  const ids = id
    ? conversation?.config.connection_ids ||
      (submitted?.conversation === id ? submitted.connectionIds : [])
    : draftIds;
  const modelCount = id ? ids.length : choices.length;
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
  useEffect(() => setGenerating(active), [active]);
  const unavailable = id
    ? ids.some((key) => {
      const connection = connections.find((item) => item.id === key);
      return !connection || !connectionStatus(connection, deployments).usable;
    })
    : selectedModels.some((model) => model && !model.artifact && !model.usable);
  const worker = readiness("chat", workers, []);
  const ready = initialized && worker.available &&
    (id ||
      (config.temperature >= 0 && config.temperature <= 2 &&
        config.tokens >= 1 && config.tokens <= 32768 &&
        Number.isInteger(config.tokens) && !!selectionA &&
        draftIds.length === choices.length)) &&
    ids.length > 0 && new Set(ids).size === ids.length && !unavailable &&
    (!id || !!conversation);
  const prompt = prompts[id || "new"] || "";
  const changePrompt = (value: string) =>
    setPrompts((old) => ({ ...old, [id || "new"]: value }));
  const rememberReturn = () => writeSession("chat-return", { id, prompt });
  function choose(next: string) {
    if (busy) return;
    if (uncertain && next && !id) {
      setPrompts((old) => ({ ...old, [next]: old[next] || old.new || "" }));
      setUncertain(false);
    }
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
      setSubmitted({ conversation: target, job, prompt, connectionIds: ids });
      setPrompts((old) => ({ ...old, [target]: "" }));
      detail.refresh();
      list.refresh();
    } catch (cause) {
      setError(message(cause));
    } finally {
      lock.current = false;
      setBusy(false);
      requestAnimationFrame(() =>
        composer.current?.focus({ preventScroll: true })
      );
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
            class="icon-button"
            type="button"
            title="Activity & logs"
            aria-label="Activity & logs"
            onClick={() => openActivity()}
          >
            <Icon name="terminal" size={18} />
          </button>
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
                    <ModelPicker
                      label="Model A"
                      value={selectionA}
                      other={selectionB}
                      models={models}
                      disabled={busy}
                      onChange={(value) =>
                        setConfig((old) => ({ ...old, a: value }))}
                    />
                    <ModelPicker
                      label="Model B · optional"
                      value={selectionB}
                      other={selectionA}
                      models={models}
                      disabled={busy}
                      optional
                      onChange={(value) =>
                        setConfig((old) => ({ ...old, b: value }))}
                    />
                  </div>
                  <p class="muted model-picker-hint">
                    Downloaded models, trained variants and API connections.
                    Fine-tuning is optional.
                  </p>
                  {!artifactsLoaded && (
                    <p role="status" class="muted">
                      Loading local model library…
                    </p>
                  )}
                  {comparisonBlocked && (
                    <Notice>
                      Two local models need two serving workers. For A/B on one
                      worker, use an API connection for the other model.
                    </Notice>
                  )}
                  {selectedModels.filter((model) =>
                    !!model?.artifact && !model.usable
                  ).map((model) => (
                    <LocalModelLaunch
                      key={model!.key}
                      model={model!}
                      workers={workers}
                      jobs={[...deployments, ...jobs]}
                      comparisonBlocked={comparisonBlocked}
                      onChanged={refresh}
                      onLeave={rememberReturn}
                    />
                  ))}
                  {selectedModels.some((model) => !model) && (
                    <Notice>
                      The selected model is not in the library. Choose another
                      model or check Models & servers.
                    </Notice>
                  )}
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
            {modelCount === 2 && (
              <p class="muted">
                One prompt, separate model histories. A runs first, then B. One
                GPU worker can host one local server; with one worker, use an
                API connection for the other model. Response time is not a
                controlled performance benchmark.
              </p>
            )}
            {unavailable && (
              <Notice>
                {id
                  ? "A selected server is unavailable. Your conversation is preserved."
                  : "The selected server is unavailable. Choose another model or check its server."}
                {" "}
                <a href={preparationHref("inference")} onClick={rememberReturn}>
                  Prepare a model
                </a>{" "}
                {id && " and start a new chat with its connection."}
              </Notice>
            )}
            {artifactsLoaded && models.length === 0 && !id && (
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
                key={turn.job.id}
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
              Message for {modelCount === 2 ? "both models" : "the model"}
            </label>
            <textarea
              id="chat-prompt"
              ref={composer}
              disabled={busy}
              rows={3}
              maxLength={100000}
              required
              value={prompt}
              onInput={(event) => changePrompt(event.currentTarget.value)}
              placeholder={modelCount === 2
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
                {busy ? "Sending…" : modelCount === 2 ? "Send to both" : "Send"}
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

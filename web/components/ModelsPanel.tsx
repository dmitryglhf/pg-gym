import { useEffect, useState } from "preact/hooks";
import { readiness } from "@/lib/readiness.ts";
import { returnHref, useDraft } from "@/lib/workspace.ts";
import { EnvironmentPanel } from "./EnvironmentPanel.tsx";
import { Field, Notice } from "./PlatformUI.tsx";
import { OperationCard } from "./OperationCard.tsx";
import { Icon } from "./Icon.tsx";
import { AddModel } from "./models/AddModel.tsx";
import { ArtifactDetail } from "./models/ArtifactDetail.tsx";
import { ConnectionCard } from "./models/ConnectionCard.tsx";
import type { ModelsProps } from "./models/types.ts";
export function ModelsPanel(props: ModelsProps) {
  const { artifacts, connections, deployments, workers, jobs, refresh } = props;
  const local = artifacts.filter((item) =>
    ["model", "adapter"].includes(item.kind)
  );
  const remote = connections.filter((item) => !item.managed_job_id);
  const [selected, setSelected] = useDraft("model-selection", "");
  const [adding, setAdding] = useState(false),
    [keys, setKeys] = useState(false),
    [query, setQuery] = useState("");
  const [target, setTarget] = useState<string | null>(null);
  const [pending, setPending] = useDraft("model-operation", "");
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    setTarget(params.get("return"));
    if (params.get("artifact")) {
      setSelected("artifact:" + params.get("artifact"));
    }
    if (params.get("connection")) {
      setSelected("connection:" + params.get("connection"));
    }
    if (params.has("add")) setAdding(true);
    if (params.get("section") === "keys") setKeys(true);
  }, []);
  const exists = local.some((item) => "artifact:" + item.id === selected) ||
    remote.some((item) => "connection:" + item.id === selected);
  const active = (exists ? selected : "") ||
    (local[0]
      ? "artifact:" + local[0].id
      : remote[0]
      ? "connection:" + remote[0].id
      : "");
  const artifact = local.find((item) => "artifact:" + item.id === active);
  const endpoint = remote.find((item) => "connection:" + item.id === active);
  const deploymentReady = readiness("deployment", workers, [
    ...deployments,
    ...jobs,
  ]);
  function select(value: string) {
    setSelected(value);
    const url = new URL(location.href);
    url.searchParams.delete("artifact");
    url.searchParams.delete("connection");
    const [kind, id] = value.split(":");
    url.searchParams.set(kind, id);
    history.replaceState(null, "", url);
  }
  return (
    <>
      <div class="section-toolbar">
        <p class="muted">
          Prepare a model here, then use it in chat, benchmarks or training.
        </p>
        <div class="inline-actions">
          <button
            type="button"
            class="button secondary"
            onClick={() => setKeys(!keys)}
            aria-expanded={keys}
          >
            Keys & variables
          </button>
          <button
            type="button"
            class="button primary"
            onClick={() => setAdding(!adding)}
            aria-expanded={adding}
          >
            <Icon name="plus" size={16} />Add model
          </button>
        </div>
      </div>
      {target && (
        <Notice>
          Preparing a model for {target === "training"
            ? "training"
            : target === "benchmark"
            ? "a benchmark"
            : "chat"}. Your draft stays saved.{" "}
          <a href={returnHref(target)}>Return to draft</a>
        </Notice>
      )}
      {keys && (
        <section class="panel">
          <div class="panel-heading">
            <h2>Account variables</h2>
            <button
              type="button"
              class="text-button"
              onClick={() => setKeys(false)}
            >
              Close
            </button>
          </div>
          <EnvironmentPanel />
        </section>
      )}
      {adding && (
        <AddModel
          workers={workers}
          onAdded={(job, connection) => {
            if (job) setPending(job.id);
            if (connection) select("connection:" + connection);
            setAdding(false);
            refresh();
          }}
        />
      )}
      {pending && (
        <>
          <OperationCard
            id={pending}
            onComplete={refresh}
          />
          <button
            type="button"
            class="text-button"
            onClick={() => setPending("")}
          >
            Dismiss operation card
          </button>
        </>
      )}
      <div class="readiness-strip">
        <Icon name="info" size={17} />
        <span>{deploymentReady.reason}</span>
        <a href="/#workers">Resources</a>
      </div>
      <div class="model-layout">
        <aside class="panel model-index">
          <Field label="Find a model">
            <input
              type="search"
              value={query}
              onInput={(e) => setQuery(e.currentTarget.value)}
              placeholder="Name or repository"
            />
          </Field>
          <nav aria-label="Models and endpoints">
            {local.filter((item) =>
              item.name.toLowerCase().includes(query.toLowerCase())
            ).map((item) => (
              <button
                type="button"
                key={item.id}
                class={active === "artifact:" + item.id ? "selected" : ""}
                aria-pressed={active === "artifact:" + item.id}
                onClick={() => select("artifact:" + item.id)}
              >
                <Icon name="layers" />
                <span>
                  <strong>{item.name}</strong>
                  <small>
                    {item.kind === "adapter"
                      ? "Trained variant"
                      : "Downloaded model"} ·{" "}
                    {item.status === "ready" ? "Files ready" : item.status}
                  </small>
                </span>
              </button>
            ))}
            {remote.filter((item) =>
              `${item.name} ${item.model}`.toLowerCase().includes(
                query.toLowerCase(),
              )
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                class={active === "connection:" + item.id ? "selected" : ""}
                aria-pressed={active === "connection:" + item.id}
                onClick={() => select("connection:" + item.id)}
              >
                <Icon name="chat" />
                <span>
                  <strong>{item.name}</strong>
                  <small>External endpoint · {item.model}</small>
                </span>
              </button>
            ))}
          </nav>
          {!local.length && !remote.length && (
            <p class="empty-state">
              Your models will appear here. Add a Hugging Face model or connect
              an existing endpoint.
            </p>
          )}
        </aside>
        <div class="model-detail">
          {artifact
            ? (
              <ArtifactDetail
                key={artifact.id}
                artifact={artifact}
                {...props}
                target={target}
                onOperation={setPending}
                onSelect={select}
              />
            )
            : endpoint
            ? (
              <ConnectionCard
                key={endpoint.id}
                connection={endpoint}
                deployments={deployments}
                target={target}
                onChanged={refresh}
              />
            )
            : (
              <section class="panel feature-empty">
                <Icon name="layers" size={38} />
                <h2>One place to prepare your models</h2>
                <p>
                  Download weights for local serving and training, or connect an
                  existing API for chat and benchmarks.
                </p>
                <button
                  type="button"
                  class="button primary"
                  onClick={() => setAdding(true)}
                >
                  Add your first model
                </button>
              </section>
            )}
        </div>
      </div>
    </>
  );
}

import { useState } from "preact/hooks";
import { field, numeric, terminal } from "@/lib/platform.ts";
import type { Artifact } from "@/lib/platform.ts";
import { startModelServer } from "@/lib/serving.ts";
import { readiness } from "@/lib/readiness.ts";
import { openActivity, returnHref, useDraft } from "@/lib/workspace.ts";
import { Field, Form, Notice } from "../PlatformUI.tsx";
import { OperationCard } from "../OperationCard.tsx";
import { ConnectionCard } from "./ConnectionCard.tsx";
import type { ModelsProps } from "./types.ts";

export function ArtifactDetail({
  artifact,
  artifacts,
  connections,
  deployments,
  workers,
  jobs,
  target,
  onOperation,
  onSelect,
  refresh,
}: ModelsProps & {
  artifact: Artifact;
  target: string | null;
  onOperation: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const servers = deployments.filter((job) =>
    job.config.artifact_id === artifact.id
  );
  const active = servers.filter((job) => !terminal(job));
  const variants = artifacts.filter((item) =>
    item.metadata.base_artifact_id === artifact.id
  );
  const [draft, setDraft] = useDraft("server:" + artifact.id, {
    purpose: "",
    tool_parser: "",
    name: artifact.name.slice(0, 80),
    max_model_len: "4096",
    gpu_memory_utilization: "0.85",
  });
  const { purpose } = draft;
  const edit = (name: keyof typeof draft, value: string) =>
    setDraft((old) => ({ ...old, [name]: value }));
  const [queueFor, setQueueFor] = useState("");
  const state = readiness("deployment", workers, [...deployments, ...jobs]);
  return (
    <>
      <section class="panel">
        <div class="panel-heading">
          <div>
            <small>
              {artifact.kind === "adapter" ? "Trained variant" : "Local model"}
            </small>
            <h2>{artifact.name}</h2>
          </div>
          <span class="status-chip">
            {artifact.status === "ready" ? "Files ready" : artifact.status}
          </span>
        </div>
        <p class="muted">
          {artifact.kind === "model"
            ? "Use these downloaded weights in chat as-is, or train a new variant. Fine-tuning is optional."
            : "Use this trained variant in chat, or evaluate it against the base model."}
          {" "}
          Chat runs through a model server.
        </p>
        <div class="inline-actions">
          {artifact.status === "ready" && (
            <a
              class={`button ${
                target === "training" ? "secondary" : "primary"
              }`}
              href={"/inference?model=" + encodeURIComponent(artifact.id)}
            >
              Open in chat
            </a>
          )}
          {artifact.kind === "model" && artifact.status === "ready" && (
            <a
              class={`button ${
                target === "training" ? "primary" : "secondary"
              }`}
              href={returnHref("training", undefined, artifact.id) +
                "&mode=train"}
            >
              Train this model
            </a>
          )}
          <a
            class="button secondary"
            href={`/rl?artifact=${artifact.id}&mode=evaluate`}
          >
            Evaluate
          </a>
          <a href={`/jobs/${artifact.job_id}`}>Files & result</a>
        </div>
        {typeof artifact.metadata.base_artifact_id === "string" && (
          <p class="lineage-line">
            Based on{" "}
            <button
              type="button"
              class="text-button"
              onClick={() =>
                onSelect("artifact:" + artifact.metadata.base_artifact_id)}
            >
              {artifacts.find((item) =>
                item.id === artifact.metadata.base_artifact_id
              )?.name || "base model"}
            </button>
          </p>
        )}
        {variants.length > 0 && (
          <div class="variant-list">
            <h3>Trained variants</h3>
            {variants.map((variant) => (
              <button
                key={variant.id}
                class="button secondary"
                type="button"
                onClick={() => onSelect("artifact:" + variant.id)}
              >
                {variant.name}
              </button>
            ))}
          </div>
        )}
        <details class="advanced">
          <summary>Model identity</summary>
          <pre class="json-view">{JSON.stringify({ id: artifact.id, ...artifact.metadata }, null, 2)}</pre>
        </details>
      </section>
      {servers.filter((job) => !terminal(job)).map((job) => {
        const connection = connections.find((item) =>
          item.managed_job_id === job.id
        );
        return (
          <section class="panel" key={job.id}>
            {connection
              ? (
                <ConnectionCard
                  connection={connection}
                  deployments={deployments}
                  target={target}
                  onChanged={refresh}
                />
              )
              : <OperationCard id={job.id} />}
          </section>
        );
      })}
      {servers.some(terminal) && (
        <details class="panel">
          <summary>
            Previous server runs ({servers.filter(terminal).length})
          </summary>
          {servers.filter(terminal).map((job) => (
            <div key={job.id} class="settings-row">
              <a href={`/jobs/${job.id}`}>{job.name}</a>
              <span>{job.status}</span>
              <button
                type="button"
                class="text-button"
                onClick={() =>
                  openActivity(job.id)}
              >
                Logs
              </button>
            </div>
          ))}
        </details>
      )}
      {!active.length && (
        <section class="panel">
          <div class="panel-heading">
            <h2>Start a server</h2>
            <small>Uses the worker GPU until stopped</small>
          </div>
          <Form
            submit={state.busy ? "Queue server" : "Start server"}
            disabled={artifact.status !== "ready" || !state.available ||
              (!!state.busy && queueFor !== state.busy.id)}
            onSubmit={async (data) => {
              const job = await startModelServer(artifact, {
                name: field(data, "name"),
                max_model_len: numeric(data, "max_model_len"),
                gpu_memory_utilization: numeric(data, "gpu_memory_utilization"),
                tool_parser: purpose === "harness"
                  ? field(data, "tool_parser")
                  : "",
              });
              onOperation(job.id);
              refresh();
            }}
          >
            <Field label="What will you use this server for?">
              <select
                required
                value={purpose}
                onChange={(e) => edit("purpose", e.currentTarget.value)}
              >
                <option value="">Choose a purpose</option>
                <option value="chat">Chat</option>
                <option value="harness">Chat and harness benchmarks</option>
              </select>
            </Field>
            {purpose === "harness" && (
              <Field
                label="Tool parser"
                hint="Choose the parser supported by this model. The platform does not guess model compatibility."
              >
                <select
                  name="tool_parser"
                  required
                  value={draft.tool_parser}
                  onChange={(e) => edit("tool_parser", e.currentTarget.value)}
                >
                  <option value="">Select supported parser</option>
                  {["hermes", "llama3_json", "mistral", "qwen3_xml"].map((
                    parser,
                  ) => <option key={parser}>{parser}</option>)}
                </select>
              </Field>
            )}
            <details class="advanced">
              <summary>Server settings</summary>
              <div class="fields three">
                <Field label="Server name">
                  <input
                    name="name"
                    value={draft.name}
                    onInput={(e) => edit("name", e.currentTarget.value)}
                    maxLength={80}
                    required
                  />
                </Field>
                <Field label="Context window">
                  <input
                    type="number"
                    name="max_model_len"
                    value={draft.max_model_len}
                    onInput={(e) =>
                      edit("max_model_len", e.currentTarget.value)}
                    min={1024}
                    max={131072}
                    required
                  />
                </Field>
                <Field label="GPU memory fraction">
                  <input
                    type="number"
                    name="gpu_memory_utilization"
                    value={draft.gpu_memory_utilization}
                    onInput={(e) =>
                      edit("gpu_memory_utilization", e.currentTarget.value)}
                    min={0.1}
                    max={0.95}
                    step={0.05}
                    required
                  />
                </Field>
              </div>
            </details>
            <Notice>
              {state.reason}
              {state.busy && (
                <>
                  <button
                    class="text-button"
                    type="button"
                    onClick={() => openActivity(state.busy!.id)}
                  >
                    Open blocking run
                  </button>
                  <label class="check-field">
                    <input
                      type="checkbox"
                      checked={queueFor === state.busy.id}
                      onChange={(e) =>
                        setQueueFor(
                          e.currentTarget.checked ? state.busy!.id : "",
                        )}
                    />Queue explicitly; a running server will not stop
                    automatically
                  </label>
                </>
              )}
            </Notice>
          </Form>
        </section>
      )}
    </>
  );
}

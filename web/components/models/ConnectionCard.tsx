import { useState } from "preact/hooks";
import { api, field, message, numeric, terminal } from "@/lib/platform.ts";
import type { Connection, Job } from "@/lib/platform.ts";
import { connectionStatus } from "@/lib/readiness.ts";
import { openActivity, returnHref } from "@/lib/workspace.ts";
import { CredentialPicker } from "../CredentialPicker.tsx";
import { Field, Form, Notice } from "../PlatformUI.tsx";

export function ConnectionCard(
  { connection, deployments, target, onChanged }: {
    connection: Connection;
    deployments: Job[];
    target: string | null;
    onChanged: () => void;
  },
) {
  const [editingKey, setEditingKey] = useState(false);
  const state = connectionStatus(connection, deployments);
  const [feedback, setFeedback] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState(false),
    [key, setKey] = useState(
      connection.api_key_env || (connection.has_key ? "__stored" : ""),
    );
  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      await action();
      onChanged();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  const job = deployments.find((item) => item.id === connection.managed_job_id);
  const canStop = job && !terminal(job);
  return (
    <div class="connection-detail">
      <div class="panel-heading">
        <div>
          <small>
            {connection.managed_job_id ? "Managed server" : "External endpoint"}
          </small>
          <h2>{connection.name}</h2>
          <p class="muted">{connection.model}</p>
        </div>
        <span
          class={`status-chip ${
            state.usable ? "status-succeeded" : "status-unknown"
          }`}
        >
          {state.label}
        </span>
      </div>
      <p class="muted">{state.detail}</p>
      <div class="capability-chips">
        <span class="status-chip">
          {connection.tools ? "Tool calling configured" : "Chat only"}
        </span>
        {!connection.managed_job_id && (
          <span class="status-chip">No local weights for training</span>
        )}
      </div>
      <div class="inline-actions">
        {state.usable && (
          <>
            <a
              class={`button ${
                target !== "benchmark" ? "primary" : "secondary"
              }`}
              href={returnHref("inference", connection.id)}
            >
              Open chat
            </a>
            {connection.tools
              ? (
                <a
                  class={`button ${
                    target === "benchmark" ? "primary" : "secondary"
                  }`}
                  href={returnHref("benchmark", connection.id)}
                >
                  Benchmark
                </a>
              )
              : (
                <span class="muted">
                  Harness benchmarks require tool calling.
                </span>
              )}
          </>
        )}
        <button
          type="button"
          class="button secondary"
          disabled={busy || (!!connection.managed_job_id && !state.usable)}
          onClick={() =>
            act(async () => {
              const result = await api<{ ok: boolean; message: string }>(
                `/connections/${connection.id}/check`,
                "POST",
              );
              if (!result.ok) throw new Error(result.message);
              setFeedback(
                "Endpoint lists this model. Checked " +
                  new Date().toLocaleTimeString() +
                  ". This is not a tool-calling test.",
              );
            })}
        >
          Check
        </button>
        {!connection.managed_job_id && (
          <button
            type="button"
            class="text-button"
            onClick={() => {
              if (!editing) {
                setKey(
                  connection.api_key_env ||
                    (connection.has_key ? "__stored" : ""),
                );
              }
              setEditingKey(false);
              setEditing(!editing);
            }}
          >
            Edit
          </button>
        )}
        {canStop && (
          <button
            type="button"
            class="text-button"
            disabled={busy || job.cancel_requested}
            onClick={() => {
              if (
                confirm(
                  "Stop this server and release its GPU slot? Chats and benchmarks using it will lose their endpoint. Existing conversations remain in history; a restarted server creates a new connection.",
                )
              ) {
                act(async () => {
                  await api(`/deployments/${job.id}/stop`, "POST");
                });
              }
            }}
          >
            {job.cancel_requested ? "Stopping…" : "Stop server"}
          </button>
        )}
        {job && (
          <button
            type="button"
            class="text-button"
            onClick={() => openActivity(job.id)}
          >
            Open logs
          </button>
        )}
        {(!connection.managed_job_id || (job && terminal(job))) && (
          <button
            type="button"
            class="text-button"
            disabled={busy}
            onClick={() => {
              if (
                confirm(
                  "Delete this connection? Historical configurations are retained.",
                )
              ) {
                act(async () => {
                  await api(`/connections/${connection.id}`, "DELETE");
                  setFeedback("Connection deleted.");
                });
              }
            }}
          >
            Delete connection
          </button>
        )}
      </div>
      {error && <Notice error>{error}</Notice>}
      {feedback && <Notice>{feedback}</Notice>}
      {editing && (
        <Form
          submit="Save connection"
          disabled={editingKey}
          onSubmit={async (data) => {
            await api(`/connections/${connection.id}`, "PUT", {
              name: field(data, "name"),
              base_url: field(data, "base_url"),
              model: field(data, "model"),
              api_key_env: key && key !== "__stored" ? key : null,
              ...(key === "__stored" ? {} : { api_key: "" }),
              context_length: numeric(data, "context_length"),
              max_tokens: numeric(data, "max_tokens"),
              tools: data.has("tools"),
            });
            setEditing(false);
            onChanged();
          }}
        >
          <div class="fields three">
            <Field label="Name">
              <input
                name="name"
                defaultValue={connection.name}
                required
                maxLength={80}
              />
            </Field>
            <Field label="API base URL">
              <input
                name="base_url"
                type="url"
                defaultValue={connection.base_url}
                required
              />
            </Field>
            <Field label="Model identifier">
              <input name="model" defaultValue={connection.model} required />
            </Field>
          </div>
          <CredentialPicker
            keepStoredKey={connection.has_key && !connection.api_key_env}
            onEditingChange={setEditingKey}
            value={key}
            onChange={setKey}
          />
          {key === "__stored" && (
            <p class="muted">The existing stored key is preserved.</p>
          )}
          <label class="check-field">
            <input
              name="tools"
              type="checkbox"
              defaultChecked={connection.tools}
            />Supports tool calling
          </label>
          <details class="advanced">
            <summary>Token limits</summary>
            <div class="fields two">
              <Field label="Context length">
                <input
                  type="number"
                  name="context_length"
                  min={1024}
                  max={2097152}
                  defaultValue={connection.context_length}
                  required
                />
              </Field>
              <Field label="Maximum output tokens">
                <input
                  type="number"
                  name="max_tokens"
                  min={16}
                  max={131072}
                  defaultValue={connection.max_tokens}
                  required
                />
              </Field>
            </div>
          </details>
        </Form>
      )}
    </div>
  );
}

import { useEffect, useState } from "preact/hooks";
import { api, field, numeric } from "@/lib/platform.ts";
import type { Job, Worker } from "@/lib/platform.ts";
import { useDraft } from "@/lib/workspace.ts";
import { readiness } from "@/lib/readiness.ts";
import { CredentialPicker } from "../CredentialPicker.tsx";
import { Field, Form, Notice } from "../PlatformUI.tsx";

export function AddModel(
  { onAdded, workers }: {
    workers: Worker[];
    onAdded: (job?: Job, connection?: string) => void;
  },
) {
  const [editingKey, setEditingKey] = useState(false);
  const availability = readiness("model_import", workers, []);
  const [draft, setDraft, restored] = useDraft("add-model", {
    source: "hf",
    repository: "",
    revision: "main",
    hfCredential: "",
    apiCredential: "",
    name: "",
    base_url: "",
    model: "",
    tools: false,
    context_length: "32768",
    max_tokens: "4096",
  });
  useEffect(() => {
    if (!restored) return;
    const url = new URL(location.href);
    if (url.searchParams.get("source") !== "api") return;
    setDraft((old) => ({ ...old, source: "api" }));
    url.searchParams.delete("source");
    history.replaceState({}, "", url);
  }, [restored]);
  const { source } = draft;
  const credential = source === "hf" ? draft.hfCredential : draft.apiCredential;
  const setCredential = (value: string) =>
    setDraft((old) => ({
      ...old,
      [source === "hf" ? "hfCredential" : "apiCredential"]: value,
    }));
  const edit = (name: keyof typeof draft, value: string | boolean) =>
    setDraft((old) => ({ ...old, [name]: value }));
  return (
    <section class="panel">
      <div class="panel-heading">
        <h2>Add a model</h2>
        <div class="scope-control" role="group" aria-label="Model source">
          <button
            type="button"
            class={`button ${source === "hf" ? "primary" : "secondary"}`}
            aria-pressed={source === "hf"}
            onClick={() => {
              if (source === "hf") return;
              edit("source", "hf");
              setEditingKey(false);
            }}
          >
            Hugging Face
          </button>
          <button
            type="button"
            class={`button ${source === "api" ? "primary" : "secondary"}`}
            aria-pressed={source === "api"}
            onClick={() => {
              if (source === "api") return;
              edit("source", "api");
              setEditingKey(false);
            }}
          >
            Existing API
          </button>
        </div>
      </div>
      <Form
        key={source}
        disabled={editingKey || (source === "hf" && !availability.available)}
        submit={source === "hf" ? "Download model" : "Save connection"}
        onSubmit={async (data) => {
          if (source === "hf") {
            const job = await api<Job>("/models/imports", "POST", {
              repository: field(data, "repository"),
              revision: field(data, "revision") || "main",
              credential_env: credential || null,
            });
            onAdded(job);
          } else {
            const result = await api<{ id: string }>("/connections", "POST", {
              name: field(data, "name"),
              base_url: field(data, "base_url"),
              model: field(data, "model"),
              api_key_env: credential || null,
              api_key: "",
              context_length: numeric(data, "context_length"),
              max_tokens: numeric(data, "max_tokens"),
              tools: data.has("tools"),
            });
            onAdded(undefined, result.id);
          }
        }}
      >
        {source === "hf"
          ? (
            <Field label="Hugging Face repository">
              <input
                name="repository"
                value={draft.repository}
                onInput={(e) => edit("repository", e.currentTarget.value)}
                placeholder="organization/model"
                pattern="[a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+"
                required
                autoFocus
              />
            </Field>
          )
          : (
            <div class="fields three">
              <Field label="Display name">
                <input
                  name="name"
                  value={draft.name}
                  onInput={(e) => edit("name", e.currentTarget.value)}
                  required
                  maxLength={80}
                />
              </Field>
              <Field label="API base URL">
                <input
                  name="base_url"
                  value={draft.base_url}
                  onInput={(e) => edit("base_url", e.currentTarget.value)}
                  type="url"
                  placeholder="https://provider.example/v1"
                  required
                />
              </Field>
              <Field label="Model identifier">
                <input
                  name="model"
                  value={draft.model}
                  onInput={(e) => edit("model", e.currentTarget.value)}
                  required
                  maxLength={200}
                />
              </Field>
            </div>
          )}
        <CredentialPicker
          onEditingChange={setEditingKey}
          value={credential}
          onChange={setCredential}
          label={source === "hf" ? "Hugging Face access" : "API key"}
          defaultName={source === "hf" ? "HF_TOKEN" : "MODEL_API_KEY"}
        />
        {source === "api" && (
          <label class="check-field">
            <input
              type="checkbox"
              name="tools"
              checked={draft.tools}
              onChange={(e) => edit("tools", e.currentTarget.checked)}
            />This model supports tool calling for harness benchmarks
          </label>
        )}
        <details class="advanced">
          <summary>Advanced settings</summary>
          {source === "hf"
            ? (
              <Field label="Revision">
                <input
                  name="revision"
                  value={draft.revision}
                  onInput={(e) => edit("revision", e.currentTarget.value)}
                />
              </Field>
            )
            : (
              <div class="fields two">
                <Field label="Context length">
                  <input
                    type="number"
                    name="context_length"
                    min={1024}
                    max={2097152}
                    value={draft.context_length}
                    onInput={(e) =>
                      edit("context_length", e.currentTarget.value)}
                    required
                  />
                </Field>
                <Field label="Maximum output tokens">
                  <input
                    type="number"
                    name="max_tokens"
                    min={16}
                    max={131072}
                    value={draft.max_tokens}
                    onInput={(e) => edit("max_tokens", e.currentTarget.value)}
                    required
                  />
                </Field>
              </div>
            )}
        </details>
        {source === "hf" && !availability.available && (
          <Notice>
            {availability.reason} <a href="/#workers">Inspect resources</a>
          </Notice>
        )}
        {source === "hf" && (
          <p class="muted">
            Downloading creates a reusable model artifact. You can train it
            directly or start a server after the files are ready.
          </p>
        )}
      </Form>
    </section>
  );
}

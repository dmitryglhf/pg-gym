import { useState } from "preact/hooks";
import { api, message } from "@/lib/platform.ts";
import { useResource } from "@/lib/query.ts";
import { Field, Notice } from "./PlatformUI.tsx";

type Environment = { revision: number; names: string[] };
export function CredentialPicker(
  {
    value,
    onChange,
    label = "API key",
    defaultName = "MODEL_API_KEY",
    onEditingChange,
    keepStoredKey = false,
  }: {
    value: string;
    onChange: (value: string) => void;
    label?: string;
    defaultName?: string;
    keepStoredKey?: boolean;
    onEditingChange?: (editing: boolean) => void;
  },
) {
  const environment = useResource<Environment>("/environment", 30000);
  const [adding, setAdding] = useState(false),
    [name, setName] = useState(defaultName),
    [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  return (
    <div class="credential-picker">
      <Field
        label={label}
        hint="Only this selected variable is used. Values stay on the server."
      >
        <select value={value} onChange={(e) => onChange(e.currentTarget.value)}>
          <option value="">No key / public access</option>
          {keepStoredKey && (
            <option value="__stored">Keep current stored key</option>
          )}
          {value && value !== "__stored" &&
            !environment.data?.names.includes(value) && (
            <option value={value}>{value}</option>
          )}
          {environment.data?.names.map((key) => <option key={key}>{key}
          </option>)}
        </select>
      </Field>
      {!adding && (
        <button
          type="button"
          class="text-button"
          onClick={() => {
            setAdding(true);
            onEditingChange?.(true);
          }}
        >
          + Add key here
        </button>
      )}
      {adding && (
        <div
          class="inline-credential"
          onKeyDown={(event) => {
            if (
              event.key === "Enter" && event.target instanceof HTMLInputElement
            ) event.preventDefault();
          }}
        >
          <div class="fields two">
            <Field label="Variable name">
              <input
                value={name}
                onInput={(e) => setName(e.currentTarget.value)}
                autoComplete="off"
              />
            </Field>
            <Field label="Secret value">
              <input
                type="password"
                value={secret}
                onInput={(e) => setSecret(e.currentTarget.value)}
                autoComplete="new-password"
              />
            </Field>
          </div>
          <div class="inline-actions">
            <button
              type="button"
              class="button secondary"
              disabled={busy || !secret ||
                !/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name)}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const current = await api<Environment>("/environment");
                  if (current.names.includes(name)) {
                    throw new Error(
                      "This name already exists. Choose the saved key or use a new name.",
                    );
                  }
                  await api("/environment", "PUT", {
                    revision: current.revision,
                    variables: {
                      ...Object.fromEntries(
                        current.names.map((key) => [key, null]),
                      ),
                      [name]: secret,
                    },
                  });
                  onChange(name);
                  setSecret("");
                  setAdding(false);
                  onEditingChange?.(false);
                  environment.refresh();
                } catch (cause) {
                  setError(message(cause));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Saving…" : "Save key"}
            </button>
            <button
              class="text-button"
              type="button"
              onClick={() => {
                setAdding(false);
                onEditingChange?.(false);
                setSecret("");
                setError("");
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {(error || environment.error) && (
        <Notice error>{error || environment.error}</Notice>
      )}
    </div>
  );
}

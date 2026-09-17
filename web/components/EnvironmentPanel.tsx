import { useEffect, useState } from "preact/hooks";
import { api, message } from "@/lib/platform.ts";
import { formatEnvironment, parseEnvironment } from "@/lib/environment.ts";
import { Field, Notice } from "./PlatformUI.tsx";
import { Icon } from "./Icon.tsx";

const EXAMPLE =
  "# Add your variables\nMODEL_API_KEY=\nHF_TOKEN=\nMODEL_BASE_URL=https://example.com/v1";
const MASKED_EXAMPLE =
  "MODEL_API_KEY=••••••••\nHF_TOKEN=••••••••\nMODEL_BASE_URL=••••••••";

type Row = { name: string; value: string | null };
type Metadata = { revision: number; names: string[] };
export function EnvironmentPanel({ onClose }: { onClose?: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [visible, setVisible] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [dirty, setDirty] = useState(false);
  async function reload() {
    if (
      dirty &&
      !confirm(
        "Discard your unsaved environment changes and reload saved values?",
      )
    ) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      install(await api<Metadata>("/environment"));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  function install(data: Metadata) {
    setRevision(data.revision);
    setRows(data.names.map((name) => ({ name, value: null })));
    setVisible(false);
    setText("");
    setLoaded(true);
    setDirty(false);
  }
  useEffect(() => {
    let stopped = false;
    api<Metadata>("/environment").then((data) => {
      if (!stopped) install(data);
    }).catch((cause) => {
      if (!stopped) setError(message(cause));
    });
    return () => {
      stopped = true;
    };
  }, []);
  useEffect(() => {
    function leave(event: BeforeUnloadEvent) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    }
    addEventListener("beforeunload", leave);
    return () => removeEventListener("beforeunload", leave);
  }, [dirty]);
  async function toggle() {
    setError("");
    if (visible) {
      try {
        setRows(
          Object.entries(parseEnvironment(text)).map(([name, value]) => ({
            name,
            value,
          })),
        );
        setVisible(false);
      } catch (cause) {
        setError(message(cause));
      }
      return;
    }
    setBusy(true);
    try {
      const saved = await api<
        { revision: number; variables: Record<string, string> }
      >("/environment/reveal", "POST");
      if (saved.revision !== revision) {
        throw new Error(
          "Environment changed in another session. Reload before editing.",
        );
      }
      const values: Record<string, string> = Object.create(null);
      for (const row of rows) {
        if (!row.name) {
          throw new Error(
            "Enter a name for each variable before opening the editor.",
          );
        }
        if (Object.hasOwn(values, row.name)) {
          throw new Error(`Duplicate variable ${row.name}.`);
        }
        values[row.name] = row.value ?? saved.variables[row.name] ?? "";
      }
      setText(formatEnvironment(values));
      setVisible(true);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section class="panel environment-panel">
      <div class="panel-heading">
        <div>
          <h2>Environment variables</h2>
          <p class="muted">
            Private variables for your account. Values are encrypted on the
            server.
          </p>
        </div>
        <div class="inline-actions">
          {onClose && (
            <button class="text-button" type="button" onClick={onClose}>
              Close
            </button>
          )}
          <button
            type="button"
            class="text-button"
            disabled={busy}
            onClick={reload}
          >
            {loaded ? "Reload saved values" : "Retry loading"}
          </button>
          <button
            type="button"
            class="button secondary"
            disabled={!loaded || busy}
            onClick={toggle}
          >
            <Icon name={visible ? "eyeOff" : "eye"} size={18} />
            {visible ? "Hide values" : "Show .env editor"}
          </button>
        </div>
      </div>
      {error && <Notice error>{error}</Notice>}
      {feedback && <Notice>{feedback}</Notice>}
      {!loaded
        ? (
          <p role="status">
            {error
              ? "Environment could not be loaded."
              : "Loading environment…"}
          </p>
        )
        : (
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              setFeedback("");
              try {
                let variables: Record<string, string | null>;
                if (visible) variables = parseEnvironment(text);
                else {
                  variables = Object.create(null);
                  for (const row of rows) {
                    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(row.name)) {
                      throw new Error(
                        "Use variable names such as MODEL_API_KEY.",
                      );
                    }
                    if (Object.hasOwn(variables, row.name)) {
                      throw new Error(`Duplicate variable ${row.name}.`);
                    }
                    variables[row.name] = row.value;
                  }
                }
                install(
                  await api<Metadata>("/environment", "PUT", {
                    revision,
                    variables,
                  }),
                );
                setFeedback("Environment saved. Values are hidden.");
              } catch (cause) {
                setError(message(cause));
              } finally {
                setBusy(false);
              }
            }}
          >
            <fieldset class="form-body" disabled={busy}>
              {visible
                ? (
                  <Field
                    label=".env editor"
                    hint="One KEY=VALUE per line. # comments and quoted values are supported. Values are literal: no shell commands or variable expansion."
                  >
                    <textarea
                      class="env-editor"
                      rows={12}
                      spellcheck={false}
                      autoComplete="off"
                      placeholder={EXAMPLE}
                      value={text}
                      onInput={(e) => {
                        setText(e.currentTarget.value);
                        setDirty(true);
                        setFeedback("");
                      }}
                    />
                  </Field>
                )
                : (
                  <>
                    {!rows.length && (
                      <div class="environment-placeholder">
                        <p>No variables saved yet.</p>
                        <pre>{MASKED_EXAMPLE}</pre>
                        <small>
                          Examples only. Choose Add variable or open the .env
                          editor.
                        </small>
                      </div>
                    )}
                    {rows.map((row, index) => (
                      <div class="environment-row" key={index}>
                        <Field label={`Variable ${index + 1}`}>
                          <input
                            aria-label={`Variable ${index + 1}`}
                            placeholder="VARIABLE_NAME"
                            value={row.name}
                            readOnly={row.value === null}
                            spellcheck={false}
                            autoComplete="off"
                            onInput={(e) => {
                              setRows(rows.map((r, i) =>
                                i === index
                                  ? { ...r, name: e.currentTarget.value }
                                  : r
                              ));
                              setDirty(true);
                            }}
                          />
                        </Field>
                        <Field label={`Value ${index + 1}`}>
                          <input
                            type="password"
                            placeholder={row.value === null
                              ? "Saved value (unchanged)"
                              : "Enter value"}
                            autoComplete="new-password"
                            value={row.value ?? ""}
                            onInput={(e) => {
                              setRows(rows.map((r, i) =>
                                i === index
                                  ? { ...r, value: e.currentTarget.value }
                                  : r
                              ));
                              setDirty(true);
                            }}
                          />
                        </Field>
                        <button
                          type="button"
                          class="button secondary"
                          aria-label={`Remove variable ${index + 1}`}
                          onClick={() => {
                            setRows(rows.filter((_, i) =>
                              i !== index
                            ));
                            setDirty(true);
                          }}
                        >
                          <Icon name="close" size={18} />
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      class="button secondary"
                      onClick={() => {
                        setRows([...rows, { name: "", value: "" }]);
                        setDirty(true);
                      }}
                    >
                      <Icon name="plus" size={16} />Add variable
                    </button>
                  </>
                )}
            </fieldset>
            <div class="form-actions">
              <span class="muted">
                {dirty ? "Unsaved changes" : "All changes saved"}
              </span>
              <button
                type="submit"
                class="button primary"
                disabled={busy || !dirty}
              >
                {busy ? "Saving…" : "Save environment"}
              </button>
            </div>
          </form>
        )}
    </section>
  );
}

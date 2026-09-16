import { useEffect, useState } from "preact/hooks";
import { api, date, field, message, numeric } from "@/lib/platform.ts";
import type { Connection } from "@/lib/platform.ts";
import type { Profile } from "./BenchmarkPanel.tsx";
import { Field, Form, Notice, usePoll } from "./PlatformUI.tsx";
import { EnvironmentPanel } from "./EnvironmentPanel.tsx";
import { SignOut } from "./SignOut.tsx";

export function SettingsPanel(
  { connections, profiles, refresh }: {
    connections: Connection[];
    profiles: Profile[];
    credentials: { id: string; name: string }[];
    refresh: () => void;
  },
) {
  const [edit, setEdit] = useState<Connection | null>(null),
    [profile, setProfile] = useState<Profile | null>(null),
    [feedback, setFeedback] = useState(""),
    [error, setError] = useState(""),
    [token, setToken] = useState("");
  const [tab, setTab] = useState(
    typeof location !== "undefined"
      ? new URLSearchParams(location.search).get("tab") || "connections"
      : "connections",
  );
  const [keyVariable, setKeyVariable] = useState("");
  useEffect(() => {
    setKeyVariable(edit?.api_key_env || (edit?.has_key ? "__stored" : ""));
  }, [edit]);
  const environment = usePoll<{ names: string[] }>("/environment");
  const tokens = usePoll<{ id: string; name: string; expires_at: number }[]>(
    "/api-tokens",
    5000,
  );
  const account = usePoll<{ username: string }>("/me", 60000);
  async function action(fn: () => Promise<unknown>, success: string) {
    setError("");
    setFeedback("");
    try {
      await fn();
      refresh();
      setFeedback(success);
    } catch (cause) {
      setError(message(cause));
    }
  }
  function remove(resource: string, id: string, name: string) {
    if (
      confirm(`Delete ${name}? Historical job configurations will be retained.`)
    ) action(() => api(`/${resource}/${id}`, "DELETE"), "Deleted");
  }
  return (
    <div class="settings-sections">
      <div class="page-tabs" role="group" aria-label="Settings view">
        {["connections", "environment", "harnesses", "account"].map((item) => (
          <button
            type="button"
            key={item}
            class={tab === item ? "selected" : ""}
            onClick={() => {
              setTab(item);
              const url = new URL(location.href);
              url.searchParams.set("tab", item);
              history.replaceState(null, "", url);
            }}
          >
            {item === "harnesses"
              ? "Harness profiles"
              : item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      <div hidden={tab !== "environment"}>
        <EnvironmentPanel />
      </div>
      {error && <Notice error>{error}</Notice>}
      {feedback && <Notice>{feedback}</Notice>}
      <section class="panel" hidden={tab !== "account"}>
        <div class="panel-heading">
          <div>
            <h2>Account</h2>
            <span class="muted">{account.data?.username}</span>
          </div>
          <SignOut className="button secondary" />
        </div>
      </section>
      <section class="panel" hidden={tab !== "connections"}>
        <div class="panel-heading">
          <h2>Model connections</h2>
        </div>
        <div class="settings-list">
          {connections.map((c) => (
            <div class="settings-row" key={c.id}>
              <div>
                <strong>{c.name}</strong>
                <small>{c.model} · {c.base_url}</small>
                <small>
                  {c.has_key ? "API key stored" : "No API key"}
                  {c.tools ? " · Tool calling enabled" : " · Chat only"}
                </small>
              </div>
              <div class="inline-actions">
                <button
                  type="button"
                  class="button secondary"
                  onClick={() =>
                    action(async () => {
                      const result = await api<
                        { ok: boolean; message: string }
                      >(`/connections/${c.id}/check`, "POST");
                      if (!result.ok) throw new Error(result.message);
                    }, "Model is reachable and listed by the server")}
                >
                  Test
                </button>
                {!c.managed_job_id && (
                  <button
                    type="button"
                    class="text-button"
                    onClick={() => setEdit(c)}
                  >
                    Edit
                  </button>
                )}
                <button
                  type="button"
                  class="text-button"
                  onClick={() => remove("connections", c.id, c.name)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
        <h3>{edit ? "Edit connection" : "Add connection"}</h3>
        <Form
          key={edit?.id || "new"}
          submit={edit ? "Save connection" : "Add connection"}
          onSubmit={async (data) => {
            await api(
              edit ? `/connections/${edit.id}` : "/connections",
              edit ? "PUT" : "POST",
              {
                name: field(data, "name"),
                base_url: field(data, "base_url"),
                model: field(data, "model"),
                api_key_env: field(data, "api_key_env") &&
                    field(data, "api_key_env") !== "__stored"
                  ? field(data, "api_key_env")
                  : null,
                ...(field(data, "api_key_env") === "__stored"
                  ? {}
                  : { api_key: "" }),
                context_length: numeric(data, "context_length"),
                max_tokens: numeric(data, "max_tokens"),
                tools: data.has("tools"),
              },
            );
            setEdit(null);
            refresh();
            return "Connection saved";
          }}
        >
          <div class="fields two">
            <Field label="Name">
              <input
                name="name"
                required
                maxLength={80}
                defaultValue={edit?.name}
              />
            </Field>
            <Field label="OpenAI-compatible API URL">
              <input
                name="base_url"
                type="url"
                required
                placeholder="http://host.docker.internal:8000/v1"
                defaultValue={edit?.base_url}
              />
            </Field>
            <Field label="Model identifier">
              <input
                name="model"
                required
                maxLength={200}
                defaultValue={edit?.model}
              />
            </Field>
            <Field
              label="API key variable"
              hint="Choose a saved Environment variable. Its value stays on the server."
            >
              <select
                name="api_key_env"
                value={keyVariable}
                onChange={(event) => setKeyVariable(event.currentTarget.value)}
              >
                <option value="">No authentication</option>
                {edit?.has_key && !edit.api_key_env && (
                  <option value="__stored">Keep stored key</option>
                )}
                {environment.data?.names.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </Field>
            <Field label="Context length">
              <input
                name="context_length"
                type="number"
                required
                min={1024}
                max={2097152}
                defaultValue={edit?.context_length || 32768}
              />
            </Field>
            <Field label="Maximum output tokens">
              <input
                name="max_tokens"
                type="number"
                required
                min={16}
                max={131072}
                defaultValue={edit?.max_tokens || 4096}
              />
            </Field>
          </div>
          <label class="check-field">
            <input name="tools" type="checkbox" defaultChecked={edit?.tools} />
            {" "}
            Supports tool calling for harnesses
          </label>
          {edit && (
            <button
              class="text-button"
              type="button"
              onClick={() => setEdit(null)}
            >
              Cancel edit
            </button>
          )}
        </Form>
      </section>
      <section class="panel" hidden={tab !== "harnesses"}>
        <div class="panel-heading">
          <h2>Harness profiles</h2>
        </div>
        <div class="settings-list">
          {profiles.map((p) => (
            <div class="settings-row" key={p.id}>
              <div>
                <strong>{p.name}</strong>
                <small>{p.harness} · {p.max_turns} turns · {p.timeout}s</small>
              </div>
              <div class="inline-actions">
                <button
                  type="button"
                  class="text-button"
                  onClick={() => setProfile(p)}
                >
                  Edit
                </button>
                <button
                  type="button"
                  class="text-button"
                  onClick={() => remove("harness-profiles", p.id, p.name)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
        <Form
          key={profile?.id || "new"}
          submit={profile ? "Save profile" : "Add profile"}
          onSubmit={async (data) => {
            await api(
              profile ? `/harness-profiles/${profile.id}` : "/harness-profiles",
              profile ? "PUT" : "POST",
              {
                name: field(data, "name"),
                harness: field(data, "harness"),
                max_turns: numeric(data, "max_turns"),
                timeout: numeric(data, "timeout"),
                temperature: numeric(data, "temperature"),
                context_strategy: field(data, "context_strategy"),
              },
            );
            setProfile(null);
            refresh();
            return "Profile saved";
          }}
        >
          <div class="fields three">
            <Field label="Name">
              <input
                name="name"
                required
                maxLength={80}
                defaultValue={profile?.name}
              />
            </Field>
            <Field label="Harness">
              <select name="harness">
                <option
                  value="markov"
                  selected={profile?.harness !== "opencode"}
                >
                  Markov
                </option>
                <option
                  value="opencode"
                  selected={profile?.harness === "opencode"}
                >
                  OpenCode
                </option>
              </select>
            </Field>
            <Field label="Maximum turns">
              <input
                name="max_turns"
                type="number"
                min={1}
                max={1000}
                required
                defaultValue={profile?.max_turns || 50}
              />
            </Field>
            <Field label="Timeout (seconds)">
              <input
                name="timeout"
                type="number"
                min={30}
                max={86400}
                required
                defaultValue={profile?.timeout || 1800}
              />
            </Field>
            <Field label="Temperature">
              <input
                name="temperature"
                type="number"
                min={0}
                max={1}
                step={0.1}
                required
                defaultValue={profile?.temperature || 0}
              />
            </Field>
            <Field label="Markov context strategy">
              <select name="context_strategy">
                <option selected={profile?.context_strategy !== "truncate"}>
                  summarize
                </option>
                <option selected={profile?.context_strategy === "truncate"}>
                  truncate
                </option>
              </select>
            </Field>
          </div>
          {profile && (
            <button
              type="button"
              class="text-button"
              onClick={() => setProfile(null)}
            >
              Cancel edit
            </button>
          )}
        </Form>
      </section>
      <section class="panel" hidden={tab !== "account"}>
        <div class="panel-heading">
          <h2>API tokens</h2>
        </div>
        <p class="muted">
          Use a token with pg-gym or a REST client. It grants access to your
          account until it expires or is revoked.
        </p>
        {tokens.data?.map((t) => (
          <div class="settings-row" key={t.id}>
            <div>
              <strong>{t.name}</strong>
              <small>Expires {date(t.expires_at)}</small>
            </div>
            <button
              type="button"
              class="text-button"
              onClick={() => remove("api-tokens", t.id, t.name)}
            >
              Revoke
            </button>
          </div>
        ))}
        <Form
          submit="Create token"
          onSubmit={async (data) => {
            const result = await api<{ token: string }>("/api-tokens", "POST", {
              name: field(data, "name"),
              days: numeric(data, "days"),
            });
            setToken(result.token);
          }}
        >
          <div class="fields two">
            <Field label="Name">
              <input name="name" defaultValue="CLI" required maxLength={80} />
            </Field>
            <Field label="Expires in days">
              <input
                name="days"
                type="number"
                defaultValue={30}
                min={1}
                max={365}
                required
              />
            </Field>
          </div>
        </Form>
        {token && (
          <div class="one-time-secret">
            <p>Copy this token now. It will not be displayed again.</p>
            <input
              aria-label="New API token"
              readOnly
              type="text"
              defaultValue={token}
              onFocus={(e) => e.currentTarget.select()}
            />
            <button
              type="button"
              class="text-button"
              onClick={() => setToken("")}
            >
              Dismiss
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

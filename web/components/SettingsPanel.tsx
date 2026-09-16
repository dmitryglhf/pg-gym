import { useState } from "preact/hooks";
import { api, date, field, message, numeric } from "@/lib/platform.ts";
import { useResource } from "@/lib/query.ts";
import { Field, Form, Notice } from "./PlatformUI.tsx";
import { SignOut } from "./SignOut.tsx";
export function SettingsPanel() {
  const [error, setError] = useState(""), [token, setToken] = useState("");
  const tokens = useResource<
    { id: string; name: string; expires_at: number }[]
  >("/api-tokens", 10000);
  const account = useResource<{ username: string }>("/me", 60000);
  async function remove(resource: string, id: string, name: string) {
    if (
      !confirm(`Revoke ${name}? Clients using this token will lose access.`)
    ) return;
    try {
      await api(`/${resource}/${id}`, "DELETE");
      setError("");
      tokens.refresh();
    } catch (cause) {
      setError(message(cause));
    }
  }
  return (
    <div class="settings-sections">
      <p class="muted">
        Model connections and provider keys live in{" "}
        <a href="/models">Models & servers</a>.{" "}
        <a href="/benchmark#profiles">Harness profiles</a> live with benchmarks.
      </p>
      {(error || tokens.error || account.error) && (
        <Notice error>{error || tokens.error || account.error}</Notice>
      )}
      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>Account</h2>
            <span class="muted">{account.data?.username}</span>
          </div>
          <SignOut className="button secondary" />
        </div>
      </section>
      <section class="panel">
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
            tokens.refresh();
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

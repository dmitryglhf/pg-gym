import { useEffect, useState } from "preact/hooks";
import {
  clearWorkspaceSession,
  readSession,
  writeSession,
} from "@/lib/workspace.ts";
import { api, field, message } from "@/lib/platform.ts";

export default function Login() {
  const [codeRequired, setCodeRequired] = useState(true);
  useEffect(() => {
    let stopped = false;
    api<{ registration_code_required: boolean }>("/auth/options").then(
      (data) => {
        if (!stopped) setCodeRequired(data.registration_code_required);
      },
    ).catch(() => {});
    return () => {
      stopped = true;
    };
  }, []);
  const [register, setRegister] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main id="main-content" class="login-page">
      <section class="login-card">
        <h1>{register ? "Create account" : "Sign in"}</h1>
        <form
          class="platform-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            const data = new FormData(event.currentTarget);
            const body = {
              username: field(data, "username"),
              password: field(data, "password"),
            };
            try {
              if (register) {
                await api("/auth/register", "POST", {
                  ...body,
                  invitation: field(data, "invitation"),
                });
              }
              await api("/auth/login", "POST", body);
              if (
                readSession("account-name", "") !== body.username
              ) clearWorkspaceSession();
              writeSession("account-name", body.username);
              location.assign("/");
            } catch (cause) {
              setError(message(cause));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label class="field">
            Username<input
              name="username"
              autoComplete="username"
              required
              minLength={3}
              maxLength={64}
              pattern="[a-zA-Z0-9_.-]+"
              autoFocus
            />
          </label>
          <label class="field">
            Password<input
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              required
              minLength={12}
              maxLength={256}
            />
          </label>
          {register && codeRequired && (
            <label class="field">
              Registration code<input
                name="invitation"
                type="password"
                autoComplete="off"
              />
              <small>Provided by the operator of this instance.</small>
            </label>
          )}
          {error && <p class="form-error" role="alert">{error}</p>}
          <button type="submit" class="button primary" disabled={busy}>
            {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
          </button>
        </form>
        <button
          type="button"
          class="text-button"
          onClick={() => {
            setRegister(!register);
            setError("");
          }}
        >
          {register ? "Already have an account? Sign in" : "Create an account"}
        </button>
      </section>
    </main>
  );
}

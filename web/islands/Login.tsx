import { useEffect, useRef, useState } from "preact/hooks";
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
  const [created, setCreated] = useState(false);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  return (
    <main id="main-content" class="login-page">
      <section class="login-card">
        <h1>{register ? "Create account" : "Sign in"}</h1>
        <form
          class="platform-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (submitting.current) return;
            submitting.current = true;
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
                setCreated(true);
                setRegister(false);
              }
              const account = await api<{ id: string; username: string }>(
                "/auth/login",
                "POST",
                body,
              );
              if (
                readSession("account-name", "").toLowerCase() !==
                  account.username.toLowerCase() ||
                !!readSession("account-id", "") &&
                  readSession("account-id", "") !== account.id
              ) clearWorkspaceSession();
              writeSession("account-name", account.username);
              writeSession("account-id", account.id);
              let destination = "/";
              try {
                const next = new URL(
                  new URLSearchParams(location.search).get("next") || "/",
                  location.origin,
                );
                if (
                  next.origin === location.origin && next.pathname !== "/login"
                ) destination = next.pathname + next.search + next.hash;
              } catch { /* Invalid return URLs lead to Workspace. */ }
              location.assign(destination);
            } catch (cause) {
              setError(message(cause));
            } finally {
              submitting.current = false;
              setBusy(false);
            }
          }}
        >
          <label class="field">
            Username<input
              disabled={busy}
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
              disabled={busy}
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
                disabled={busy}
                name="invitation"
                type="password"
                autoComplete="off"
              />
              <small>Provided by the operator of this instance.</small>
            </label>
          )}
          {created && (
            <p role="status">Your account is created. Sign in to continue.</p>
          )}
          {error && <p class="form-error" role="alert">{error}</p>}
          <button type="submit" class="button primary" disabled={busy}>
            {busy ? "Please wait…" : register ? "Create account" : "Sign in"}
          </button>
        </form>
        <button
          type="button"
          class="text-button"
          disabled={busy}
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

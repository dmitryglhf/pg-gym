import { Icon } from "./Icon.tsx";
import { useState } from "preact/hooks";
import { api, message } from "@/lib/platform.ts";

export function SignOut(
  { className = "quiet-button" }: { className?: string },
) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <button
        type="button"
        class={className}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await api("/auth/logout", "POST");
            location.assign("/login");
          } catch (cause) {
            setError(message(cause));
            setBusy(false);
          }
        }}
      >
        <Icon name="logout" size={20} />
        <span>{busy ? "Signing out…" : "Sign out"}</span>
      </button>
      {error && <span class="form-error" role="alert">{error}</span>}
    </>
  );
}

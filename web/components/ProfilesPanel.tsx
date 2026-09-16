import { useState } from "preact/hooks";
import { api, field, message, numeric } from "@/lib/platform.ts";
import type { Profile } from "./BenchmarkPanel.tsx";
import { Field, Form, Notice } from "./PlatformUI.tsx";
export function ProfilesPanel(
  { profiles, refresh }: { profiles: Profile[]; refresh: () => void },
) {
  const [profile, setProfile] = useState<Profile | null>(null),
    [error, setError] = useState("");
  async function remove(resource: string, id: string, name: string) {
    if (
      !confirm(
        `Delete ${name}? Existing runs retain their saved configuration.`,
      )
    ) return;
    try {
      await api(`/${resource}/${id}`, "DELETE");
      setError("");
      refresh();
    } catch (cause) {
      setError(message(cause));
    }
  }
  return (
    <>
      {error && <Notice error>{error}</Notice>}
      <section class="panel">
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
    </>
  );
}

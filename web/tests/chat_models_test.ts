/// <reference lib="dom" />
import { chatModels, modelSelection } from "../lib/chat-models.ts";
import type { Artifact, Connection, Job } from "../lib/platform.ts";

const base = {
  id: "base",
  name: "Base weights",
  kind: "model",
  status: "ready",
} as Artifact;
const adapter = {
  ...base,
  id: "adapter",
  name: "Trained weights",
  kind: "adapter",
} as Artifact;
const server = {
  id: "server",
  kind: "deployment",
  status: "running",
  created_at: 1,
  worker_connected: true,
  config: { artifact_id: base.id },
  result: { connection_id: "local" },
} as Job;
const connection = {
  id: "local",
  name: "Local server",
  managed_job_id: server.id,
  artifact_id: base.id,
} as Connection;
function assert(value: unknown, message: string) {
  if (!value) throw new Error(message);
}

Deno.test("chat catalog includes base weights and trained variants without running connections", () => {
  const models = chatModels([base, adapter], [], []);
  assert(models.length === 2, "Both local kinds must be selectable");
  assert(
    models[0].key === "artifact:base" && models[1].key === "artifact:adapter",
    "Selection must identify the model, not a transient server",
  );
  assert(models.every((model) => !model.usable), "Downloaded is not served");
});

Deno.test("chat catalog reconciles server identity without duplicate managed choices", () => {
  const models = chatModels([base], [connection], [server]);
  assert(models.length === 1, "The model and its connection are one choice");
  assert(
    models[0].usable && models[0].connection?.id === "local",
    "A ready server resolves to the actual chat connection",
  );
  assert(
    modelSelection("local", models, [connection], [server]) === "artifact:base",
    "Existing connection links must still select their model",
  );
  const legacy = { ...connection, artifact_id: undefined };
  assert(
    chatModels([base], [legacy], [server])[0].usable,
    "The deployment config also identifies the model for older connections",
  );
});

Deno.test("a failed server never hides downloaded weights or becomes a ready chat choice", () => {
  const models = chatModels([base], [connection], [{
    ...server,
    status: "failed",
  }]);
  assert(models.length === 1, "The downloaded model must remain visible");
  assert(!models[0].usable, "Failed server must not accept a chat");
  assert(!models[0].deployment, "Failed server must allow a fresh start");
  const lost = chatModels([base], [connection], [{
    ...server,
    worker_connected: false,
  }]);
  assert(!lost[0].usable, "Lost worker contact must not mean ready");
  assert(
    !!lost[0].deployment,
    "An active server must be reconciled, not duplicated",
  );
});

Deno.test("API connections and orphaned managed connections remain addressable", () => {
  const external = { id: "api", name: "API" } as Connection;
  const models = chatModels([], [external, connection], [server]);
  assert(
    models.length === 2,
    "Catalog failure must not hide known connections",
  );
  assert(
    models.every((model) => model.usable),
    "Both ready endpoints must work",
  );
  assert(
    modelSelection("api", models, [external, connection], [server]) === "api",
    "External connection identity must remain stable",
  );
  assert(
    modelSelection("removed", models, [external], []) === "removed",
    "Missing selections must remain visible as unavailable, not be silently replaced",
  );
});

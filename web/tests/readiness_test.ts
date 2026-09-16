/// <reference lib="dom" />
import { connectionStatus, readiness } from "../lib/readiness.ts";
import type { Connection, Job, Worker } from "../lib/platform.ts";
const worker = {
  id: "gpu-1",
  connected: true,
  capabilities: ["training", "deployment", "evaluation", "chat"],
} as Worker;
const server = {
  id: "serve-1",
  kind: "deployment",
  name: "Model server",
  worker_id: "gpu-1",
  worker_connected: true,
  status: "running",
  result: { connection_id: "connection-1" },
} as Job;
const connection = {
  id: "connection-1",
  managed_job_id: "serve-1",
} as Connection;
function assert(value: unknown, message: string) {
  if (!value) throw new Error(message);
}
Deno.test("a ready server occupies the GPU until terminal, but does not block chat capability", () => {
  assert(
    readiness("training", [worker], [server]).busy?.id === server.id,
    "Training must show the active server blocker",
  );
  assert(
    !readiness("chat", [worker], [server]).busy,
    "Chat must remain available through the server",
  );
  assert(
    !readiness("training", [worker], [{ ...server, status: "cancelled" }]).busy,
    "Completed server must release its slot",
  );
});
Deno.test("another eligible GPU worker prevents a false global busy state", () => {
  assert(
    !readiness("training", [worker, { ...worker, id: "gpu-2" }], [server]).busy,
    "One occupied worker must not block all workers",
  );
  assert(
    !readiness("training", [{ ...worker, connected: false }], []).available,
    "Offline workers cannot satisfy readiness",
  );
});
Deno.test("managed connection existence is not server readiness", () => {
  assert(
    !connectionStatus(connection, []).usable,
    "Unknown deployment cannot be ready",
  );
  assert(
    connectionStatus(connection, [server]).usable,
    "Ready running server should be usable",
  );
  assert(
    !connectionStatus(connection, [{ ...server, status: "failed" }]).usable,
    "Failed server retains its connection but is unusable",
  );
  assert(
    !connectionStatus(connection, [{ ...server, worker_connected: false }])
      .usable,
    "Lost heartbeat is not readiness",
  );
  assert(
    !connectionStatus(connection, [{ ...server, cancel_requested: true }])
      .usable,
    "Stopping server must be unavailable",
  );
});
Deno.test("queued deployment is waiting, not contact lost", () => {
  const state = connectionStatus(connection, [{
    ...server,
    status: "queued",
    worker_connected: false,
    result: null,
  }]);
  assert(
    state.label === "Waiting for a worker" && !state.usable,
    "Queued servers have no heartbeat yet",
  );
});

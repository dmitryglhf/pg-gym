import { terminal } from "./platform.ts";
import type { Connection, Job, Worker } from "./platform.ts";

export function readiness(kind: string, workers: Worker[], jobs: Job[]) {
  const candidates = workers.filter((worker) =>
    worker.connected && worker.capabilities.includes(kind)
  );
  if (!candidates.length) {
    return {
      available: false,
      busy: null,
      reason:
        `No connected worker advertises ${kind}. Open Workspace to inspect resources.`,
    };
  }
  const gpu = ["training", "evaluation", "deployment"].includes(kind);
  const occupied = (workerId: string) =>
    jobs.find((job) =>
      job.worker_id === workerId &&
      ["training", "evaluation", "deployment"].includes(job.kind) &&
      !terminal(job)
    );
  const blocking = gpu && candidates.every((worker) => occupied(worker.id))
    ? occupied(candidates[0].id)
    : undefined;
  return {
    available: true,
    busy: blocking || null,
    reason: blocking
      ? `GPU slot occupied by ${blocking.name}. ${
        blocking.kind === "deployment"
          ? "A running server keeps this slot until stopped."
          : "The new run can wait until it finishes."
      }`
      : `${candidates.length} connected worker${
        candidates.length > 1 ? "s" : ""
      } support this operation. Scheduling checks availability.`,
  };
}
export function connectionStatus(connection: Connection, deployments: Job[]) {
  if (!connection.managed_job_id) {
    return {
      usable: true,
      label: "External endpoint",
      detail:
        "Use Check to verify the endpoint. Tool calling is a declared capability.",
    };
  }
  const job = deployments.find((item) => item.id === connection.managed_job_id);
  if (!job) {
    return {
      usable: false,
      label: "Status unavailable",
      detail: "Waiting for the deployment status.",
    };
  }
  if (terminal(job)) {
    return {
      usable: false,
      label: job.status === "failed" ? "Server failed" : "Server stopped",
      detail: job.error ||
        "Start a server from the model card to create a new connection.",
    };
  }
  if (job.cancel_requested) {
    return {
      usable: false,
      label: "Stopping",
      detail: "Waiting for the server to release its resources.",
    };
  }
  if (job.status === "queued") {
    return {
      usable: false,
      label: "Waiting for a worker",
      detail: "The server has not started yet.",
    };
  }
  if (!job.worker_connected) {
    return {
      usable: false,
      label: "Contact lost",
      detail: "The last known state is not a health confirmation.",
    };
  }
  if (job.result?.connection_id) {
    return {
      usable: true,
      label: "Ready",
      detail:
        "Server reported readiness. A live connection check is available.",
    };
  }
  return {
    usable: false,
    label: job.status === "queued" ? "Waiting for a worker" : "Starting",
    detail: "The server has not reported readiness yet.",
  };
}

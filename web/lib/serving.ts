import { api } from "./platform.ts";
import type { Artifact, Job } from "./platform.ts";

export type ServerSettings = {
  name?: string;
  max_model_len?: number;
  gpu_memory_utilization?: number;
  tool_parser?: string;
};

/** Shared serving entry point for model management and the chat launch action. */
export function startModelServer(
  artifact: Artifact,
  settings: ServerSettings = {},
) {
  if (
    !["model", "adapter"].includes(artifact.kind) || artifact.status !== "ready"
  ) {
    throw new Error(
      "The model files must finish downloading before starting a server.",
    );
  }
  return api<Job>("/deployments", "POST", {
    artifact_id: artifact.id,
    name: settings.name ?? artifact.name.slice(0, 80),
    max_model_len: settings.max_model_len ?? 4096,
    gpu_memory_utilization: settings.gpu_memory_utilization ?? 0.85,
    tool_parser: settings.tool_parser ?? "",
  });
}

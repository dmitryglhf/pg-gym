import type { Artifact, Connection, Job } from "./platform.ts";
import { terminal } from "./platform.ts";
import { connectionStatus } from "./readiness.ts";

export type ChatModel = {
  key: string;
  name: string;
  label: string;
  artifact?: Artifact;
  connection?: Connection;
  deployment?: Job;
  usable: boolean;
};

/** Models are identities; a running connection is only their execution endpoint. */
export function chatModels(
  artifacts: Artifact[],
  connections: Connection[],
  deployments: Job[],
): ChatModel[] {
  const local = artifacts.filter((item) =>
    ["model", "adapter"].includes(item.kind)
  );
  const localIds = new Set(local.map((item) => item.id));
  const artifactFor = (connection: Connection) =>
    connection.artifact_id ||
    String(
      deployments.find((job) => job.id === connection.managed_job_id)?.config
        .artifact_id || "",
    );
  return [
    ...local.map((artifact) => {
      const servers = deployments.filter((job) =>
        job.config.artifact_id === artifact.id
      ).sort((a, b) => b.created_at - a.created_at);
      const connection = connections.find((item) =>
        artifactFor(item) === artifact.id &&
        connectionStatus(item, deployments).usable
      );
      const deployment = servers.find((job) =>
        job.id === connection?.managed_job_id
      ) || servers.find((job) => !terminal(job));
      const state = connection
        ? "Ready for chat"
        : deployment
        ? (deployment.cancel_requested
          ? "Stopping"
          : deployment.status === "queued"
          ? "Queued"
          : "Starting")
        : artifact.status === "ready"
        ? "Downloaded · server not running"
        : `Files ${artifact.status}`;
      return {
        key: "artifact:" + artifact.id,
        name: artifact.name,
        label: `${artifact.name} · ${state}`,
        artifact,
        connection,
        deployment,
        usable: !!connection,
      };
    }),
    ...connections.filter((item) =>
      !item.managed_job_id || !localIds.has(artifactFor(item))
    ).map((connection) => {
      const state = connectionStatus(connection, deployments);
      return {
        key: connection.id,
        name: connection.name,
        label: `${connection.name} · ${state.label}`,
        connection,
        usable: state.usable,
      };
    }),
  ];
}

/** Old links and drafts may refer to a managed connection instead of a model. */
export function modelSelection(
  value: string,
  models: ChatModel[],
  connections: Connection[],
  deployments: Job[],
) {
  if (models.some((model) => model.key === value)) return value;
  const connection = connections.find((item) => item.id === value);
  const artifactId = connection?.artifact_id ||
    deployments.find((job) => job.id === connection?.managed_job_id)?.config
      .artifact_id;
  const key = "artifact:" + artifactId;
  return models.some((model) => model.key === key) ? key : value;
}

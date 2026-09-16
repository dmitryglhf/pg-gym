import type { Artifact, Connection, Job, Worker } from "@/lib/platform.ts";
export type ModelsProps = {
  artifacts: Artifact[];
  connections: Connection[];
  deployments: Job[];
  jobs: Job[];
  workers: Worker[];
  refresh: () => void;
};

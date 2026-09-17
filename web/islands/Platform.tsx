import type {
  Artifact,
  Connection,
  Job,
  Suite,
  Worker,
} from "@/lib/platform.ts";
import { loadDeployments, useResource } from "@/lib/query.ts";
import { ConsolePanel } from "@/components/ConsolePanel.tsx";
import { WorkspacePanel } from "@/components/WorkspacePanel.tsx";
import { BenchmarkPanel } from "@/components/BenchmarkPanel.tsx";
import type { Profile } from "@/components/BenchmarkPanel.tsx";
import { TrainingPanel } from "@/components/TrainingPanel.tsx";
import { ModelsPanel } from "@/components/ModelsPanel.tsx";
import { InferencePanel } from "@/components/InferencePanel.tsx";
import { SettingsPanel } from "@/components/SettingsPanel.tsx";
import { ResultsPanel } from "@/components/ResultsPanel.tsx";
import { JobMonitor } from "@/components/JobMonitor.tsx";
import { Notice } from "@/components/PlatformUI.tsx";

/** Page composition only. Each resource loads and reports failures independently. */
export default function Platform({ page, id }: { page: string; id?: string }) {
  const needs = (...pages: string[]) => !id && pages.includes(page);
  const suites = useResource<Suite[]>(
    needs("home", "benchmark", "rl") ? "/suites" : null,
    60000,
  );
  const connections = useResource<Connection[]>(
    needs("home", "models", "inference", "benchmark") ? "/connections" : null,
  );
  const profiles = useResource<Profile[]>(
    needs("benchmark") ? "/harness-profiles" : null,
    30000,
  );
  const artifacts = useResource<Artifact[]>(
    needs("home", "models", "rl", "inference") ? "/artifacts" : null,
  );
  const capabilities = useResource<{ workers: Worker[] }>(
    needs("home", "models", "rl", "benchmark", "inference")
      ? "/capabilities"
      : null,
    15000,
  );
  // Job lists are the heaviest calls: fast only where jobs are the subject.
  const jobs = useResource<{ items: Job[]; next: string | null }>(
    needs(
        "home",
        "models",
        "rl",
        "benchmark",
        "results",
        "console",
        "inference",
      )
      ? "/jobs?limit=200"
      : null,
    needs("home", "results", "console") ? 5000 : 10000,
  );
  const deployments = useResource<Job[]>(
    needs("home", "models", "inference", "benchmark", "rl")
      ? "/jobs?kind=deployment&limit=200"
      : null,
    10000,
    loadDeployments,
  );
  const resources = {
    suites,
    connections,
    profiles,
    artifacts,
    capabilities,
    jobs,
    deployments,
  };
  const refresh = () =>
    Object.values(resources).forEach((resource) => resource.refresh());
  const errors = Object.entries(resources).filter(([, resource]) =>
    resource.error
  );
  const required: Record<string, (keyof typeof resources)[]> = {
    home: ["jobs"],
    models: ["artifacts", "connections"],
    inference: ["connections"],
    benchmark: ["suites", "connections"],
    rl: ["suites", "artifacts"],
    results: ["jobs"],
    console: ["jobs"],
    settings: [],
  };
  const loading = (required[page] || []).some((key) => !resources[key].data);
  const data = {
    suites: suites.data || [],
    connections: connections.data || [],
    profiles: profiles.data || [],
    artifacts: artifacts.data || [],
    workers: capabilities.data?.workers || [],
    jobs: jobs.data?.items || [],
    next: jobs.data?.next || null,
    deployments: deployments.data || [],
    refresh,
  };
  const title = ({
    home: "Workspace",
    benchmark: "Benchmarks",
    results: "Workspace",
    rl: "Training",
    models: "Models & servers",
    inference: "Inference",
    settings: "Account & access",
    console: "Console",
  } as Record<string, string>)[page];
  if (id) {
    return (
      <main id="main-content" class="wrap platform">
        <JobMonitor id={id} />
      </main>
    );
  }
  return (
    <main id="main-content" class="wrap platform">
      <div class="page-heading">
        <h1>{title}</h1>
        <a class="mobile-account" href="/settings">Account</a>
      </div>
      {(page === "home" || page === "results") && (
        <nav class="workspace-tabs" aria-label="Workspace view">
          <a href="/" aria-current={page === "home" ? "page" : undefined}>
            Overview
          </a>
          <a
            href="/results"
            aria-current={page === "results" ? "page" : undefined}
          >
            Runs & results
          </a>
        </nav>
      )}
      {errors.map(([name, resource]) => (
        <Notice error key={name}>
          {name}: {resource.error} {resource.data && (
            <span>
              Showing data received {resource.updated
                ? new Date(resource.updated).toLocaleTimeString()
                : "earlier"}.
            </span>
          )}
          <button type="button" class="text-button" onClick={resource.refresh}>
            Retry
          </button>
        </Notice>
      ))}
      {loading
        ? (
          <p class="loading-state" role="status">
            {errors.length
              ? "Waiting for required data. Retry the failed request above."
              : "Loading…"}
          </p>
        )
        : (
          <>
            {page === "home" && <WorkspacePanel {...data} />}
            {page === "models" && <ModelsPanel {...data} />}
            {page === "inference" && (
              <InferencePanel
                connections={data.connections}
                deployments={data.deployments}
                workers={data.workers}
                artifacts={data.artifacts}
                artifactsLoaded={artifacts.data !== null}
                jobs={data.jobs}
                refresh={refresh}
              />
            )}
            {page === "benchmark" && <BenchmarkPanel {...data} />}
            {page === "rl" && <TrainingPanel {...data} />}
            {page === "results" && (
              <ResultsPanel jobs={data.jobs} next={data.next} />
            )}
            {page === "console" && (
              <ConsolePanel jobs={data.jobs} next={data.next} />
            )}
            {page === "settings" && <SettingsPanel />}
          </>
        )}
    </main>
  );
}

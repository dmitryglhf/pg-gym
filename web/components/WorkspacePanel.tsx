import type {
  Artifact,
  Connection,
  Job,
  Suite,
  Worker,
} from "@/lib/platform.ts";
import { terminal } from "@/lib/platform.ts";
import { Icon } from "./Icon.tsx";
import { JobTable, Resources } from "./PlatformUI.tsx";

export function WorkspacePanel(
  { jobs, workers, connections, artifacts, suites }: {
    jobs: Job[];
    workers: Worker[];
    connections: Connection[];
    artifacts: Artifact[];
    suites: Suite[];
  },
) {
  const online = workers.filter((w) => w.connected);
  const active = jobs.filter((job) => !terminal(job));
  const ready = artifacts.filter((a) =>
    a.status === "ready" && ["model", "adapter"].includes(a.kind)
  );
  const benchmarkReady = online.some((w) =>
    w.capabilities.includes("benchmark")
  );
  const steps = [
    {
      done: connections.some((c) => c.tools),
      title: "Connect a model",
      description: "Add a model with tool calling to run agent benchmarks.",
      href: "/settings",
    },
    {
      done: benchmarkReady,
      title: "Prepare a benchmark worker",
      description:
        "A connected worker needs the PostgreSQL task image to run benchmarks.",
      href: "/settings#workers",
    },
    {
      done: jobs.some((j) => j.kind === "benchmark" && j.started_at !== null),
      title: "Run your first benchmark",
      description: "Start with one task, then evaluate a suite or split.",
      href: "/benchmark",
    },
  ];
  return (
    <div class="workspace-sections">
      <div class="workspace-stats">
        <div class="panel">
          <small>Active in recent jobs</small>
          <strong>{active.length}</strong>
          <a href="/results">
            View jobs <Icon name="arrow" size={14} />
          </a>
        </div>
        <div class="panel">
          <small>Workers online</small>
          <strong>
            {online.length}
            <span>/ {workers.length}</span>
          </strong>
          <a href="#workers">
            View resources <Icon name="arrow" size={14} />
          </a>
        </div>
        <div class="panel">
          <small>Model connections</small>
          <strong>{connections.length}</strong>
          <a href="/settings">
            Manage connections <Icon name="arrow" size={14} />
          </a>
        </div>
        <div class="panel">
          <small>Ready model artifacts</small>
          <strong>{ready.length}</strong>
          <a href="/inference?tab=models">
            Browse models <Icon name="arrow" size={14} />
          </a>
        </div>
      </div>
      {!steps.every((step) => step.done) && (
        <section class="panel">
          <div class="panel-heading">
            <h2>Get started</h2>
            <small>{steps.filter((s) => s.done).length} of 3 complete</small>
          </div>
          <div class="setup-grid">
            {steps.map((step, index) => (
              <a
                class={`setup-step ${step.done ? "complete" : ""}`}
                href={step.href}
                key={step.title}
              >
                <span class="step-number">
                  {step.done ? <Icon name="check" size={16} /> : index + 1}
                </span>
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.description}</p>
                  <small>{step.done ? "Complete" : "Set up →"}</small>
                </div>
              </a>
            ))}
          </div>
        </section>
      )}
      {jobs.length > 0 && (
        <section class="panel">
          <div class="panel-heading">
            <div>
              <h2>In progress</h2>
              <small>From the {jobs.length} most recent jobs</small>
            </div>
            <a class="button secondary" href="/console">
              <Icon name="terminal" size={16} /> Open console
            </a>
          </div>
          {active.length
            ? <JobTable jobs={active} />
            : (
              <div class="workspace-empty">
                <Icon name="pause" size={24} />
                <div>
                  <strong>No active jobs in this view</strong>
                  <p>
                    Start an experiment or explore your models. Progress will
                    appear here.
                  </p>
                </div>
              </div>
            )}
        </section>
      )}
      <div class="workspace-actions">
        <a href="/benchmark">
          <Icon name="play" />
          <div>
            <strong>Run a benchmark</strong>
            <small>
              {suites.reduce((n, s) => n + s.tasks, 0)} tasks across{" "}
              {suites.length} suites
            </small>
          </div>
          <Icon name="arrow" />
        </a>
        <a href="/rl">
          <Icon name="training" />
          <div>
            <strong>Train or evaluate</strong>
            <small>GRPO training and held-out evaluation</small>
          </div>
          <Icon name="arrow" />
        </a>
        <a href="/inference">
          <Icon name="chat" />
          <div>
            <strong>Open inference</strong>
            <small>Chat, import models and manage servers</small>
          </div>
          <Icon name="arrow" />
        </a>
      </div>
      <section class="panel">
        <div class="panel-heading">
          <h2>Recent runs</h2>
          <a href="/results">View all →</a>
        </div>
        {jobs.length
          ? <JobTable jobs={jobs.slice(0, 6)} />
          : (
            <div class="workspace-empty">
              <Icon name="clock" size={24} />
              <div>
                <strong>Your experiment history starts here</strong>
                <p>
                  Completed runs will include their status, results and
                  execution logs.
                </p>
              </div>
            </div>
          )}
      </section>
      <div id="workers">
        <Resources workers={workers} />
      </div>
    </div>
  );
}

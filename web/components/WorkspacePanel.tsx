import type {
  Artifact,
  Connection,
  Job,
  Suite,
  Worker,
} from "@/lib/platform.ts";
import { terminal } from "@/lib/platform.ts";
import { connectionStatus, readiness } from "@/lib/readiness.ts";
import { openActivity, preparationHref, useDraft } from "@/lib/workspace.ts";
import { Icon } from "./Icon.tsx";
import { JobTable, Resources } from "./PlatformUI.tsx";

export function WorkspacePanel(
  { jobs, workers, connections, artifacts, suites, deployments }: {
    jobs: Job[];
    workers: Worker[];
    connections: Connection[];
    artifacts: Artifact[];
    suites: Suite[];
    deployments: Job[];
  },
) {
  const [goal, setGoal] = useDraft("workspace-goal", "benchmark");
  const online = workers.filter((item) => item.connected);
  const active = [
    ...new Map(
      [...jobs, ...deployments].filter((job) => !terminal(job)).map((
        job,
      ) => [job.id, job]),
    ).values(),
  ];
  const models = artifacts.filter((item) =>
    item.status === "ready" && item.kind === "model"
  );
  const usable = connections.filter((item) =>
    connectionStatus(item, deployments).usable
  );
  const preparation = goal === "training"
    ? models.length > 0
    : usable.some((item) => goal !== "benchmark" || item.tools);
  const capability = readiness(goal === "inference" ? "chat" : goal, workers, [
    ...deployments,
    ...jobs,
  ]);
  const steps = [
    {
      done: preparation,
      title: goal === "training"
        ? "Download base model weights"
        : "Prepare a model connection",
      description: goal === "training"
        ? "Training uses weights directly; no inference server is needed."
        : goal === "benchmark"
        ? "Use an external API or a local server with tool calling."
        : "Use a ready local server or connect an external API.",
      href: preparationHref(
        goal === "training"
          ? "training"
          : goal === "inference"
          ? "inference"
          : "benchmark",
      ),
    },
    {
      done: capability.available && !capability.busy,
      title: "Check execution resources",
      description: capability.reason,
      href: "#workers",
    },
    {
      done: false,
      title: goal === "training"
        ? "Configure training"
        : goal === "inference"
        ? "Open a conversation"
        : "Choose a benchmark task",
      description:
        "Continue in the task screen. Its draft is saved when you leave.",
      href: goal === "training"
        ? "/rl"
        : goal === "inference"
        ? "/inference"
        : "/benchmark",
    },
  ];
  return (
    <div class="workspace-sections">
      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>What would you like to do?</h2>
            <p class="muted">Prepare once, then move between experiments.</p>
          </div>
          <div class="scope-control" role="group" aria-label="Workspace goal">
            {[["inference", "Chat"], ["benchmark", "Benchmark"], [
              "training",
              "Train",
            ]].map(([value, label]) => (
              <button
                type="button"
                key={value}
                class={`button ${goal === value ? "primary" : "secondary"}`}
                aria-pressed={goal === value}
                onClick={() => setGoal(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div class="setup-grid">
          {steps.map((step, index) => (
            <a
              key={step.title}
              class={`setup-step ${step.done ? "complete" : ""}`}
              href={step.href}
            >
              <span class="step-number">
                {step.done ? <Icon name="check" size={16} /> : index + 1}
              </span>
              <div>
                <strong>{step.title}</strong>
                <p>{step.description}</p>
                <small>
                  {step.done ? "Available · manage →" : "Continue →"}
                </small>
              </div>
            </a>
          ))}
        </div>
      </section>
      <div class="workspace-stats">
        <div class="panel">
          <small>Available connections</small>
          <strong>{usable.length}</strong>
          <a href="/models">Models & servers →</a>
        </div>
        <div class="panel">
          <small>Base models downloaded</small>
          <strong>{models.length}</strong>
          <a href="/models">Files & variants →</a>
        </div>
        <div class="panel">
          <small>Workers connected</small>
          <strong>
            {online.length}
            <span>/ {workers.length}</span>
          </strong>
          <a href="#workers">Resources →</a>
        </div>
        <div class="panel">
          <small>Runnable tasks</small>
          <strong>{suites.reduce((sum, suite) => sum + suite.tasks, 0)}</strong>
          <a href="/benchmark">Browse tasks →</a>
        </div>
      </div>
      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>In progress</h2>
            <small>Recent {jobs.length} runs and known deployments</small>
          </div>
          <button
            type="button"
            class="button secondary"
            onClick={() => openActivity()}
          >
            <Icon name="terminal" size={16} />Open console
          </button>
        </div>
        {active.length ? <JobTable jobs={active} /> : (
          <p class="empty-state">
            No active runs in this view. Start a chat, benchmark or training run
            above.
          </p>
        )}
      </section>
      <section class="panel">
        <div class="panel-heading">
          <h2>Recent runs</h2>
          <a href="/results">All runs & results →</a>
        </div>
        <JobTable jobs={jobs.slice(0, 6)} />
      </section>
      <div id="workers">
        <Resources workers={workers} />
      </div>
    </div>
  );
}

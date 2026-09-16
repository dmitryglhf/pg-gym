import { useEffect, useRef, useState } from "preact/hooks";
import { api, message } from "@/lib/platform.ts";
import type { Artifact, Job, Suite, Worker } from "@/lib/platform.ts";
import { readiness } from "@/lib/readiness.ts";
import { preparationHref, useDraft } from "@/lib/workspace.ts";
import { Field, Form, Notice } from "./PlatformUI.tsx";
import { OperationCard } from "./OperationCard.tsx";

type Parameters = {
  seed: number;
  max_completion_length: number;
  steps: number;
  learning_rate: number;
  group_size: number;
  batch_size: number;
  rank: number;
  num_layers: number;
  max_prompt_length: number;
  beta: number;
  checkpoint_every: number;
  keep_checkpoints: number;
};
const defaults: Parameters = {
  seed: 42,
  max_completion_length: 2048,
  steps: 20,
  learning_rate: 0.00001,
  group_size: 2,
  batch_size: 1,
  rank: 8,
  num_layers: 16,
  max_prompt_length: 4096,
  beta: 0.001,
  checkpoint_every: 10,
  keep_checkpoints: 3,
};
const fields: {
  key: keyof Parameters;
  label: string;
  min: number;
  max: number;
  step?: string;
  basic?: boolean;
  shared?: boolean;
  hint?: string;
}[] = [
  { key: "steps", label: "Training steps", min: 1, max: 100000, basic: true },
  {
    key: "learning_rate",
    label: "Learning rate",
    min: 1e-9,
    max: 0.01,
    step: "any",
  },
  { key: "group_size", label: "Group size", min: 2, max: 64 },
  {
    key: "max_completion_length",
    label: "Output token limit",
    min: 32,
    max: 32768,
    shared: true,
  },
  { key: "seed", label: "Seed", min: 0, max: 2147483647, shared: true },
  {
    key: "batch_size",
    label: "Batch size",
    min: 1,
    max: 64,
    hint: "Must divide the group size.",
  },
  { key: "rank", label: "LoRA rank", min: 1, max: 256 },
  { key: "num_layers", label: "Last layers to train", min: 1, max: 256 },
  {
    key: "max_prompt_length",
    label: "Prompt token limit",
    min: 128,
    max: 131072,
    hint: "Oversized tasks are excluded, never truncated.",
  },
  { key: "beta", label: "KL weight (beta)", min: 0, max: 1, step: "any" },
  { key: "checkpoint_every", label: "Save every N steps", min: 1, max: 10000 },
  { key: "keep_checkpoints", label: "Keep checkpoints", min: 1, max: 20 },
];
export function TrainingPanel(
  { artifacts, suites, jobs, deployments, workers, refresh }: {
    artifacts: Artifact[];
    suites: Suite[];
    jobs: Job[];
    deployments: Job[];
    workers: Worker[];
    refresh: () => void;
  },
) {
  const [draft, setDraft, restored] = useDraft("training", {
    mode: "train",
    suite: suites[0]?.id || "",
    split: "train",
    artifact: "",
    name: "",
    ...defaults,
  });
  const [pending, setPending] = useDraft("training-pending", "");
  const [queue, setQueue] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [cloning, setCloning] = useState(false);
  const initialized = useRef(false);
  useEffect(() => {
    if (!restored || initialized.current) return;
    initialized.current = true;
    const query = new URLSearchParams(location.search),
      artifact = query.get("artifact"),
      mode = query.get("mode"),
      clone = query.get("clone");
    if (artifact || mode) {
      setDraft((old) => ({
        ...old,
        artifact: artifact || old.artifact,
        mode: ["train", "evaluate"].includes(mode || "") ? mode! : old.mode,
        split: mode === "evaluate"
          ? "test"
          : mode === "train"
          ? "train"
          : old.split,
      }));
    }
    if (clone) {
      setCloning(true);
      api<Job>("/jobs/" + encodeURIComponent(clone)).then((job) => {
        if (!["training", "evaluation"].includes(job.kind)) {
          throw new Error("This run is not training or evaluation.");
        }
        const parameters = { ...defaults };
        for (const item of fields) {
          if (typeof job.config[item.key] === "number") {
            parameters[item.key] = Number(job.config[item.key]);
          }
        }
        setDraft({
          ...parameters,
          mode: job.kind === "training" ? "train" : "evaluate",
          suite: job.config.suite || "",
          split: String(job.config.split || ""),
          artifact: job.config.artifact_id || "",
          name: (job.name + " · copy").slice(0, 100),
        });
        query.delete("clone");
        history.replaceState({}, "", "/rl" + (query.size ? "?" + query : ""));
      }).catch((cause) => setError(message(cause))).finally(() =>
        setCloning(false)
      );
    }
  }, [restored]);
  const train = draft.mode === "train";
  const splits =
    suites.find((item) => item.id === draft.suite)?.splits.filter((split) =>
      !train || split !== "test"
    ) || [];
  const models = artifacts.filter((item) =>
    item.status === "ready" &&
    (item.kind === "model" || (!train && item.kind === "adapter"))
  );
  const worker = readiness(train ? "training" : "evaluation", workers, [
    ...deployments,
    ...jobs,
  ]);
  const valid = models.some((item) => item.id === draft.artifact) &&
    splits.includes(draft.split) &&
    (!train || draft.group_size % draft.batch_size === 0);
  function input(item: typeof fields[number]) {
    return (
      <Field key={item.key} label={item.label} hint={item.hint}>
        <input
          type="number"
          min={item.min}
          max={item.max}
          step={item.step || 1}
          required
          value={draft[item.key]}
          onInput={(event) =>
            setDraft({
              ...draft,
              [item.key]: Number(event.currentTarget.value),
            })}
        />
      </Field>
    );
  }
  return (
    <div class="workspace-sections">
      {pending && <OperationCard id={pending} onComplete={refresh} />}
      <section class="panel">
        <div class="panel-heading">
          <h2>{train ? "Train with GRPO" : "Evaluate a model"}</h2>
          <a href={preparationHref("training", draft.artifact)}>
            Prepare a model
          </a>
        </div>
        <div class="scope-control" role="group" aria-label="Training view">
          {[["train", "Train"], ["evaluate", "Evaluate"]].map((
            [mode, label],
          ) => (
            <button
              type="button"
              key={mode}
              class={`button ${draft.mode === mode ? "primary" : "secondary"}`}
              aria-pressed={draft.mode === mode}
              onClick={() => {
                setDraft({
                  ...draft,
                  mode,
                  split: mode === "train" ? "train" : "test",
                });
                setQueue(false);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <p class="muted">
          {train
            ? "Training uses downloaded model weights directly. A running inference server is not required."
            : "Evaluate direct patch generation on a saved model or adapter. Harness-based measurements are in Benchmarks."}
        </p>
        {error && <Notice error>{error}</Notice>}
        {(!models.some((item) => item.id === draft.artifact) ||
          !splits.includes(draft.split)) && (
          <Notice>
            Select an available {train ? "base model" : "model or adapter"}{" "}
            and a valid suite split to continue.
          </Notice>
        )}
        <Form
          submit={worker.busy && queue
            ? (train ? "Queue training" : "Queue evaluation")
            : train
            ? "Start training"
            : "Start evaluation"}
          disabled={!restored || cloning || !valid || !worker.available ||
            (!!worker.busy && !queue) || busy}
          onSubmit={async () => {
            const config: Record<string, unknown> = {
              artifact_id: draft.artifact,
              suite: draft.suite,
              split: draft.split,
              name: draft.name ||
                (train ? "GRPO training" : "Held-out evaluation"),
              seed: draft.seed,
              max_completion_length: draft.max_completion_length,
            };
            if (train) {
              for (const item of fields) {
                config[item.key] = draft[item.key];
              }
            }
            const job = await api<Job>(
              train ? "/training-runs" : "/evaluations",
              "POST",
              config,
            );
            setPending(job.id);
            refresh();
            setQueue(false);
          }}
        >
          <div class="fields two">
            <Field label={train ? "Base model" : "Model / adapter"}>
              <select
                required
                value={draft.artifact}
                onChange={(event) =>
                  setDraft({ ...draft, artifact: event.currentTarget.value })}
              >
                <option value="">Select downloaded weights</option>
                {models.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.kind} · {item.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Experiment name">
              <input
                maxLength={100}
                value={draft.name}
                placeholder={train ? "GRPO training" : "Held-out evaluation"}
                onInput={(event) =>
                  setDraft({ ...draft, name: event.currentTarget.value })}
              />
            </Field>
            <Field label="Suite">
              <select
                required
                value={draft.suite}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    suite: event.currentTarget.value,
                    split: "",
                  })}
              >
                <option value="">Select a suite</option>
                {suites.map((item) => <option key={item.id}>{item.id}</option>)}
              </select>
            </Field>
            <Field label="Split">
              <select
                required
                value={draft.split}
                onChange={(event) =>
                  setDraft({ ...draft, split: event.currentTarget.value })}
              >
                <option value="">Select a split</option>
                {splits.map((split) => <option key={split}>{split}</option>)}
              </select>
            </Field>
          </div>
          {!models.length && (
            <Notice>
              <a href={preparationHref("training")}>Download a model</a>{" "}
              to continue. External API connections cannot provide weights for
              training.
            </Notice>
          )}
          {train && (
            <div class="fields three">
              {fields.filter((item) => item.basic).map(input)}
            </div>
          )}
          <details class="advanced">
            <summary>Generation {train && "and LoRA"} parameters</summary>
            <div class="fields three">
              {fields.filter((item) => !item.basic && (train || item.shared))
                .map(input)}
            </div>
          </details>
          {train && draft.group_size % draft.batch_size !== 0 && (
            <Notice error>Group size must be divisible by batch size.</Notice>
          )}
          <Notice>
            {worker.reason}{" "}
            {!worker.available && <a href="/#workers">Inspect resources</a>}
          </Notice>
          {worker.busy && (
            <div class="gpu-resolution">
              <a href={`/jobs/${worker.busy.id}`}>Inspect {worker.busy.name}</a>
              {worker.busy.kind === "deployment" && (
                <button
                  type="button"
                  class="button secondary"
                  disabled={busy || worker.busy.cancel_requested}
                  onClick={async () => {
                    if (
                      !confirm(
                        "Stop this server to release the GPU? Active chats and benchmarks using it can fail. Existing chat history remains available.",
                      )
                    ) return;
                    setBusy(true);
                    try {
                      await api(`/deployments/${worker.busy!.id}/stop`, "POST");
                      refresh();
                    } catch (cause) {
                      setError(message(cause));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  {worker.busy.cancel_requested
                    ? "Server stopping…"
                    : "Stop server to free GPU"}
                </button>
              )}
              <label class="check-field">
                <input
                  type="checkbox"
                  checked={queue}
                  onChange={(event) => setQueue(event.currentTarget.checked)}
                />Queue until the GPU is released
              </label>
            </div>
          )}
          <p class="muted">
            {train
              ? "The test split is reserved for evaluation. Training creates an adapter; it does not replace the base model."
              : "Direct-generation results and agentic benchmark results use different protocols and are not directly comparable."}
          </p>
        </Form>
      </section>
    </div>
  );
}

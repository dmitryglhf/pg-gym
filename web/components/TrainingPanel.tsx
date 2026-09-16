import { useState } from "preact/hooks";
import { api, field, numeric } from "@/lib/platform.ts";
import type { Artifact, Job, Suite } from "@/lib/platform.ts";
import { ArtifactSelect, Field, Form, Notice } from "./PlatformUI.tsx";

export function TrainingPanel(
  { artifacts, suites }: { artifacts: Artifact[]; suites: Suite[] },
) {
  const [mode, setMode] = useState(
      typeof location !== "undefined" &&
        new URLSearchParams(location.search).get("mode") === "evaluate"
        ? "evaluate"
        : "train",
    ),
    [suite, setSuite] = useState(suites[0]?.id || "");
  const splits =
    suites.find((s) => s.id === suite)?.splits.filter((s) =>
      mode !== "train" || s !== "test"
    ) || [];
  return (
    <section class="panel">
      <div class="panel-heading">
        <h2>{mode === "train" ? "Train with GRPO" : "Evaluate a model"}</h2>
        <div class="scope-control">
          <button
            type="button"
            class={`button ${mode === "train" ? "primary" : "secondary"}`}
            onClick={() => setMode("train")}
          >
            Train
          </button>
          <button
            type="button"
            class={`button ${mode === "evaluate" ? "primary" : "secondary"}`}
            onClick={() => setMode("evaluate")}
          >
            Evaluate
          </button>
        </div>
      </div>
      <Form
        key={mode}
        submit={mode === "train" ? "Start training" : "Start evaluation"}
        disabled={!splits.length}
        onSubmit={async (data) => {
          const config: Record<string, unknown> = {
            artifact_id: field(data, "artifact_id"),
            suite,
            split: field(data, "split"),
            name: field(data, "name"),
            seed: numeric(data, "seed"),
            max_completion_length: numeric(data, "max_completion_length"),
          };
          if (mode === "train") {
            for (
              const key of [
                "steps",
                "learning_rate",
                "group_size",
                "batch_size",
                "rank",
                "num_layers",
                "max_prompt_length",
                "beta",
                "checkpoint_every",
                "keep_checkpoints",
              ]
            ) config[key] = numeric(data, key);
          }
          const job = await api<Job>(
            mode === "train" ? "/training-runs" : "/evaluations",
            "POST",
            config,
          );
          location.assign(`/jobs/${job.id}`);
        }}
      >
        <div class="fields two">
          <Field label={mode === "train" ? "Base model" : "Model / adapter"}>
            <ArtifactSelect
              artifacts={artifacts}
              modelsOnly={mode === "train"}
              initial={typeof location !== "undefined"
                ? new URLSearchParams(location.search).get("artifact") || ""
                : ""}
            />
          </Field>
          <Field label="Experiment name">
            <input
              required
              name="name"
              maxLength={100}
              defaultValue={mode === "train"
                ? "GRPO training"
                : "Held-out evaluation"}
            />
          </Field>
          <Field label="Suite">
            <select
              value={suite}
              onChange={(e) => setSuite(e.currentTarget.value)}
            >
              {suites.map((s) => <option value={s.id} key={s.id}>{s.id}
              </option>)}
            </select>
          </Field>
          <Field label="Split">
            <select
              key={suite + mode}
              name="split"
              required
            >
              {splits.map((s) => (
                <option
                  key={s}
                  selected={s === (mode === "train" ? "train" : "test")}
                >
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {mode === "train" && (
          <div class="fields three">
            <Field label="Training steps">
              <input
                name="steps"
                type="number"
                min={1}
                max={100000}
                defaultValue={20}
                required
              />
            </Field>
            <Field label="Learning rate">
              <input
                name="learning_rate"
                type="number"
                step="any"
                min={0.000000001}
                max={0.01}
                defaultValue={0.00001}
                required
              />
            </Field>
            <Field label="Group size">
              <input
                name="group_size"
                type="number"
                min={2}
                max={64}
                defaultValue={2}
                required
              />
            </Field>
          </div>
        )}
        <details class="advanced">
          <summary>
            Generation {mode === "train" && "and LoRA"} parameters
          </summary>
          <div class="fields three">
            <Field label="Output token limit">
              <input
                name="max_completion_length"
                type="number"
                min={32}
                max={32768}
                defaultValue={2048}
                required
              />
            </Field>
            <Field label="Seed">
              <input
                name="seed"
                type="number"
                min={0}
                max={2147483647}
                defaultValue={42}
                required
              />
            </Field>
            {mode === "train" && (
              <>
                <Field label="Batch size" hint="Must divide the group size.">
                  <input
                    name="batch_size"
                    type="number"
                    min={1}
                    max={64}
                    defaultValue={1}
                    required
                  />
                </Field>
                <Field label="LoRA rank">
                  <input
                    name="rank"
                    type="number"
                    min={1}
                    max={256}
                    defaultValue={8}
                    required
                  />
                </Field>
                <Field label="Last layers to train">
                  <input
                    name="num_layers"
                    type="number"
                    min={1}
                    max={256}
                    defaultValue={16}
                    required
                  />
                </Field>
                <Field
                  label="Prompt token limit"
                  hint="Oversized tasks are excluded, never truncated."
                >
                  <input
                    name="max_prompt_length"
                    type="number"
                    min={128}
                    max={131072}
                    defaultValue={4096}
                    required
                  />
                </Field>
                <Field label="KL weight (beta)">
                  <input
                    name="beta"
                    type="number"
                    step="any"
                    min={0}
                    max={1}
                    defaultValue={0.001}
                    required
                  />
                </Field>
                <Field label="Save every N steps">
                  <input
                    name="checkpoint_every"
                    type="number"
                    min={1}
                    max={10000}
                    defaultValue={10}
                    required
                  />
                </Field>
                <Field label="Keep checkpoints">
                  <input
                    name="keep_checkpoints"
                    type="number"
                    min={1}
                    max={20}
                    defaultValue={3}
                    required
                  />
                </Field>
              </>
            )}
          </div>
        </details>
        <Notice>
          {mode === "train"
            ? "GRPO trains direct patch generation against the selected suite. The test split is reserved for evaluation."
            : "This measures direct patch generation on held-out tasks. Use Benchmark to measure the same model inside Markov or OpenCode."}
        </Notice>
      </Form>
    </section>
  );
}

# Training

The platform trains direct patch generation. The model sees a task prompt and the relevant source, writes a patch, and the patch is built and tested in a disposable container. The test outcome is the reward, and GRPO uses it to update a LoRA adapter.

```sh
pg-gym --timeout 86400 rl train MODEL_ID --suite sql-function-set --split train --wait
pg-gym --timeout 86400 rl train --config training.json --wait
```

The job runs on the GPU worker and produces an adapter artifact whose manifest points back at the base model and the run. Checkpoints are written on the worker along the way, but only a finished run publishes its adapter.

## The specification

```json
{
  "name": "coder-3b grpo",
  "artifact_id": "MODEL_ID",
  "suite": "sql-function-set",
  "split": "train",
  "steps": 200,
  "learning_rate": 1e-5,
  "group_size": 4,
  "batch_size": 1,
  "rank": 8,
  "num_layers": 16,
  "max_completion_length": 2048,
  "max_prompt_length": 4096,
  "beta": 0.001,
  "checkpoint_every": 10,
  "keep_checkpoints": 3,
  "seed": 42
}
```

`group_size` is how many completions are sampled per prompt and compared against each other, which is what the G in GRPO stands for. `rank` and `num_layers` size the LoRA adapter. `beta` is the KL penalty against the base model. `checkpoint_every` and `keep_checkpoints` bound how much disk a run holds.

GRPO assumes a decoder model whose modules match the library's LoRA targets. Arbitrary architectures and models that need custom code are not supported.

## What the reward is not

The reward curve on the job page is computed on training tasks while the policy is changing. It tells you the optimiser is working. It does not tell you how the model does on tasks it has not seen. For that, evaluate.

```sh
pg-gym --timeout 86400 rl evaluate ADAPTER_ID --suite sql-function-set --split test --wait
```

Evaluation is a separate job under the `direct-diff-evaluation.v1` protocol. It runs the base model or the adapter on the held-out split with sampling fixed by `seed`, builds every patch and reports the solve rate. Evaluate the base model the same way to have a baseline.

Neither number is an agentic benchmark. To see how the trained model behaves with tools, deploy it and run a benchmark through OpenCode or the Goose-based harness, see [Models and inference](inference.md) and [Benchmarks](benchmarks.md).

## The GPU

One training, evaluation or serving job holds the worker's GPU at a time. A queued job waits for the current one. Stop a deployment before a training run, and expect a job that was cancelled while grading to keep the GPU reserved until its task containers are cleaned up.

Cancellation during training leaves the local checkpoints on the worker without publishing them, and there is no automatic resume. Do not remove worker storage while a job is active.

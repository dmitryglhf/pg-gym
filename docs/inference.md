# Models and inference

A model on the platform is an artifact: a directory of files with a manifest, checksums and lineage. Imports create them, training creates more of them, and vLLM serves them.

## Importing a model

```sh
pg-gym --timeout 3600 models pull Qwen/Qwen2.5-Coder-3B-Instruct --wait
pg-gym models list
```

The import resolves the revision to a commit, downloads the safetensors weights, the tokenizer and the config, and records every file with its size and SHA-256. Remote model code is never enabled, so an architecture that needs it cannot be imported. Pass `--revision` to pin something other than `main` and `--credential` for a gated repository, or point the import at an environment variable with `credential_env` in a config file.

The download runs on a worker, and the worker and the API each keep a copy, so allow for twice the model size on disk.

## Artifacts

```sh
pg-gym artifacts list
pg-gym artifacts show ARTIFACT_ID
pg-gym artifacts download ARTIFACT_ID --directory ./model
```

`show` prints the manifest and the files. `download` fetches every file of a ready artifact and checks each against its recorded checksum. An adapter's manifest names the model it was trained on and the job that produced it, and a model's manifest names the repository and commit it came from.

Ready artifacts are immutable. A file that goes missing on disk is reported as a storage error rather than silently recreated.

## Serving with vLLM

```sh
pg-gym inference deploy MODEL_ID --wait
pg-gym inference status JOB_ID
pg-gym inference stop JOB_ID
```

A deployment is a job on the GPU worker that starts vLLM with the artifact mounted read-only, Hugging Face offline mode on and a per-deployment API key. When it is up, a connection for it appears in Settings, ready for chat and for benchmarks. An adapter deploys the same way and is served on top of its base model.

The specification has a few knobs.

| Field | Default | Meaning |
| --- | --- | --- |
| `max_model_len` | 4096 | Context length vLLM allocates for |
| `gpu_memory_utilization` | 0.85 | Share of the GPU memory vLLM may take |
| `tool_parser` | none | `hermes`, `llama3_json`, `mistral` or `qwen3_xml` |

Set the tool parser to the one matching the model when the deployment will be used inside a harness, otherwise the agent's tool calls come back as text. One deployment holds the GPU, so stop it before training. Stopping removes the container and its staging volume while the deployment's configuration and history stay visible.

## Chat

```sh
pg-gym --timeout 300 inference chat --connection CONNECTION_ID --prompt 'Explain this query plan'
pg-gym inference chat --connection A_ID --connection B_ID --prompt-stdin < question.txt
pg-gym inference chat --conversation CONVERSATION_ID --prompt 'And with a partial index?'
```

Each chat is a conversation on the platform with its history, so a follow-up refers to what was said. Two connections make two independent conversations that receive the same prompts, which is how you compare a fine-tuned model to its base. Answers stream in the web application and arrive whole on the CLI. Tool calls the model makes are shown, not executed.

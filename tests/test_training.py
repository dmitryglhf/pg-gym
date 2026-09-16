import json
import subprocess
from types import SimpleNamespace

import pytest

from postgres_gym.core.agents import PatchAgent
from postgres_gym.training.context import context_from_patch
from postgres_gym.training.data import split
from postgres_gym.training.grpo import peft_config
from postgres_gym.training.reward import diff_from_completion

PATCH = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,3 +1,3 @@\n before\n-fixed\n+buggy\n \n"


def test_split_is_deterministic_and_disjoint():
    train, test = split(["a", "b", "c", "d", "e"], 0.2, 42)

    assert train == ["a", "b", "c", "e"]
    assert test == ["d"]
    assert not set(train) & set(test)


def test_peft_targets_the_last_model_layers():
    assert peft_config(8, 16, 36).layers_to_transform == list(range(20, 36))


def test_diff_from_completion_extracts_fenced_diff():
    completion = "```diff\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n```"

    assert diff_from_completion(completion) == "diff --git a/a b/a\n--- a/a\n+++ b/a\n"


def test_diff_from_completion_skips_a_non_patch_fence():
    completion = "```\ndiff a b\n```\n```diff\ndiff --git a/a b/a\n--- a/a\n+++ b/a\n```"

    assert diff_from_completion(completion) == "diff --git a/a b/a\n--- a/a\n+++ b/a\n"


@pytest.mark.parametrize("wrap", [lambda p: p, lambda p: f"```diff\n{p}```",
                                  lambda p: f"<think>diff --git is a format</think>\n```patch\n{p}```\n"])
def test_extracted_patch_reverses_mutation(tmp_path, monkeypatch, wrap):
    (tmp_path / "a").write_text("before\nbuggy\n\n")
    monkeypatch.setattr("postgres_gym.core.payload.completion", lambda: diff_from_completion(wrap(PATCH)))
    result = PatchAgent().run({}, {}, suite=None, stand=SimpleNamespace(root=tmp_path))
    assert result["applied"], result
    assert (tmp_path / "a").read_text() == "before\nfixed\n\n"


def test_patch_recounts_invalid_hunk_lengths(tmp_path, monkeypatch):
    (tmp_path / "a").write_text("before\nbuggy\n\n")
    malformed = PATCH.replace("@@ -1,3 +1,3 @@", "@@ -1,1 +1,1 @@")
    monkeypatch.setattr("postgres_gym.core.payload.completion", lambda: malformed)
    result = PatchAgent().run({}, {}, suite=None, stand=SimpleNamespace(root=tmp_path))
    assert result["applied"], result
    assert (tmp_path / "a").read_text() == "before\nfixed\n\n"


def test_diff_normalizes_empty_context_lines():
    malformed = PATCH.replace("\n \n", "\n\n")
    assert diff_from_completion(malformed).endswith("@@ -1,3 +1,3 @@\n before\n-fixed\n+buggy\n \n")


def test_patch_adds_missing_newline_without_stripping_context():
    assert diff_from_completion(PATCH[:-1]) == PATCH
    assert diff_from_completion("no patch") == ""


def test_buggy_context_does_not_expose_fixed_source(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a").write_text("before\nfixed\n\n")
    subprocess.run(["git", "add", "a"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    context = context_from_patch(tmp_path / ".git", "HEAD", PATCH)
    assert "buggy" in context
    assert "fixed" not in context
    assert "before\nbuggy\n" in context
    assert (tmp_path / "a").read_text() == "before\nfixed\n\n"


def test_chat_prefix_and_loss_boundary_match():
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    from postgres_gym.training.chat import CHAT_TEMPLATE

    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel(
        {"[UNK]": 0, "<bos>": 1, "<eos>": 2}, unk_token="[UNK]"))
    tokenizer = transformers.PreTrainedTokenizerFast(tokenizer_object=backend, bos_token="<bos>", eos_token="<eos>")
    tokenizer.chat_template = CHAT_TEMPLATE
    messages = [{"role": "user", "content": "task"}]
    prefix = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages + [{"role": "assistant", "content": PATCH}], tokenize=False)
    assert full == prefix + PATCH + "<eos>"
    assert "<think>" not in prefix


def test_mlx_conversion_preserves_lora_update(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("peft")
    from safetensors.torch import load_file, save_file

    from postgres_gym.training.adapters import convert_mlx_lora

    source = tmp_path / "mlx"
    source.mkdir()
    (source / "adapter_config.json").write_text(json.dumps({"lora_parameters": {"rank": 2, "scale": 7, "dropout": 0}}))
    a, b = torch.randn(4, 2), torch.randn(2, 3)
    save_file({"model.layers.3.self_attn.q_proj.lora_a": a,
               "model.layers.3.self_attn.q_proj.lora_b": b}, source / "adapters.safetensors")
    output = tmp_path / "peft"
    convert_mlx_lora(source, output, "test")
    config = json.loads((output / "adapter_config.json").read_text())
    weights = load_file(output / "adapter_model.safetensors")
    x = torch.randn(5, 4)
    prefix = "base_model.model.model.layers.3.self_attn.q_proj."
    actual = x @ weights[prefix + "lora_A.weight"].T @ weights[prefix + "lora_B.weight"].T
    torch.testing.assert_close(actual * config["lora_alpha"] / config["r"], 7 * (x @ a @ b))
    assert config["layers_to_transform"] == [3]


def test_sft_rejects_target_truncation():
    from postgres_gym.training.chat import validate_lengths

    tokenizer = SimpleNamespace(apply_chat_template=lambda *args, **kwargs: list(range(10)))
    rows = [{"messages": [{"role": "user", "content": "task"}, {"role": "assistant", "content": PATCH}]}]
    with pytest.raises(ValueError, match="instead of truncating"):
        validate_lengths(tokenizer, rows, 9)
    validate_lengths(tokenizer, rows, 10)


def test_template_matches_between_sft_and_grpo():
    from postgres_gym.training.chat import CHAT_TEMPLATE, configure_template

    local = configure_template(SimpleNamespace(chat_template="native"),
                               "artifacts/models/deepseek-r1-distill-qwen-1.5b-mlx")
    native = configure_template(SimpleNamespace(chat_template="native"), "Qwen/Qwen2.5-Coder-3B-Instruct")
    assert local.chat_template == CHAT_TEMPLATE
    assert native.chat_template == "native"
    with pytest.raises(ValueError, match="no chat template"):
        configure_template(SimpleNamespace(chat_template=None), "base/model")


def test_summary_counts_applied_and_rewarded_rollouts():
    from postgres_gym.training.evaluate import summarize

    records = [{"patch": PATCH, "reward": 1.0, "record": {"agent_meta": {"applied": True}}},
               {"patch": "", "reward": None, "record": None}]

    assert summarize(records) == {"tasks": 2, "applied": 1, "nonempty_patch": 1,
                                  "rewarded": 1, "reward_mean": 0.5, "reward_max": 1.0}


def test_peft_to_mlx_round_trip_preserves_the_adapter(tmp_path):
    import torch
    from safetensors.torch import load_file, save_file

    from postgres_gym.training.adapters import convert_mlx_lora, convert_peft_lora

    mlx = tmp_path / "mlx"
    mlx.mkdir()
    (mlx / "adapter_config.json").write_text(json.dumps({"lora_parameters": {"rank": 2, "scale": 20, "dropout": 0}}))
    weights = {"model.layers.3.self_attn.q_proj.lora_a": torch.randn(4, 2),
               "model.layers.3.self_attn.q_proj.lora_b": torch.randn(2, 3)}
    save_file(weights, mlx / "adapters.safetensors")
    convert_mlx_lora(mlx, tmp_path / "peft", "test")
    convert_peft_lora(tmp_path / "peft", tmp_path / "back")

    config = json.loads((tmp_path / "back" / "adapter_config.json").read_text())
    assert config["lora_parameters"]["scale"] == 20
    assert config["lora_parameters"]["keys"] == ["self_attn.q_proj"]
    assert config["num_layers"] == 1
    for key, tensor in load_file(tmp_path / "back" / "adapters.safetensors").items():
        torch.testing.assert_close(tensor, weights[key])


def test_liveness_marks_only_groups_that_can_produce_advantage():
    from postgres_gym.training.screen import liveness

    rows = liveness({("s", "flat"): [0.1, 0.1], ("s", "mixed"): [0.0, 0.1]})

    assert [(row["task"], row["live"]) for row in rows] == [("flat", False), ("mixed", True)]


def test_screen_limit_counts_each_suite_separately():
    from postgres_gym.training.screen import first_per_suite

    rows = [{"suite": "a", "task": str(index)} for index in range(3)]
    rows += [{"suite": "b", "task": str(index)} for index in range(3)]

    assert [row["task"] for row in first_per_suite(rows, 2)] == ["0", "1", "0", "1"]


def test_interleave_visits_suites_in_turn():
    from postgres_gym.training.grpo import interleave

    rows = [{"suite": "a", "task": "a1"}, {"suite": "a", "task": "a2"}, {"suite": "b", "task": "b1"}]

    assert [row["task"] for row in interleave(rows)] == ["a1", "b1", "a2"]


def test_selected_reads_suite_and_task_pairs(tmp_path):
    from postgres_gym.training.grpo import selected

    path = tmp_path / "live-tasks.txt"
    path.write_text("suite\ttask\n\nother\tsecond\n")

    assert selected(path) == {("suite", "task"), ("other", "second")}
    assert selected(None) is None


def test_selected_rejects_a_line_without_a_suite(tmp_path):
    from postgres_gym.training.grpo import selected

    path = tmp_path / "live-tasks.txt"
    path.write_text("task\n")

    with pytest.raises(ValueError, match="tab separated"):
        selected(path)

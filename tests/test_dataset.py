import json
from pathlib import Path

import pytest

from postgres_gym.collect import dataset, episode

SUITE = "sql-function-set"
TOOLS = [
    {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
    for name in episode.TOOLS
]
MESSAGES = [
    {"role": "system", "content": "You are markov"},
    {"role": "user", "content": "Implement area()"},
]


def line(
    turn: int,
    *,
    call: tuple[str, str] | None = ("shell", '{"command": "ls"}'),
    finish: str = "tool_calls",
    tools: list[dict] = TOOLS,
    error: dict | None = None,
) -> dict:
    message: dict = {"role": "assistant", "content": None}
    if call:
        name, arguments = call
        message["tool_calls"] = [
            {
                "id": f"call_{turn}",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ]
    else:
        message["content"] = "done"
    usage = {"prompt_tokens": 100 + turn, "completion_tokens": 10}
    history = [{"role": "assistant", "content": "earlier"}] * turn
    return {
        "turn": turn,
        "at": "2026-09-17T00:00:00+00:00",
        "seconds": 1.0,
        "request": {"model": "m", "messages": MESSAGES + history, "tools": tools},
        "response": None
        if error
        else {
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": usage,
        },
        "usage": None if error else usage,
        "error": error,
    }


ENTRY = {
    "episode_id": "e1",
    "suite": SUITE,
    "task": "area",
    "task_hash": "h",
    "attempt": 1,
    "model": "m",
    "state": "scored_pass",
    "pass": True,
    "trajectory_file": "e1.jsonl",
}


def run_dir(tmp_path: Path, lines: list[dict], **entry) -> Path:
    root = tmp_path / "run"
    (root / "trajectories").mkdir(parents=True)
    (root / "reports" / SUITE / "area").mkdir(parents=True)
    (root / "run.json").write_text(json.dumps({"model": "m"}))
    with (root / "trajectories" / "e1.jsonl").open("w") as handle:
        for item in lines:
            handle.write(json.dumps(item) + "\n")
    report = {**ENTRY, **entry}
    (root / "reports" / SUITE / "area" / "1.json").write_text(json.dumps(report))
    return root


def rows_of(path: Path) -> list[dict]:
    return [json.loads(raw) for raw in path.read_text().splitlines()]


def test_build_writes_one_row_per_assistant_turn(tmp_path: Path):
    root = run_dir(tmp_path, [line(0), line(1), line(2, call=None, finish="stop")])
    out = tmp_path / "out"
    manifest = dataset.build([root], out, dev_fraction=0)
    rows = rows_of(out / "train.jsonl")

    assert len(rows) == 3
    assert manifest["rows"] == {"train": 3, "dev": 0}
    assert manifest["episodes"] == {"passing": 1, "accepted": 1, "rejected": 0}
    assert manifest["harness"] == [{"model": "m"}]
    assert manifest["files"]["train.jsonl"]
    first = rows[0]
    assert first["format"] == dataset.FORMAT
    assert first["prompt"] == MESSAGES
    assert first["completion"][0]["tool_calls"][0]["function"]["name"] == "shell"
    assert [t["function"]["name"] for t in first["tools"]] == list(episode.TOOLS)
    assert first["metadata"]["turn"] == 0 and first["metadata"]["turns"] == 3
    assert first["metadata"]["split"] == "train"
    assert first["metadata"]["source_model"] == "m"
    assert first["metadata"]["prompt_tokens"] == 100
    assert len(rows[1]["prompt"]) == 3
    assert rows[2]["completion"][0]["content"] == "done"
    assert rows[2]["metadata"]["finish_reason"] == "stop"
    assert (out / "dev.jsonl").read_text() == ""


def test_build_rejects_broken_trajectories_and_skips_failures(tmp_path: Path):
    root = run_dir(tmp_path, [line(0), line(2)])
    other = root / "reports" / SUITE / "cbrt"
    other.mkdir()
    (other / "1.json").write_text(
        json.dumps({**ENTRY, "episode_id": "e2", "task": "cbrt", "pass": False})
    )
    out = tmp_path / "out"
    manifest = dataset.build([root], out)

    assert rows_of(out / "rejected.jsonl") == [
        {"episode_id": "e1", "reason": "turn_gap"}
    ]
    assert manifest["rows"] == {"train": 0, "dev": 0}
    assert manifest["episodes"] == {"passing": 1, "accepted": 0, "rejected": 1}


def test_build_rejects_a_missing_trajectory(tmp_path: Path):
    root = run_dir(tmp_path, [line(0)], trajectory_file="gone.jsonl")
    dataset.build([root], tmp_path / "out")

    assert rows_of(tmp_path / "out" / "rejected.jsonl") == [
        {"episode_id": "e1", "reason": "no_trajectory"}
    ]


@pytest.mark.parametrize(
    ("lines", "reason"),
    [
        ([], "empty_trajectory"),
        ([line(0, error={"kind": "provider"})], "no_completed_calls"),
        ([line(0), line(2)], "turn_gap"),
        (
            [line(0), line(1, error={"kind": "provider"}), line(2)],
            "error_before_last_call",
        ),
        ([line(0, tools=TOOLS[:4])], "unexpected_tools:edit,read_image,shell,tree"),
        ([line(0, call=("rm", "{}"))], "unknown_tool_call:rm"),
        ([line(0, call=("shell", "not json"))], "tool_arguments_not_json"),
        ([line(0, finish="length")], "finish_reason:length"),
    ],
)
def test_episode_rows_rejects_broken_trajectories(lines, reason):
    with pytest.raises(ValueError, match=reason):
        dataset.episode_rows(ENTRY, lines, "digest")


def test_trailing_budget_refusal_keeps_the_completed_calls():
    lines = [line(0), line(1), line(2, error={"kind": "budget"})]
    rows = dataset.episode_rows(ENTRY, lines, "digest")

    assert [row["metadata"]["turn"] for row in rows] == [0, 1]
    assert all(row["metadata"]["turns"] == 2 for row in rows)
    assert all(row["metadata"]["trajectory_sha256"] == "digest" for row in rows)


def test_pick_dev_holds_out_whole_groups():
    rows = [{"metadata": {"group": g}} for g in ("a", "b", "c", "d", "a", "b")]
    dev = dataset.pick_dev(rows, 0.25, seed=0)

    assert len(dev) == 1 and dev < {"a", "b", "c", "d"}
    assert dataset.pick_dev(rows, 0, seed=0) == set()
    assert dataset.pick_dev(rows, 0.5, seed=1) == dataset.pick_dev(rows, 0.5, seed=1)
    assert len(dataset.pick_dev(rows, 0.5, seed=1)) == 2


def test_group_key_falls_back_to_the_task_name():
    assert dataset.group_key("no-such-suite", "t") == "no-such-suite:t"
    assert dataset.group_key(SUITE, "area").startswith(f"{SUITE}:")

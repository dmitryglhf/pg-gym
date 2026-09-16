from pathlib import Path

from postgres_gym.core import data


def test_split_preserves_suite_order(tmp_path: Path):
    (tmp_path / "tasks").mkdir()
    (tmp_path / "splits").mkdir()
    for name in ("a", "b", "c"):
        (tmp_path / "tasks" / f"{name}.json").write_text("{}")
    (tmp_path / "splits" / "train.txt").write_text("c\na\n")

    assert data.apply_split(tmp_path, ["a", "b", "c"], "train") == ["a", "c"]


def test_task_hash_changes_with_oracle(tmp_path: Path):
    for directory in ("tasks", "oracle", "prep"):
        (tmp_path / directory).mkdir()
    (tmp_path / "tasks" / "a.json").write_text('{"func":"a"}')
    (tmp_path / "oracle" / "a.json").write_text('{"patch":"prep/a.patch"}')
    (tmp_path / "prep" / "a.patch").write_text("first")

    before = data.task_hash(tmp_path, "a")
    (tmp_path / "oracle" / "a.json").write_text('{"patch":"prep/a.patch","x":1}')

    assert data.task_hash(tmp_path, "a") != before

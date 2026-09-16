from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.rl"])
def test_task_image_excludes_suite_data(name):
    rules = (ROOT / f"deploy/task/{name}.dockerignore").read_text()
    assert rules.splitlines()[0] == "**"
    assert "!suites/*/src/**" in rules
    assert "!suites/*/data" not in rules
    assert "suites/*/data/" in rules
    assert "suites/*/data/**" in rules


def test_task_image_supports_commit_collation_tests():
    dockerfile = (ROOT / "deploy/task/Dockerfile").read_text()
    assert "--with-icu" in dockerfile
    assert "libicu-dev" in dockerfile
    for locale in ("de_DE", "en_US", "sv_SE", "tr_TR"):
        assert f"localedef -i {locale}" in dockerfile
        assert f"/usr/lib/locale/{locale}" in dockerfile


def test_suite_data_is_direct():
    assert (ROOT / "suites/sql-function-set/data/tasks").is_dir()
    assert not (ROOT / "suites/sql-function-set/selections").exists()

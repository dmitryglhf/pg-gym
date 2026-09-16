import os
import shutil
import subprocess
import sys
from pathlib import Path

from postgres_gym.core import registry
from postgres_gym.execution.payload import build


def test_task_runtime_loads_payload_without_suite_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for suite in registry.available():
        shutil.copytree(
            root / "suites" / suite.id / "src",
            tmp_path / "suites" / suite.id / "src",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        name = suite.runnable()[0]
        payload = build(suite, name)
        script = """
import sys
from postgres_gym.core import registry
suite = registry.load(sys.argv[1])
task, oracle = suite.load(sys.argv[2])
assert suite.prompt(task, oracle)
assert suite.mutation(oracle)
assert not suite.data.exists()
print('payload loaded without suite data')
"""
        result = subprocess.run(
            [sys.executable, "-c", script, suite.id, name],
            cwd=tmp_path,
            input=payload,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "POSTGRES_GYM_ROOT": str(tmp_path),
                "POSTGRES_GYM_PAYLOAD_STDIN": "1",
                "PYTHONPATH": str(root / "src"),
            },
        )
        assert result.returncode == 0, result.stderr.decode()

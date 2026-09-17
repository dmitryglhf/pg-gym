from __future__ import annotations

import time
from types import SimpleNamespace

from postgres_gym_platform.execute import MODEL_FILES, DownloadProgress, expected_bytes


class Events:
    def __init__(self):
        self.items = []

    def emit(self, kind, **payload):
        self.items.append((kind, payload))


def test_expected_bytes_counts_only_the_files_an_import_fetches():
    siblings = [
        SimpleNamespace(rfilename="model.safetensors", size=1000),
        SimpleNamespace(rfilename="config.json", size=24),
        SimpleNamespace(rfilename="pytorch_model.bin", size=5000),
        SimpleNamespace(rfilename="tokenizer.json", size=None),
    ]

    assert expected_bytes(siblings, MODEL_FILES) == 1024
    assert expected_bytes([], MODEL_FILES) is None


def test_download_progress_reports_partial_files_and_the_final_size(tmp_path):
    runtime = SimpleNamespace(events=Events())
    directory = tmp_path / "download"
    with DownloadProgress(runtime, directory, total=4 * 2**20, interval=0.05):
        directory.mkdir()
        (directory / ".cache").mkdir()
        (directory / ".cache" / "weights.incomplete").write_bytes(b"x" * 2**20)
        time.sleep(0.2)
        (directory / "weights.safetensors").write_bytes(b"x" * 3 * 2**20)

    texts = [payload["text"] for kind, payload in runtime.events.items if kind == "log"]
    assert texts[0].startswith("downloaded 1.0 MB of 4.0 MB (25%)")
    assert texts[-1] == "downloaded 4.0 MB of 4.0 MB (100%)"
    assert len(texts) == len(set(texts)), "unchanged sizes are not repeated"

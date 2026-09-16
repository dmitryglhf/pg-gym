from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote


def download_artifact(client, identifier: str, directory: Path) -> dict:
    artifact = client.request("GET", "/artifacts/" + identifier)
    if artifact["status"] != "ready":
        raise ValueError("Artifact is not complete")
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    for item in artifact["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in item["path"]:
            raise ValueError("Invalid artifact path")
        path = directory / relative
        if not path.resolve().is_relative_to(directory):
            raise ValueError("Artifact path escapes the destination")
        if path.exists():
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() == item["sha256"]:
                    continue
            raise ValueError("Refusing to overwrite a different file: " + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".download-")
        os.close(descriptor)
        temporary = Path(name)
        with client.http.stream(
            "GET",
            "/api/v1/artifacts/"
            + identifier
            + "/files/"
            + quote(item["path"], safe="/"),
        ) as response:
            response.raise_for_status()
            checksum = hashlib.sha256()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(1024**2):
                    output.write(chunk)
                    checksum.update(chunk)
        if (
            checksum.hexdigest() != item["sha256"]
            or temporary.stat().st_size != item["size"]
        ):
            temporary.unlink()
            raise ValueError("Artifact checksum mismatch")
        temporary.replace(path)
    (directory / "pg-gym-manifest.json").write_text(json.dumps(artifact, indent=2))
    return {
        "artifact_id": identifier,
        "directory": str(directory),
        "files": len(artifact["files"]),
    }

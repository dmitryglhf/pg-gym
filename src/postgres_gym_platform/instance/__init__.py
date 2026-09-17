from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


class CommandError(Exception):
    """A local docker or compose command exited with a failure."""


@dataclass(frozen=True)
class Instance:
    """Durable identity of a local platform instance shared by compose and storage."""

    directory: Path
    name: str

    @property
    def data(self) -> Path:
        return self.directory / "data"

    @property
    def secrets(self) -> Path:
        return self.directory / "secrets"

    @property
    def compose(self) -> Path:
        return self.directory / "compose.yaml"

    @property
    def environment(self) -> Path:
        return self.directory / "platform.env"

    @classmethod
    def load(cls, directory: Path) -> Instance:
        directory = directory.expanduser().resolve()
        manifest = directory / "instance.json"
        if not manifest.is_file():
            raise ValueError(
                "Instance identity is missing. Initialize a new directory with platform init; "
                "legacy instances require an explicit migration."
            )
        value = json.loads(manifest.read_text())
        name = value.get("name", "")
        if value.get("version") != 1 or not re.fullmatch(r"pg-gym-[a-f0-9]{32}", name):
            raise ValueError("Invalid instance identity")
        if (
            not (directory / "compose.yaml").is_file()
            or not (directory / "platform.env").is_file()
        ):
            raise ValueError("Instance is incomplete")
        return cls(directory, name)


__all__ = ["CommandError", "Instance"]

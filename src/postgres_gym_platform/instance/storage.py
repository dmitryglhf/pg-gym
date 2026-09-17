from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from . import Instance


def backup(instance: Instance, path: Path) -> dict:
    from ..db import Database

    path = path.expanduser().resolve()
    database = instance.data / "platform.sqlite"
    if not database.is_file():
        raise ValueError("Database not found")
    if path.exists():
        raise ValueError("Backup destination already exists")
    with tempfile.TemporaryDirectory() as temporary:
        snapshot = Path(temporary) / "platform.sqlite"
        Database(database).backup(snapshot)
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
            path.chmod(0o600)
            archive.write(snapshot, "platform.sqlite")
            for name in ("master.key", "worker-token", "registration-token"):
                if (instance.secrets / name).is_file():
                    archive.write(instance.secrets / name, "secrets/" + name)
            for file in (instance.data / "artifacts").rglob("*"):
                if (
                    file.is_file()
                    and not file.is_symlink()
                    and ".upload-" not in file.name
                ):
                    archive.write(file, file.relative_to(instance.data))
    return {"path": str(path), "at": time.time(), "instance": instance.name}


def reset_password(instance: Instance, username: str, password: str) -> dict:
    from ..db import Database
    from ..security import PASSWORDS

    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    if not (instance.data / "platform.sqlite").is_file():
        raise ValueError("Database not found")
    with Database(instance.data / "platform.sqlite").connect(write=True) as db:
        row = db.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise ValueError("User not found")
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (PASSWORDS.hash(password), row["id"]),
        )
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
    return {"ok": True}


def _restore_files(path: Path, instance: Instance) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not {
            "platform.sqlite",
            "secrets/master.key",
            "secrets/worker-token",
        }.issubset(names):
            raise ValueError("Backup is missing the database or required secrets")
        if len(set(names)) != len(names):
            raise ValueError("Duplicate backup members")
        for item in archive.infolist():
            relative = Path(item.filename)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in item.filename
                or item.is_dir()
                or (item.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Invalid backup member")
            if (
                item.filename
                not in {
                    "platform.sqlite",
                    "secrets/master.key",
                    "secrets/worker-token",
                    "secrets/registration-token",
                }
                and relative.parts[0] != "artifacts"
            ):
                raise ValueError("Unexpected backup member")
        for item in archive.infolist():
            relative = Path(item.filename)
            target = (
                instance.secrets / relative.name
                if relative.parts[0] == "secrets"
                else instance.data / relative
            )
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with archive.open(item) as source, target.open("xb") as output:
                target.chmod(0o600)
                shutil.copyfileobj(source, output)


def restore(path: Path, directory: Path, origin: str, open_registration: bool) -> dict:
    from .compose import initialize_instance

    directory = directory.expanduser().resolve()
    if directory.exists():
        raise ValueError("Restore requires a new, nonexistent instance directory")
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".pg-gym-restore-", dir=directory.parent
    ) as temporary:
        stage = Path(temporary) / "instance"
        initialize_instance(stage, origin, open_registration)
        instance = Instance.load(stage)
        for secret in instance.secrets.iterdir():
            secret.unlink()
        _restore_files(path.expanduser().resolve(), instance)
        if (
            not open_registration
            and not (instance.secrets / "registration-token").is_file()
        ):
            raise ValueError(
                "Backup is missing the registration token; use --open-registration if appropriate"
            )
        stage.rename(directory)
    return {"ok": True, "directory": str(directory), "instance": instance.name}

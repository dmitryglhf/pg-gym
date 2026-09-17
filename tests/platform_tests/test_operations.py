import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from postgres_gym.cli import app
from postgres_gym_platform.api import create_app
from postgres_gym_platform.instance import Instance, compose, storage

from .conftest import connection, submit

ROOT = Path(__file__).resolve().parents[2]


def test_backup_restore_keeps_ownership_credentials_and_history(platform, tmp_path):
    client, app, users = platform
    cfg = app.state.config
    conn = connection(client, users["alice"])
    job = submit(client, users["alice"], conn["id"]).json()
    (cfg.secret_dir / "worker-token").write_text(cfg.worker_token)
    (cfg.secret_dir / "registration-token").write_text(cfg.registration_token)
    instance = Instance(cfg.data.parent, "pg-gym-" + "0" * 32)
    archive = tmp_path / "backup.zip"

    assert storage.backup(instance, archive)["path"] == str(archive)

    restored_dir = tmp_path / "restored"
    result = storage.restore(archive, restored_dir, "http://localhost:9432", False)
    assert result["ok"]
    restored = replace(
        cfg, data=restored_dir / "data", secret_dir=restored_dir / "secrets"
    )
    with TestClient(create_app(restored)) as after:
        assert (
            after.get(f"/api/v1/jobs/{job['id']}", headers=users["alice"]).json()["id"]
            == job["id"]
        )
        assert (
            after.get(f"/api/v1/jobs/{job['id']}", headers=users["bob"]).status_code
            == 404
        )
        with after.app.state.db.connect() as db:
            encrypted = db.execute(
                "SELECT secret FROM connections WHERE id=?", (conn["id"],)
            ).fetchone()[0]
        assert (
            after.app.state.vault.decrypt(encrypted.encode())
            == b"private-provider-test"
        )
    with pytest.raises(ValueError, match="nonexistent instance directory"):
        storage.restore(archive, restored_dir, "http://localhost:9432", False)


def test_restore_rejects_traversal_before_writing(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("platform.sqlite", "database")
        z.writestr("secrets/master.key", "key")
        z.writestr("secrets/worker-token", "token")
        z.writestr("artifacts/../../escaped", "bad")

    with pytest.raises(ValueError, match="Invalid backup member"):
        storage.restore(archive, tmp_path / "restored", "http://localhost:9432", True)

    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path / "restored").exists()


def test_cli_rejects_invalid_limits_before_submission():
    runner = CliRunner()
    for args in (
        ["benchmark", "submit", "--min-solve-rate", "0.5"],
        ["benchmark", "submit", "--wait", "--min-solve-rate", "2"],
        ["--timeout", "nan", "benchmark", "submit"],
    ):
        assert runner.invoke(app, args).exit_code == 2, args


def test_platform_start_initializes_builds_and_starts_without_resetting(
    tmp_path, monkeypatch
):
    commands = []
    monkeypatch.setattr(
        compose, "checked", lambda command, **kwargs: commands.append(command)
    )
    directory = tmp_path / "instance"

    assert compose.start_platform(ROOT, directory)["ok"]
    original = (directory / "secrets" / "master.key").read_bytes()
    assert sum(command[:2] == ["docker", "build"] for command in commands) == 2
    assert "--wait" in commands[-1] and "up" in commands[-1]
    assert "PG_GYM_API_PORT=9433" in (directory / "platform.env").read_text()

    assert compose.start_platform(ROOT, directory)["ok"]
    assert (directory / "secrets" / "master.key").read_bytes() == original


def test_docker_group_is_root_under_docker_desktop(monkeypatch):
    monkeypatch.setattr(compose.sys, "platform", "darwin")
    assert compose.docker_gid() == 0

    monkeypatch.setattr(compose.sys, "platform", "linux")
    monkeypatch.setattr(compose.Path, "exists", lambda self: False)
    assert compose.docker_gid() == 0


def test_platform_start_refreshes_files_of_an_older_release(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "checked", lambda *args, **kwargs: None)
    directory = tmp_path / "instance"
    compose.start_platform(ROOT, directory)
    stale = (directory / "compose.yaml").read_text().replace("9433", "8001")
    (directory / "compose.yaml").write_text(stale)
    env = directory / "platform.env"
    env.write_text(
        "".join(
            line + "\n"
            for line in env.read_text().splitlines()
            if not line.startswith("PG_GYM_API_PORT=")
        )
    )

    result = compose.start_platform(ROOT, directory)

    assert result["refreshed"] == ["compose.yaml", "platform.env"]
    assert "8001" not in (directory / "compose.yaml").read_text()
    assert "PG_GYM_API_PORT=9433" in env.read_text()
    assert "PG_GYM_ORIGIN=http://localhost:9432" in env.read_text()
    assert "refreshed" not in compose.start_platform(ROOT, directory)


def test_refresh_moves_macos_instances_to_the_root_docker_group(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "checked", lambda *args, **kwargs: None)
    monkeypatch.setattr(compose.sys, "platform", "darwin")
    directory = tmp_path / "instance"
    compose.start_platform(ROOT, directory)
    env = directory / "platform.env"
    env.write_text(
        env.read_text().replace("PG_GYM_DOCKER_GID=0", "PG_GYM_DOCKER_GID=20")
    )

    assert compose.refresh_instance(Instance.load(directory)) == ["platform.env"]
    assert "PG_GYM_DOCKER_GID=0\n" in env.read_text()


def test_platform_start_supports_code_free_registration(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "checked", lambda *args, **kwargs: None)
    directory = tmp_path / "instance"

    assert compose.start_platform(ROOT, directory, open_registration=True)["ok"]
    assert "PG_GYM_OPEN_REGISTRATION=1" in (directory / "platform.env").read_text()
    assert "PG_GYM_OPEN_REGISTRATION:" in (directory / "compose.yaml").read_text()
    result = compose.start_platform(ROOT, directory, open_registration=True)
    assert result["ok"] and "registration_code" not in result

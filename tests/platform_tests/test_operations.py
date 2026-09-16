import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from postgres_gym_platform.api import create_app
from postgres_gym_platform.cli import parser, run

from .conftest import connection, submit


def test_backup_restore_keeps_ownership_credentials_and_history(
    platform, tmp_path, monkeypatch, capsys
):
    client, app, users = platform
    cfg = app.state.config
    conn = connection(client, users["alice"])
    job = submit(client, users["alice"], conn["id"]).json()
    monkeypatch.setenv("PG_GYM_DATA", str(cfg.data))
    monkeypatch.setenv("PG_GYM_SECRET_DIR", str(cfg.secret_dir))
    archive = tmp_path / "backup.zip"
    assert (
        run(
            parser().parse_args(["storage", "backup", str(archive), "--output", "json"])
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["path"] == str(archive)
    restored = replace(
        cfg, data=tmp_path / "restored-data", secret_dir=tmp_path / "restored-secrets"
    )
    monkeypatch.setenv("PG_GYM_DATA", str(restored.data))
    monkeypatch.setenv("PG_GYM_SECRET_DIR", str(restored.secret_dir))
    assert run(parser().parse_args(["storage", "restore", str(archive)])) == 0
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
    with pytest.raises(ValueError, match="empty instance"):
        run(parser().parse_args(["storage", "restore", str(archive)]))


def test_restore_rejects_traversal_before_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("PG_GYM_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PG_GYM_SECRET_DIR", str(tmp_path / "secrets"))
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("platform.sqlite", "database")
        z.writestr("secrets/master.key", "key")
        z.writestr("artifacts/../../escaped", "bad")
    with pytest.raises(ValueError, match="Invalid backup member"):
        run(parser().parse_args(["storage", "restore", str(archive)]))
    assert not (tmp_path / "escaped").exists()
    assert not list((tmp_path / "data").iterdir())


def test_cli_rejects_invalid_limits_before_submission():
    for args in (
        ["benchmark", "run", "--min-solve-rate", "0.5"],
        ["benchmark", "run", "--wait", "--min-solve-rate", "2"],
        ["benchmark", "run", "--timeout", "nan"],
    ):
        with pytest.raises(ValueError):
            run(parser().parse_args(args))


def test_platform_start_initializes_builds_and_starts_without_resetting(tmp_path, monkeypatch):
    from postgres_gym_platform import operations

    commands = []
    monkeypatch.setattr(operations, "checked", lambda command, **kwargs: commands.append(command))
    source = Path(__file__).resolve().parents[2]
    directory = tmp_path / "instance"
    args = parser().parse_args(["platform", "start", "--source", str(source), "--directory", str(directory)])
    assert operations.operate(args)["ok"]
    original = (directory / "secrets" / "master.key").read_bytes()
    assert sum(command[:2] == ["docker", "build"] for command in commands) == 2
    assert "--wait" in commands[-1] and "up" in commands[-1]
    assert operations.operate(args)["ok"]
    assert (directory / "secrets" / "master.key").read_bytes() == original


def test_platform_start_supports_code_free_registration(tmp_path, monkeypatch):
    from postgres_gym_platform import operations

    monkeypatch.setattr(operations, "checked", lambda *args, **kwargs: None)
    source = Path(__file__).resolve().parents[2]
    directory = tmp_path / "instance"
    args = parser().parse_args(["platform", "start", "--source", str(source), "--directory", str(directory), "--open-registration"])
    assert operations.operate(args)["ok"]
    assert "PG_GYM_OPEN_REGISTRATION=1" in (directory / "platform.env").read_text()
    assert "PG_GYM_OPEN_REGISTRATION:" in (directory / "compose.yaml").read_text()
    result = operations.operate(args)
    assert result["ok"] and "registration_code" not in result

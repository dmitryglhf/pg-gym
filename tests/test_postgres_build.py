from types import SimpleNamespace

from postgres_gym.stands.postgres import build


def test_build_cleans_before_rebuilding_changed_files(monkeypatch):
    calls = []

    monkeypatch.setattr(build, "ensure_configured", lambda: None)
    monkeypatch.setattr(build, "invalidate_generated", lambda: None)

    def run(argv, cwd, timeout):
        calls.append((argv, cwd, timeout))
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(build, "_run", run)

    build.build(["src/fe_utils/print.c"])

    assert calls == [
        (["make", "clean"], build.settings.PG_SRC, build.BUILD_TIMEOUT),
        (["make", f"-j{build.JOBS}"], build.settings.PG_SRC, build.BUILD_TIMEOUT),
    ]

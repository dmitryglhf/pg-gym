from __future__ import annotations

import typer


def groups() -> list[tuple[str, typer.Typer]]:
    """Command groups the platform adds to the pg-gym root; a name already present is merged into it."""
    from . import (
        artifacts,
        auth,
        benchmark,
        catalog,
        context,
        inference,
        jobs,
        models,
        platform,
        resources,
        rl,
        server,
    )

    return [
        ("platform", platform.app),
        ("benchmark", benchmark.app),
        ("jobs", jobs.app),
        ("context", context.app),
        ("auth", auth.app),
        ("suites", catalog.suites),
        ("tasks", catalog.tasks),
        ("models", models.app),
        ("artifacts", artifacts.app),
        ("inference", inference.app),
        ("rl", rl.app),
        ("server", server.app),
        *(
            (kind, resources.group(kind))
            for kind in ("connections", "credentials", "profiles")
        ),
    ]


__all__ = ["groups"]

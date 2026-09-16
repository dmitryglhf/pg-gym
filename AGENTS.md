# AGENTS.md

## Checks

```sh
uv run ruff check src tests suites
uv run ty check src
uv run pytest
```

Run all checks before committing.

## Style

Prefer names and module boundaries over comments. Keep comments short and rare. Explain constraints, not control flow. Do not use em dashes.

Keep Markdown paragraphs on one line.

## Isolation

Scored tasks run in disposable containers. Suite data, prior runs and operator secrets must not be mounted into a task container.

Task data is sent through stdin. Results leave the container through the execution backend.

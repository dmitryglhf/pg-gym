doc:
    uv run --group docs mkdocs serve

check:
    uv run ruff check src tests suites
    uv run ty check src
    uv run pytest

upd-hooks:
    prek uninstall
    prek install

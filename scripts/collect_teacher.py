"""Collect teacher trajectories for agentic SFT.

Each task runs in the task container as usual, but markov is driven from here
through markov-sdk while a local recording proxy keeps every model call. Needs
the collect group: `uv sync --group collect`.

    uv run scripts/collect_teacher.py --run local/collect/teacher-2026-09-17 \\
        --suite sql-function-set --split train --task area --task cbrt

    uv run scripts/collect_teacher.py --run local/collect/teacher-2026-09-17 --summary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from postgres_gym import settings
from postgres_gym.collect import run


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--run", type=Path, required=True, help="run directory (resumable)"
    )
    parser.add_argument(
        "--suite", action="append", help="suite id; repeatable, default both"
    )
    parser.add_argument("--split", default="train", help="suite split, default train")
    parser.add_argument("--task", action="append", help="task name; repeatable")
    parser.add_argument("--limit", type=int, help="run at most N tasks per suite")
    parser.add_argument("--model", default=run.DEFAULT_MODEL, help="pgpro model id")
    parser.add_argument("--image", default=settings.TASK_IMAGE, help="task image")
    parser.add_argument("--max-turns", type=int, default=60, help="GOOSE_MAX_TURNS")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=28000,
        help="prompt tokens before the run is cut; 0 disables",
    )
    parser.add_argument(
        "--agent-timeout", type=int, default=1800, help="seconds for one agent turn"
    )
    parser.add_argument(
        "--attempts", type=int, default=1, help="attempts per task until it passes"
    )
    parser.add_argument(
        "--workers", type=int, default=2, help="parallel task containers"
    )
    parser.add_argument(
        "--upstream",
        help="gateway host for the proxy, default from PGPRO_HOST or MARKOV_BASE_URL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="continue a run frozen with another harness",
    )
    parser.add_argument(
        "--summary", action="store_true", help="only recompute and print summary.json"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    if args.summary:
        summary = run.summarize(args.run)
        (args.run / run.SUMMARY_FILE).write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
    else:
        summary = run.collect(
            args.run,
            args.suite,
            split=args.split,
            tasks=args.task,
            limit=args.limit,
            config=run.RunConfig(
                model=args.model,
                image=args.image,
                max_turns=args.max_turns,
                token_budget=args.token_budget or None,
                agent_timeout=args.agent_timeout,
            ),
            attempts=args.attempts,
            workers=args.workers,
            upstream=args.upstream,
            force=args.force,
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

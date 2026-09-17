"""Container entry point: run one scored task and write its record.

Only the standard library and the postgres_gym core are imported here; the task
image has no typer.
"""

from __future__ import annotations

import argparse
import json
import sys

from postgres_gym import settings
from postgres_gym.core import agents, records, registry, runner
from postgres_gym.core import langfuse as lf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="postgres-gym-worker")
    parser.add_argument("task")
    parser.add_argument("--suite")
    parser.add_argument("--agent", default="cli:markov")
    parser.add_argument("--level", default="L0")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-base-url")
    return parser


def run(args: argparse.Namespace) -> dict:
    settings.use_suite(args.suite)
    suite = registry.load(args.suite)
    if settings.REQUIRE_LANGFUSE:
        lf.require()
    runner.require_provider_key(args.agent)
    runner.scored_run_is_allowed(args.agent)
    kwargs = {} if args.agent in agents.REGISTRY else {"level": args.level}
    record = runner.guarded(
        suite,
        args.task,
        args.agent,
        judge=args.judge,
        judge_model=args.judge_model,
        judge_base_url=args.judge_base_url,
        **kwargs,
    )
    records.save(record, args.task, args.agent, args.level)
    return record


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    record = run(args)
    public = {key: value for key, value in record.items() if key != "agent_meta"}
    print(json.dumps(public, indent=2, ensure_ascii=False)[:3000])
    if record.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()

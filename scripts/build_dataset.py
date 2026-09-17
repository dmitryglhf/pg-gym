"""Build the agent SFT dataset from one or more collection runs.

    uv run scripts/build_dataset.py --run local/collect/teacher-2026-09-17 \\
        --out local/datasets/agent-sft-2026-09-17
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from postgres_gym.collect import dataset


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--run",
        type=Path,
        action="append",
        required=True,
        help="collection run; repeatable",
    )
    parser.add_argument("--out", type=Path, required=True, help="dataset directory")
    parser.add_argument(
        "--dev-fraction", type=float, default=0.1, help="share of task groups held out"
    )
    parser.add_argument("--seed", type=int, default=0, help="dev split seed")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    manifest = dataset.build(
        args.run, args.out, dev_fraction=args.dev_fraction, seed=args.seed
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

"""The Maple Test: `python -m tests.maple_test run|grade` (README.md has the details)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tests.maple_test import grade, run

HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.maple_test")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="ask every question through one arm")
    r.add_argument("--arm", choices=run.ARMS, required=True)
    r.add_argument("--model", default="claude-sonnet-5-5")
    r.add_argument(
        "--server-dir",
        type=Path,
        default=run.REPO,
        help="MapleStats checkout to serve (maplestats arm)",
    )
    r.add_argument("--label", default="", help="name for this run in the report")
    r.add_argument(
        "--alts",
        type=Path,
        default=None,
        help="folder with local clones for the openmcp and candata_mcp arms",
    )
    r.add_argument("--only", nargs="*", help="question ids, e.g. M-01 M-13")
    g = sub.add_parser("grade", help="grade every run file and write results.md")
    g.add_argument("runs", nargs="*", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        print(run.run(args.arm, args.model, args.server_dir, args.only, args.label, args.alts))
        return 0
    report = grade.grade_runs(args.runs or sorted((HERE / "runs").glob("*.jsonl")))
    (HERE / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (HERE / "results.md").write_text(grade.render(report), encoding="utf-8")
    print("wrote tests/maple_test/results.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

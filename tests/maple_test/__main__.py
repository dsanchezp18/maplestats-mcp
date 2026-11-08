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
        help="folder with local clones for the openmcp, candata_mcp, canada_data_agent and opencanada arms",
    )
    r.add_argument("--only", nargs="*", help="question ids, e.g. M-01 M-13")
    r.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    r.add_argument("--repeat", type=int, default=1, help="ask every question this many times")
    g = sub.add_parser("grade", help="grade every run file and write results.md")
    g.add_argument("runs", nargs="*", type=Path)
    g.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    g.add_argument(
        "--verify", action="store_true", help="look up cited IDs the citation cache lacks"
    )
    c = sub.add_parser(
        "costs", help="print mean cost and input tokens per question and arm (no grading)"
    )
    c.add_argument("runs", nargs="*", type=Path)
    c.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    args = parser.parse_args()
    if args.command == "costs":
        paths = args.runs or sorted(grade.SUITES[args.version].runs.glob("*.jsonl"))
        answers = [
            json.loads(line)
            for path in paths
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print("\n".join(grade.cost_per_question(answers, args.version)))
        return 0
    if args.command == "run":
        print(
            run.run(
                args.arm,
                args.model,
                args.server_dir,
                args.only,
                args.label,
                args.alts,
                args.version,
                args.repeat,
            )
        )
        return 0
    suite = grade.SUITES[args.version]
    report = grade.grade_runs(
        args.runs or sorted(suite.runs.glob("*.jsonl")), args.version, args.verify
    )
    # newline="\n": on Windows, text mode would write CRLF into LF files.
    suite.results.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    markdown = suite.results.with_suffix(".md")
    markdown.write_text(grade.render(report, args.version), encoding="utf-8", newline="\n")
    print(f"wrote {markdown.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

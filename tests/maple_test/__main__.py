"""The Maple Test: `python -m tests.maple_test run|run-many|grade|costs|estimate`.

README.md has the details.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tests.maple_test import grade, run

HERE = Path(__file__).resolve().parent


def _run_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.add_argument(
        "--server-dir",
        type=Path,
        default=run.REPO,
        help="MapleStats checkout to serve (maplestats arm)",
    )
    p.add_argument(
        "--alts",
        type=Path,
        default=None,
        help="folder with local clones for the openmcp, candata_mcp, canada_data_agent and opencanada arms",
    )
    p.add_argument("--only", nargs="*", help="question ids, e.g. M-01 M-13")
    p.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    p.add_argument(
        "--repeat", type=int, default=1, help="full passes over every question (v4: keep 1)"
    )
    p.add_argument(
        "--extra-passes",
        type=int,
        default=None,
        help="more passes over the questions the key marks extra_passes (v4 default 2)",
    )
    p.add_argument("--split", choices=("all", "dev", "test"), default="all")
    p.add_argument(
        "--workers", type=int, default=1, help="questions asked at once (hosted arms only)"
    )
    p.add_argument(
        "--frozen",
        type=Path,
        default=None,
        help="maplestats arm: serve upstream HTTP from this cassette (frozen_server.py)",
    )


def _run_kwargs(args: argparse.Namespace) -> dict:
    extra = args.extra_passes
    if extra is None:
        extra = 2 if args.version == "v4" else 0
    return {
        "model": args.model,
        "server_dir": args.server_dir,
        "only": args.only,
        "alts": args.alts,
        "version": args.version,
        "repeat": args.repeat,
        "extra_passes": extra,
        "split": args.split,
        "frozen": args.frozen,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.maple_test")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="ask every question through one arm")
    r.add_argument("--arm", choices=run.ARMS, required=True)
    r.add_argument("--label", default="", help="name for this run in the report")
    _run_options(r)
    m = sub.add_parser("run-many", help="several arms at once; local-server arms one by one")
    m.add_argument("--arms", nargs="+", choices=run.ARMS, required=True)
    _run_options(m)
    g = sub.add_parser("grade", help="grade every run file and write results.md")
    g.add_argument("runs", nargs="*", type=Path)
    g.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    g.add_argument(
        "--verify", action="store_true", help="look up cited IDs the citation cache lacks"
    )
    g.add_argument("--judge", action="store_true", help="v4: ask the LLM judge about each answer")
    g.add_argument("--judge-model", default=None)
    g.add_argument("--judge-workers", type=int, default=6)
    c = sub.add_parser(
        "costs", help="print mean cost and input tokens per question and arm (no grading)"
    )
    c.add_argument("runs", nargs="*", type=Path)
    c.add_argument("--version", choices=sorted(grade.SUITES), default="v1")
    e = sub.add_parser("estimate", help="expected wall time per arm, from earlier runs")
    e.add_argument("--version", choices=sorted(grade.SUITES), default="v4")
    e.add_argument("--repeat", type=int, default=1)
    e.add_argument("--extra-passes", type=int, default=2)
    e.add_argument("--workers", type=int, default=4)
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
    if args.command == "estimate":
        print("\n".join(run.estimate(args.version, args.repeat, args.extra_passes, args.workers)))
        return 0
    if args.command == "run":
        print(run.run(args.arm, label=args.label, workers=args.workers, **_run_kwargs(args)))
        return 0
    if args.command == "run-many":
        for path in run.run_many(args.arms, workers=args.workers, label="", **_run_kwargs(args)):
            print(path)
        return 0
    suite = grade.SUITES[args.version]
    paths = args.runs or sorted(suite.runs.glob("*.jsonl"))
    report = grade.grade_runs(paths, args.version, args.verify)
    markdown = suite.results.with_suffix(".md")
    if args.version == "v4":
        from tests.maple_test import judge, review

        questions = {q["id"]: q for q in grade.load_key("v4")}
        texts = {review.ref({"run": r}): r["response"] for r in grade.load_runs(paths)}
        if args.judge:
            overrides = (
                json.loads(suite.overrides.read_text(encoding="utf-8"))
                if suite.overrides.exists()
                else {}
            )
            review.attach(
                report,
                questions,
                texts,
                overrides,
                args.judge_model or judge.MODEL,
                args.judge_workers,
            )
        else:
            for row in report["answers"]:
                row["ref"], row["needs_review"] = review.ref(row), False
        report["summary_v4"] = review.summary(report)
        review.QUEUE.parent.mkdir(exist_ok=True)
        review.QUEUE.write_text(
            review.queue(report, texts, questions), encoding="utf-8", newline="\n"
        )
        rendered = review.render(report)
    else:
        rendered = grade.render(report, args.version)
    # newline="\n": on Windows, text mode would write CRLF into LF files.
    suite.results.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    markdown.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {markdown.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

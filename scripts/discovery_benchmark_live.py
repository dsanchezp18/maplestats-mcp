# ============================================================
# Discovery benchmark, live source-search pass
# Author: Daniel Sanchez
# Purpose: Ask the benchmark questions of the sources' own lexical search
#     (wds_search_cubes for StatCan, ckan_search_datasets for CKAN portals) and
#     record what comes back, so a later semantic index can be compared with
#     what the source already finds. Needs the network and is not part of pytest.
# Inputs:  tests/discovery_benchmark/queries.json (category statcan, ckan_*, municipal)
# Outputs: live.json in the --out folder (default tests/discovery_benchmark/latest)
# ============================================================
"""Live pass over the benchmark questions, paced to each source's rate limit.

    uv run python scripts/discovery_benchmark_live.py --limit 10

The questions go to the source verbatim, as a user would type them. WDS needs every
word in a table title and CKAN runs a Solr query, so a whole sentence is a hard lexical
query; the empty-result rate is part of what this pass measures. The in-process client
shares the server's per-source token buckets (WDS 20/s, CKAN portals 1 to 2/s), and
`--pause` adds a fixed wait between calls on top. Only a few StatCan questions carry a
verified table id (`live_expected`, taken from ids this repo's tests and smoke scripts
already use); for the rest the pass records the top results for a person to judge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

# scripts/ is not a package, so the repo root (which holds tests/) goes on the path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maplestats_mcp.modules.ckan.constants import PORTALS as CKAN_PORTALS
from maplestats_mcp.server import mcp
from tests.discovery_benchmark import runner

logger = logging.getLogger("discovery_benchmark_live")

LIVE_CATEGORIES = ("statcan", "ckan_federal", "ckan_provincial", "municipal")
DEPTH = 10


def pick_call(q: runner.Query) -> tuple[str, dict[str, Any]] | None:
    """The source search a question maps to, or None when no CKAN portal fits."""
    if q.category == "statcan":
        return "wds_search_cubes", {"query": q.query, "limit": DEPTH, "lang": q.lang}
    portal = next((key for key in q.plan_portals if key in CKAN_PORTALS), None)
    if portal is None and q.category == "ckan_federal":
        portal = "federal"
    if portal is None:
        return None
    return "ckan_search_datasets", {
        "portal": portal,
        "query": q.query,
        "rows": DEPTH,
        "lang": q.lang,
    }


def summarise_hits(tool: str, data: dict[str, Any], lang: str) -> tuple[list[str], list[str], int]:
    """Identifiers, titles and the source's total match count from one search result."""
    if tool == "wds_search_cubes":
        cubes = data.get("cubes", [])
        title = "cube_title_fr" if lang == "fr" else "cube_title_en"
        return (
            [str(cube["product_id"]) for cube in cubes],
            [cube.get(title, "") for cube in cubes],
            int(data.get("total_count", 0)),
        )
    packages = data.get("packages", [])
    return (
        [package["id"] for package in packages],
        [package["title"] for package in packages],
        int(data.get("total_count", 0)),
    )


async def run_live(queries: list[runner.Query], pause: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with Client(mcp) as client:
        for q in queries:
            call = pick_call(q)
            if call is None:
                logger.info("%s: no CKAN portal to ask, skipped", q.id)
                continue
            tool, arguments = call
            started = time.perf_counter()
            row: dict[str, Any] = {"id": q.id, "category": q.category, "lang": q.lang, "tool": tool}
            try:
                result = await client.call_tool("call_tool", {"name": tool, "arguments": arguments})
                data = result.structured_content or {}
                ids, titles, total = summarise_hits(tool, data, q.lang)
                row |= {"ids": ids, "titles": titles, "total_count": total, "error": None}
            except ToolError as exc:
                row |= {"ids": [], "titles": [], "total_count": 0, "error": str(exc)}
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            row["live_expected"] = list(q.live_expected)
            row["rank"] = (
                runner.first_rank(row["ids"], q.live_expected) if q.live_expected else None
            )
            rows.append(row)
            await asyncio.sleep(pause)
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(row["latency_ms"] for row in rows)
    verified = [row for row in rows if row["live_expected"]]
    return {
        "n": len(rows),
        "errors": sum(row["error"] is not None for row in rows),
        "empty_results": sum(row["error"] is None and row["total_count"] == 0 for row in rows),
        "verified_n": len(verified),
        "verified_recall_at_5": (
            sum(row["rank"] is not None and row["rank"] <= 5 for row in verified) / len(verified)
            if verified
            else None
        ),
        "latency_ms_p50": latencies[len(latencies) // 2] if latencies else None,
        "latency_ms_p95": latencies[max(math.ceil(0.95 * len(latencies)) - 1, 0)]
        if latencies
        else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--category",
        action="append",
        choices=LIVE_CATEGORIES,
        help="only these categories (repeat to add more); default all of them",
    )
    parser.add_argument("--limit", type=int, default=20, help="most questions to ask (default 20)")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between calls")
    parser.add_argument("--out", type=Path, default=runner.DEFAULT_OUT, help="folder for live.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    wanted = args.category or LIVE_CATEGORIES
    queries = [q for q in runner.load_queries() if q.category in wanted][: args.limit]
    rows = asyncio.run(run_live(queries, args.pause))
    summary = summarise(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "live.json"
    target.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("live pass: %s", summary)
    logger.info("wrote %s", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

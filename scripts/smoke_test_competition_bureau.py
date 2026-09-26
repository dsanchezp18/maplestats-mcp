"""Live smoke test for the competition_bureau module: reads the real
merger-review report pages, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_competition_bureau.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.competition_bureau import client


async def main() -> int:
    ok = True

    everything = await client.search_mergers(limit=3)
    print(f"OK: all reviews -> {everything.total_matched}, outcomes {everything.outcome_counts}")
    # confirmed live 2026-09-25: about 830 weekly + 1,725 archived
    ok &= everything.total_matched > 2400
    ok &= everything.reviews[0].outcome == "Ongoing"

    oil = await client.search_mergers(naics="2111", include_ongoing=False, limit=5)
    print(f"OK: NAICS 2111 concluded -> {oil.total_matched}")
    ok &= oil.total_matched > 20 and all((r.naics or "").startswith("2111") for r in oil.reviews)

    consent = await client.search_mergers(outcome="CA")
    print(f"OK: consent agreements -> {consent.total_matched}")
    ok &= consent.total_matched >= 40

    archive = await client.search_mergers(concluded_from="2015-01", concluded_to="2015-12")
    print(f"OK: concluded in 2015 -> {archive.total_matched}")
    ok &= archive.total_matched > 100 and all(r.report == "archive" for r in archive.reviews)

    french = await client.search_mergers(outcome="ARC", lang="fr", limit=1)
    print("OK: French label ->", french.reviews[0].outcome_label)
    ok &= french.reviews[0].outcome_label.startswith("Certificat")

    print(
        "\nCOMPETITION BUREAU SMOKE TEST PASSED" if ok else "\nCOMPETITION BUREAU SMOKE TEST FAILED"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

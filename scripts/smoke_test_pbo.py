"""Live smoke test for the Parliamentary Budget Officer module, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_pbo.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.pbo import client


async def main() -> int:
    ok = True

    latest = await client.search_publications()
    print(f"OK: {latest.total_matched} publications, newest {latest.publications[0].id}")
    # confirmed live 2026-09-26: 863 publications, 15 per page
    ok &= latest.total_matched > 800 and latest.returned_count == 15

    costings = await client.search_publications(types=["LEG"])
    print(f"OK: legislative costing notes -> {costings.total_matched}")
    ok &= costings.total_matched > 100 and all(p.type == "LEG" for p in costings.publications)

    carbon = await client.search_publications("carbon tax")
    print("OK: search 'carbon tax' ->", [p.id for p in carbon.publications[:3]])
    ok &= carbon.total_matched > 0

    # Economic and Fiscal Outlook 2026: tables of projections, checked 2026-09-26.
    outlook = await client.get_publication("RP-2627-002-S")
    first = outlook.tables[0].rows[0] if outlook.tables and outlook.tables[0].rows else {}
    print(f"OK: RP-2627-002-S -> {len(outlook.tables)} tables; first row {first}")
    ok &= len(outlook.tables) >= 5 and "Real GDP growth" in first

    costing = await client.get_publication("LEG-2526-012-S", lang="fr")
    print(f"OK: LEG-2526-012-S (fr) -> {[t.label for t in costing.tables]}")
    ok &= costing.has_structured_content and len(costing.tables) >= 2

    archived = await client.get_publication("LIBARC-0809-001")
    print(f"OK: LIBARC-0809-001 structured={archived.has_structured_content}")
    ok &= not archived.has_structured_content and archived.publication.pdf_url is not None

    print("\nPBO SMOKE TEST PASSED" if ok else "\nPBO SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Live smoke test for the ised.clean_growth module: reads the real Clean
Growth Hub page (EN and FR) and checks the grants and contributions
DataStore table it points to, per AGENTS.md.

Usage:
    uv run python scripts/smoke_test_ised_clean_growth.py
"""

from __future__ import annotations

import asyncio
import sys

from _smoke_common import skip_reloading, verdict

from maplestats_mcp.modules.ckan import client as ckan
from maplestats_mcp.modules.ised.clean_growth import client


async def main() -> int:
    ok = True

    english = await client.federal_investment("en")
    print("OK: federal_investment(en) headline:", english.headline.model_dump())
    ok &= english.headline.committed_cad is not None and english.headline.agreements is not None
    ok &= len(english.by_year) >= 9 and len(english.by_province) >= 8
    total = sum(r.value_cad or 0 for r in english.by_year)
    committed = english.headline.committed_cad or 0.0
    print(f"  by year sums to ${total / 1e9:.2f}B; headline ${committed / 1e9:.0f}B")
    ok &= abs(total - committed) < 2e9

    french = await client.federal_investment("fr")
    print("OK: federal_investment(fr) provinces:", [r.label for r in french.by_province][:3])
    ok &= french.by_year[-1].value_cad == english.by_year[-1].value_cad

    rows = await ckan.datastore_search("federal", english.records_resource_id, limit=1)
    print(f"OK: grants and contributions DataStore -> {rows.total_count} records")
    if rows.total_count == 0:
        skip_reloading("open.canada.ca DataStore", "grants and contributions")
    else:
        ok &= rows.total_count > 100_000

    return verdict("ISED CLEAN GROWTH", ok)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

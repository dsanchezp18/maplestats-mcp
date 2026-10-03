"""Live smoke test for the CBSA border wait times module (EN and FR).

uv run python scripts/smoke_test_cbsa.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.cbsa import client


async def main() -> int:
    ok = True

    everything = await client.border_wait_times()
    unparsed = [c.office for c in everything.crossings if c.province is None or not c.updated_at]
    print(f"OK: {everything.total_crossings} crossings, unparsed {unparsed}")
    # confirmed live 2026-10-03: 30 crossings, every location and zone parsed
    ok &= everything.total_crossings >= 25 and not unparsed
    statuses = {
        getattr(c, lane).status
        for c in everything.crossings
        for lane in ("commercial_canada_bound", "travellers_canada_bound")
    }
    print(f"OK: Canada-bound statuses -> {sorted(statuses)}")
    ok &= "other" not in statuses

    ontario = await client.border_wait_times(province="ON", direction="canada_bound")
    print(f"OK: Ontario -> {[c.office for c in ontario.crossings]}")
    ok &= ontario.returned_count >= 8 and ontario.crossings[0].travellers_us_bound is None

    french = await client.border_wait_times(crossing="peace", lang="fr")
    print(f"OK: fr Peace -> {[(c.office, c.updated) for c in french.crossings]}")
    ok &= french.returned_count >= 1 and french.crossings[0].office.startswith("Pont")

    print("\nCBSA SMOKE TEST PASSED" if ok else "\nCBSA SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

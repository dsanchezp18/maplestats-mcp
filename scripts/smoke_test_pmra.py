"""Live smoke test for the PMRA pesticide registry module (EN and FR).

uv run python scripts/smoke_test_pmra.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.pmra import client


async def main() -> int:
    ok = True

    roundup = await client.search_products("roundup")
    print(f"OK: 'roundup' current -> {roundup.total_matched}, {roundup.by_product_type}")
    # confirmed live 2026-10-03: 28 current Roundup products, all herbicides
    ok &= roundup.total_matched >= 10

    glyphosate = await client.search_products(active_ingredient="glyphosate", status="all")
    print(f"OK: glyphosate products (all) -> {glyphosate.total_matched}")
    ok &= glyphosate.total_matched >= 200

    french = await client.search_products("herbicide", lang="fr")
    print(f"OK: fr 'herbicide' -> {french.total_matched}; {french.products[0].registration_status}")
    ok &= french.total_matched > 0 and french.products[0].registration_status != "Full Registration"

    detail = await client.get_product("31153")
    ingredient = detail.ingredients[0]
    print(f"OK: 31153 -> {ingredient.name}, MRLs {ingredient.mrl_chemical} {ingredient.mrl_count}")
    ok &= (
        ingredient.mrl_chemical == "Glyphosate" and ingredient.mrl_count > 20 and bool(detail.pests)
    )

    detail_fr = await client.get_product("32446", lang="fr")
    print(
        f"OK: 32446 fr -> {detail_fr.product.product_name}, {detail_fr.ingredients[0].cas_number}"
    )
    ok &= detail_fr.ingredients[0].cas_number == "52918-63-5"

    limits = await client.get_residue_limits("glyphosate", commodity="wheat")
    print(f"OK: glyphosate on wheat -> {[(m.commodity, m.mrl_ppm) for m in limits.limits]}")
    ok &= any(m.mrl_ppm == 5.0 for m in limits.limits)

    berries = await client.get_residue_limits(commodity="bleuets", lang="fr")
    unparsed = [m for m in berries.limits if m.mrl_ppm is None]
    print(f"OK: fr bleuets -> {berries.total_matched} limits, unparsed {len(unparsed)}")
    ok &= berries.total_matched > 50 and not unparsed

    print("\nPMRA SMOKE TEST PASSED" if ok else "\nPMRA SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

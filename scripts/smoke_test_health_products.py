"""Live smoke test for the Health Canada health products module (hc_ tools).

Calls every tool's client function against health-products.canada.ca and
the canada.ca Canada Vigilance extract. Checked by hand on 2026-10-03:
- DIN 02242705 is AROMASIN (exemestane 25 MG, Pfizer, marketed).
- NPN 80000035 is Easy-Mind / Night-Cap (Phytos Inc.), Scutellaria.
- MDALL licence 102449 is the Dexcom G6 CGM system, class 3, 8 devices.
- Canada Vigilance report 195 (1973) names codeine as the suspect drug.
- The reaction search reads about 102 MB of the extract (about a minute)
  and finds over 2,000 myocarditis reports.
The first natural health product search reads the whole licence table
(about a minute before its first byte).
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.health_products.dpd import client as dpd
from maplestats_mcp.modules.health_products.lnhpd import client as lnhpd
from maplestats_mcp.modules.health_products.mdall import client as mdall
from maplestats_mcp.modules.health_products.vigilance import client as vigilance


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += 0 if ok else 1

    # hc_drug_search_products
    found = await dpd.search_products(brand="tylenol", status="marketed", limit=5)
    check(found.total_matched > 10, f"hc_drug_search_products brand -> {found.total_matched}")
    found = await dpd.search_products(ingredient="exemestane")
    check(
        any(p.din == "02242705" for p in found.products),
        f"hc_drug_search_products ingredient -> {found.total_matched}",
    )
    found = await dpd.search_products(company="pfizer", schedule="narcotic", lang="fr")
    check(
        found.total_matched >= 0,
        f"hc_drug_search_products company+schedule fr -> {found.by_status}",
    )
    # hc_drug_get_product
    product = await dpd.get_product("02242705")
    check(
        product.product.brand_name == "AROMASIN"
        and product.active_ingredients[0].name == "EXEMESTANE",
        f"hc_drug_get_product -> {product.product.brand_name}, {product.schedules}",
    )
    product = await dpd.get_product(drug_code=1017, lang="fr")
    check(
        product.veterinary_species == ["Chiens"],
        f"hc_drug_get_product vet fr -> {product.veterinary_species}",
    )
    # hc_drug_search_ingredients
    ingredients = await dpd.search_ingredients("acetaminophen", limit=3)
    check(
        ingredients.ingredients[0].product_count > 1000,
        f"hc_drug_search_ingredients -> {ingredients.ingredients[0]}",
    )

    # hc_nhp_get_product
    nhp = await lnhpd.get_product("80000035", lang="fr")
    check(
        bool(nhp.medicinal_ingredients) and nhp.routes == ["Orale"],
        f"hc_nhp_get_product -> {[n.product_name for n in nhp.names]}",
    )
    # hc_nhp_search_products
    nhps = await lnhpd.search_products("melatonin", limit=3)
    check(nhps.licences_matched > 100, f"hc_nhp_search_products -> {nhps.licences_matched} NPNs")

    # hc_device_search_licences
    licences = await mdall.search_licences("insulin pump")
    check(licences.total_matched >= 1, f"hc_device_search_licences -> {licences.by_risk_class}")
    # hc_device_get_licence
    licence = await mdall.get_licence(102449)
    check(
        licence.device_count >= 5 and licence.company is not None,
        f"hc_device_get_licence -> {licence.licence.licence_name}, {licence.device_count} devices",
    )
    # hc_device_search_devices
    devices = await mdall.search_devices("dexcom g7", limit=5)
    check(devices.total_matched >= 1, f"hc_device_search_devices -> {devices.total_matched}")
    devices = await mdall.search_devices(identifier="STE-FT-008", active_only=False)
    check(
        devices.total_matched >= 1, f"hc_device_search_devices identifier -> {devices.devices[:1]}"
    )

    # hc_vigilance_get_report
    report = await vigilance.get_report(195)
    check(
        any(d.role == "Suspect" and d.drug_name == "CODEINE" for d in report.drugs),
        f"hc_vigilance_get_report -> {report.date_received}, {report.reactions}",
    )
    # hc_vigilance_list_codes
    codes = await vigilance.list_codes(lang="fr")
    check(len(codes.tables) == 5, f"hc_vigilance_list_codes -> {list(codes.tables)}")
    # hc_vigilance_search_reactions
    hits = await vigilance.search_reactions("myocarditis", limit=5)
    check(
        hits.complete and hits.reports_matched > 1000,
        f"hc_vigilance_search_reactions -> {hits.reports_matched} reports, {hits.scanned_mb} MB",
    )
    partial = await vigilance.search_reactions("headache", max_scan_mb=20, limit=3)
    check(
        not partial.complete,
        f"hc_vigilance_search_reactions ceiling -> {partial.provenance.coverage}",
    )

    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

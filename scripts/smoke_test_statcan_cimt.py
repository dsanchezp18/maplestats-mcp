"""Live smoke test for the statcan.cimt module's client.py: calls the real,
undocumented CIMT web-application API and its code lists (not mocks), per
AGENTS.md's "lesson from auditing the StatCan module", and reconciles the
all-commodity total with WDS table 12-10-0011-01.

Usage:
    uv run python scripts/smoke_test_statcan_cimt.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.cimt import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.http import api_post

WDS_LATEST = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromCubePidCoordAndLatestNPeriods"
# 12-10-0011-01, customs basis, unadjusted, all countries: Export 1.2.1.1.1, Import 1.1.1.1.1.
WDS_COORDINATES = {"exports": "1.2.1.1.1.0.0.0.0.0", "imports": "1.1.1.1.1.0.0.0.0.0"}


async def wds_million(direction: str, period: str) -> float:
    body = await api_post(
        WDS_LATEST,
        json_body=[{"productId": 12100011, "coordinate": WDS_COORDINATES[direction], "latestN": 6}],
    )
    for point in body[0]["object"]["vectorDataPoint"]:
        if point["refPer"].startswith(period):
            return float(point["value"])
    raise AssertionError(f"WDS has no {direction} value for {period}")


async def main() -> int:
    ok = True

    periods = await client.get_periods()
    latest = periods.latest_period
    print(f"OK: get_periods -> {periods.first_period} to {latest}")
    ok &= periods.first_period == "1988-01" and latest >= "2026-07"

    oil = await client.search_commodities("crude petroleum", level="hs6")
    print(f"OK: search_commodities('crude petroleum') -> {oil.total_matched} codes")
    ok &= any(m.code == "270900" for m in oil.commodities)
    oil_fr = await client.search_commodities("pétrole brut", level="hs6", lang="fr")
    ok &= any(m.code == "270900" for m in oil_fr.commodities)
    national = await client.search_commodities("2709", level="national")
    ok &= any(m.code == "27090010" for m in national.commodities)
    chapters = await client.search_commodities("27", level="chapter")
    ok &= chapters.commodities[0].code == "27"
    # The import detail list is a 16 MB file; this is the one live check of it.
    imports_detail = await client.search_commodities("2709", direction="imports", level="national")
    print(f"OK: search_commodities(imports, national) -> {imports_detail.total_matched} codes")
    ok &= imports_detail.total_matched > 5 and len(imports_detail.commodities[0].code) == 10

    china = await client.search_partners("china")
    ok &= china.partners[0].code == 553
    texas = await client.search_partners("texas", kind="us_state")
    ok &= texas.partners[0].code == 44
    alberta = await client.search_partners("AB", kind="province")
    ok &= alberta.partners[0].code == 48
    print("OK: search_partners country, us_state, province")

    # Crude oil to the US, a year of months and the same year annualized.
    monthly = await client.get_trade(
        "exports", "2025-01", "2025-12", hs_code="270900", partner="US"
    )
    annual = await client.get_trade(
        "exports", "2025-01", "2025-12", hs_code="270900", partner="US", annualize=True
    )
    print(
        f"OK: get_trade crude to US 2025 -> {monthly.returned_count} months, "
        f"{annual.rows[0].value_cad:,.0f} dollars annualized"
    )
    ok &= monthly.returned_count == 12 and not monthly.truncated
    ok &= abs(monthly.returned_value_cad - annual.rows[0].value_cad) < 1.0
    ok &= annual.rows[0].period == "2025" and annual.rows[0].unit is not None

    states = await client.get_trade(
        "exports",
        latest,
        latest,
        hs_code="87",
        us_state="Texas",
        provinces=["ON", "Quebec"],
        limit=5,
    )
    ok &= states.returned_count == 5 and states.truncated
    ok &= all(r.us_state == "Texas" for r in states.rows)
    imports = await client.get_trade(
        "imports", latest, latest, hs_code="2709", provinces=["AB"], hs_level="national"
    )
    ok &= imports.returned_count > 0 and all(len(r.hs_code) == 10 for r in imports.rows)
    print("OK: get_trade with US state, provinces, limit and imports at national level")

    # Reconciliation: every HS6 export row of one month adds up to the total WDS
    # publishes. Imports run past the 5,000-row tool limit (about 6,000 HS6 rows), so
    # their total is checked through the all-partner total of get_top_partners.
    everything = await client.get_trade("exports", latest, latest, limit=5000)
    wds_exports = await wds_million("exports", latest)
    rows_million = everything.returned_value_cad / 1e6
    print(
        f"RECONCILE exports {latest}: CIMT {everything.returned_count} rows = "
        f"{rows_million:,.1f} million; WDS 12-10-0011-01 = {wds_exports:,.1f} million"
    )
    ok &= not everything.truncated and abs(rows_million - wds_exports) <= 0.1
    import_partners = await client.get_top_partners("imports", period=latest)
    wds_imports = await wds_million("imports", latest)
    print(
        f"RECONCILE imports {latest}: CIMT total {import_partners.total_value_cad / 1e6:,.1f} "
        f"million; WDS = {wds_imports:,.1f} million"
    )
    ok &= abs(import_partners.total_value_cad / 1e6 - wds_imports) <= 0.1

    partners = await client.get_top_partners("exports", period=latest)
    ok &= partners.partners[0].name.startswith("United States")
    ok &= abs(partners.total_value_cad / 1e6 - wds_exports) <= 0.1
    states_view = await client.get_top_partners(
        "imports", period=latest, hs_chapter="27", view="us_state"
    )
    ok &= states_view.returned_count > 0
    print(
        f"OK: get_top_partners -> {partners.partners[0].name} {partners.partners[0].share_of_total:.1%}"
    )

    commodities = await client.get_top_commodities("exports", province="AB", partner="US")
    ok &= commodities.commodities[0].code == "270900"
    provinces = await client.get_province_breakdown("exports", partner="China", hs_chapter="12")
    ok &= provinces.returned_count > 3
    print("OK: get_top_commodities and get_province_breakdown")

    chapter = await client.get_series("exports", "27", partner="US")
    ok &= chapter.returned_count >= 60
    commodity = await client.get_series("exports", "710812")
    ok &= {"domestic_value", "domestic_quantity"} <= {p.measure for p in commodity.points}
    ok &= commodity.unit is not None
    import_series = await client.get_series("imports", "2709000049")
    ok &= {"value", "quantity"} <= {p.measure for p in import_series.points}
    print("OK: get_series chapter, commodity and import series")

    for label, call in (
        (
            "an unknown partner raises NotFound",
            client.get_trade("exports", "2026-06", "2026-07", partner="Atlantis"),
        ),
        ("a future month raises InvalidInput", client.get_trade("exports", "2026-07", "2099-01")),
        (
            "a 9-digit code raises InvalidInput",
            client.get_trade("exports", "2026-06", "2026-07", hs_code="270900100"),
        ),
    ):
        try:
            await call
            print(f"FAIL: expected an error: {label}")
            ok = False
        except (InvalidInput, NotFound):
            print(f"OK: {label}")

    print("\nSTATCAN CIMT SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

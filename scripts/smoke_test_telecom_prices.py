"""Live smoke test for the CRTC Communications Market Reports module (telecom_prices).

uv run python scripts/smoke_test_telecom_prices.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.telecom_prices import client


async def main() -> int:
    ok = True

    # Confirmed live 2026-10-27: version 11 (2026-05-14), 2016-2025, 5 GB lowest
    # national price 46.91 in 2020 and 30.08 in 2025.
    mobile = await client.get_plan_prices("mobile", plan="5 GB", from_year=2020)
    print(
        f"OK: mobile 5 GB v{mobile.version} ({mobile.released}) -> "
        f"{[(p.year, round(p.average_price or 0, 2)) for p in mobile.points]}"
    )
    ok &= mobile.years[0] == 2016 and mobile.years[-1] >= 2025 and len(mobile.points) >= 6
    ok &= all(p.technology == "lowest" and p.geography == "Canada" for p in mobile.points)

    internet = await client.get_plan_prices(
        "internet", plan="50/10 Mbps", province="QC", region="all", lang="fr"
    )
    print(f"OK: Internet 50/10 Quebec -> {internet.total_matched} averages, plans {internet.plans}")
    ok &= internet.total_matched >= 20 and "50/10 Mbps" in internet.plans

    # Several provinces in one call (CRTC averages): 2024 urban 50 GB lowest
    # price was 37.00 in AB and ON, 33.50 in QC (checked 2026-10-27).
    several = await client.get_plan_prices(
        "mobile", plan="50 GB", province="AB, ON, QC", region="urban", from_year=2024
    )
    shown = [(p.geography, p.year, p.average_price) for p in several.points]
    print(f"OK: 50 GB urban AB, ON, QC -> {shown}")
    ok &= ("AB", 2024, 37.0) in shown and ("QC", 2024, 33.5) in shown

    # City (CMA) means computed from the Prix-Prices sheet, checked 2026-10-27
    # against a government analyst's figures: 50 GB in 2024, Edmonton 36.75,
    # Toronto 36.75, Winnipeg 35.57, Regina 40.20, Victoria 36.75, Québec 37.67;
    # in 2022 Calgary 84.17 and Ottawa-Gatineau 72.50. Edmonton's per-provider
    # mean (37.00) equals the CRTC's AB urban average.
    cities = await client.get_city_plan_prices(
        "mobile",
        city=["Edmonton", "Toronto", "Winnipeg", "Regina", "Victoria", "quebec"],
        plan="50 GB",
        from_year=2024,
        to_year=2024,
    )
    means = {a.cma: a.average_price for a in cities.averages}
    print(f"OK: 50 GB by CMA, 2024 -> {means}")
    ok &= means == {
        "Edmonton": 36.75,
        "Toronto": 36.75,
        "Winnipeg": 35.57,
        "Regina": 40.2,
        "Victoria": 36.75,
        "Québec": 37.67,
    }
    edmonton = next(a for a in cities.averages if a.cma == "Edmonton")
    ok &= edmonton.lowest_per_provider_average == 37.0 and edmonton.providers == 4
    older = await client.get_city_plan_prices(
        "mobile", city="Calgary, Ottawa, Montreal", plan="50GB", from_year=2022, include_rows=True
    )
    pairs = {(a.cma, a.year): a.average_price for a in older.averages}
    print(f"OK: 50 GB 2022 on -> {pairs}; {len(older.notes) - 1} notes, {older.rows_matched} rows")
    ok &= pairs[("Calgary", 2022)] == 84.17 and pairs[("Ottawa-Gatineau", 2022)] == 72.5
    ok &= not any(year >= 2024 for _, year in pairs)
    ok &= sum("from 2024 the CRTC surveys" in n for n in older.notes) == 3
    ok &= older.rows_matched >= 30 and older.rows[0].provider is not None
    ok &= len(older.cmas) == 24 and sum(2025 in c.years for c in older.cmas) == 13
    internet = await client.get_city_plan_prices("internet", city="Gatineau", plan="50/10")
    print(f"OK: Internet 50/10 Ottawa-Gatineau -> {internet.total_matched} years")
    ok &= internet.total_matched == 8 and internet.averages[0].providers is None

    for sector, table in (("mobile", "MB-S3"), ("internet", "N-S4")):
        listing = await client.list_market_tables(sector)
        ids = [t.table_id for t in listing.tables]
        print(f"OK: {sector} tables -> {len(ids)}, e.g. {ids[:4]}")
        ok &= table in ids
        result = await client.get_market_table(table, sector)
        last = result.observations[-1]
        print(f"OK: {table} {result.title!r} -> {len(result.observations)} values, last {last}")
        ok &= len(result.observations) >= 20 and not result.notes[0].startswith("Type")

    french = await client.get_market_table("MB-F12", "mobile", lang="fr")
    print(f"OK: French ARPU tab {french.table_id} -> {french.title}")
    ok &= french.table_id == "MB-G12" and len(french.observations) >= 12

    trends = await client.get_quarterly_trends("mobile", metric="wireless data traffic")
    print(
        f"OK: quarterly v{trends.version} ({trends.released}) -> "
        f"{trends.provenance.coverage}, last {trends.observations[-1].period}"
    )
    ok &= trends.total_matched >= 40 and trends.observations[-1].year >= 2026
    for service in ("internet", "wireline", "tv_distribution"):
        other = await client.get_quarterly_trends(service, from_year=2025)
        print(f"OK: quarterly {service} -> {other.total_matched} values since 2025")
        ok &= other.total_matched > 0

    print("\nTELECOM PRICES SMOKE TEST PASSED" if ok else "\nTELECOM PRICES SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

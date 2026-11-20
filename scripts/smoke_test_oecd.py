"""Live smoke test for the oecd module: calls the real OECD Data Explorer API
(not mocks) for every client function and every tool, per AGENTS.md's
"lesson from auditing the StatCan module".

The OECD allows 60 data downloads an hour; a full run spends about 20, so
do not run it twice in a row.

Usage:
    uv run python scripts/smoke_test_oecd.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.modules.oecd import client, constants
from maplestats_mcp.server import mcp
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _expect_error(label: str, coro, exc_type: type[Exception]) -> bool:
    try:
        await coro
    except exc_type as exc:
        print(f"OK: {label} -> {type(exc).__name__}: {str(exc)[:140]}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False
    print(f"FAIL: {label} -> no error")
    return False


async def main() -> bool:
    ok = True

    # 1,552 dataflows on 2026-11-07.
    for query, expected in (
        ("economic outlook", "DSD_EO@DF_EO"),
        ("unit labour costs", "DSD_PDB@DF_PDB_ULC_Q"),
        ("house prices", "DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES"),
        ("revenue statistics oecd countries", "DSD_REV_COMP_OECD@DF_RSOECD"),
        ("composite leading indicators", "DSD_STES@DF_CLI"),
    ):
        found = await client.search_datasets(query, limit=5)
        ids = [d.id for d in found.datasets]
        print(f"OK: search {query!r} -> {found.total_matches} matches, top {ids[:3]}")
        if expected not in ids:
            print(f"FAIL: {expected} not in the top 5 for {query!r}")
            ok = False

    for dataset in ("DSD_EO@DF_EO", "DSD_PDB@DF_PDB", "DSD_STES@DF_CLI"):
        structure = await client.describe_dataset(dataset, lang="fr")
        print(
            f"OK: describe {dataset} -> {structure.key_template} e.g. {structure.example_key!r}, "
            f"updated {structure.last_updated}, {structure.observation_count} obs"
        )
        ok &= all(d.codes for d in structure.dimensions) and "CAN" in structure.example_key

    eo = await client.get_data("DSD_EO@DF_EO", "CAN+USA.GDPV_ANNPCT.A", start_period="2024")
    print("OK: EO ->", [(s.key, s.unit, s.latest_period, s.latest_value) for s in eo.series])
    ok &= len(eo.series) == 2 and eo.rows[0].ref_area == "CAN" and eo.rows[0].frequency == "Annual"

    # The quarterly GDP example in oecd_get_data's docstring: the dataflow and key come from
    # DBnomics' copy of it (indexed 2026-06-16), because sdmx.oecd.org answered a Cloudflare
    # challenge on 2026-11-17, so this is the first run of the key against the OECD itself.
    qna = await client.get_data(
        "DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD",
        "Q.Y.CAN.S1.S1.B1GQ._Z._Z._Z.PC.L.G1.T0102",
        last_n=2,
    )
    print("OK: quarterly GDP ->", [(s.key, s.latest_period, s.latest_value) for s in qna.series])
    ok &= len(qna.series) == 1 and "-Q" in (qna.series[0].latest_period or "")

    revenue = await client.get_data(
        "OECD.CTP.TPS,DSD_REV_COMP_OECD@DF_RSOECD",
        "CAN.TAX_REV.S13.T_1100+T_5000._T.PT_B1GQ.A",
        last_n=2,
        lang="fr",
    )
    print("OK: revenue (fr) ->", [(s.key, s.ref_area_name, s.unit) for s in revenue.series])
    ok &= len(revenue.series) == 2

    for indicator in constants.INDICATORS:
        result = await client.compare_countries(indicator, compare_with=["G7"])
        canada = result.countries[0]
        print(
            f"OK: {indicator} -> CA {canada.latest_period} {canada.latest_value} "
            f"({canada.unit}), rank {result.canada_rank}/{result.ranked_countries} in "
            f"{result.rank_period}; notes {result.notes[:1]}"
        )
        ok &= canada.area_code == "CAN" and len(result.countries) >= 4

    french = await client.compare_countries("tax_to_gdp", ["US", "AU", "OECD_REP"], lang="fr")
    print(f"OK: compare (fr) -> {french.indicator_label} | {french.countries[0].area_name}")
    ok &= french.indicator_label.startswith("Recettes fiscales")
    return ok


async def errors() -> bool:
    """Errors that the client catches before spending a download, and one 404."""
    ok = True
    ok &= await _expect_error(
        "short key", client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT"), InvalidInput
    )
    ok &= await _expect_error(
        "unknown code", client.get_data("DSD_EO@DF_EO", "ZZZ.GDPV_ANNPCT.A"), InvalidInput
    )
    ok &= await _expect_error("unknown dataset", client.describe_dataset("DSD_NOPE@DF"), NotFound)
    ok &= await _expect_error(
        "archived dataset", client.describe_dataset("DSD_PDB@DF_PDB_LV"), NotFound
    )
    ok &= await _expect_error(
        "future period",
        client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT.A", start_period="2040"),
        NotFound,
    )
    ok &= await _expect_error("unknown indicator", client.compare_countries("gdp"), InvalidInput)
    return ok


async def through_server() -> bool:
    """Every tool once through call_tool, as a client reaches it (cached calls)."""
    ok = True
    calls = [
        ("oecd_search_datasets", {"query": "productivity", "lang": "fr"}),
        ("oecd_describe_dataset", {"dataset": "DSD_EO@DF_EO"}),
        (
            "oecd_get_data",
            {"dataset": "DSD_EO@DF_EO", "key": "CAN+USA.GDPV_ANNPCT.A", "start_period": "2024"},
        ),
        ("oecd_compare_countries", {"indicator": "real_gdp_growth", "compare_with": ["G7"]}),
        (
            "oecd_query_dataset",
            {
                "dataset": "DSD_EO@DF_EO",
                "sql": "SELECT ref_area, max(value) FROM obs GROUP BY ref_area",
                "filters": {"REF_AREA": ["CAN", "USA"], "MEASURE": ["GDPV_ANNPCT"]},
                "start_period": "2024",
            },
        ),
    ]
    async with Client(mcp) as session:
        for name, args in calls:
            result = await session.call_tool("call_tool", {"name": name, "arguments": args})
            text = next(c.text for c in result.content if isinstance(c, TextContent))
            data = json.loads(text)
            print(f"OK: call_tool({name}) -> {sorted(data)[:6]}")
            ok &= not result.is_error
    return ok


async def queries() -> bool:
    """oecd_query_dataset: a ranking answered, and the checks refusing wrong sums."""
    from maplestats_mcp.modules.oecd import query

    ok = True
    base = {"MEASURE": ["UNE_LF"], "SEX": ["_T"], "AGE": ["Y_GE15"], "ADJUSTMENT": ["Y"],
            "FREQ": ["A"], "UNIT_MEASURE": ["PT_LF_SUB"]}  # fmt: skip
    ranked = await query.query_dataset(
        "DSD_LFS@DF_IALFS_INDIC",
        "SELECT ref_area, value FROM obs WHERE period = '2024' ORDER BY value DESC LIMIT 3",
        filters=base,
        start_period="2024",
        end_period="2024",
    )
    print(f"OK: query ranking -> {ranked.rows}")
    ok &= ranked.row_count == 3
    levels = {**base, "MEASURE": ["UNE"], "UNIT_MEASURE": ["PS"], "REF_AREA": ["G7", "CAN", "USA"]}
    try:
        await query.query_dataset(
            "DSD_LFS@DF_IALFS_INDIC",
            "SELECT period, sum(value) FROM obs GROUP BY period",
            filters=levels,
            start_period="2023",
        )
    except InvalidInput as exc:
        print(f"OK: query refuses the G7 with members -> {str(exc)[:110]}")
        ok &= "total_with_parts" in str(exc)
    else:
        print("FAIL: query did not refuse the G7 with members")
        ok = False
    return ok


async def run() -> int:
    ok = await main()
    ok &= await errors()
    ok &= await queries()
    ok &= await through_server()
    print("ALL OK" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))

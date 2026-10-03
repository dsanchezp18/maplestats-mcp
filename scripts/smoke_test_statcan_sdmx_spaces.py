"""Live smoke test for statcan.sdmx_spaces: calls StatCan's real CCEI and
shared SDMX spaces and the sdmx-sfs search service (not mocks), per AGENTS.md's
"lesson from auditing the StatCan module".

Usage:
    uv run python scripts/smoke_test_statcan_sdmx_spaces.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.sdmx_spaces import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    # Dataflow lists: counts confirmed live 2026-10-02 (245 and 238 flows).
    ccei = await client.list_flows("ccei", limit=250)
    print(f"OK: list_flows(ccei) -> {ccei.total_flows} flows {ccei.agencies}")
    ok &= ccei.total_flows >= 200 and ccei.non_production_flows == ccei.total_flows
    ok &= "CCEI" in ccei.agencies and "STC" in ccei.agencies
    shared = await client.list_flows("stcshared", agency="CITH", limit=250)
    print(f"OK: list_flows(stcshared, agency=CITH) -> {shared.matched} flows")
    ok &= shared.matched >= 90
    ghg = await client.list_flows("ccei", query="greenhouse gas", agency="CCEI")
    print("OK: list_flows(ccei, 'greenhouse gas', CCEI) ->", [f.flow for f in ghg.flows])
    ok &= any(f.id == "GHG_IPCC_TABLE" for f in ghg.flows)
    fr = await client.list_flows("ccei", query="gaz à effet de serre", lang="fr")
    print(f"OK: list_flows(ccei, fr) -> {fr.matched} flows")
    ok &= fr.matched > 0

    # Search service: ccei tenant, the three shared tenants, a facet filter.
    found = await client.search_flows("ccei", "greenhouse gas")
    print(
        f"OK: search_flows(ccei, 'greenhouse gas') -> {found.found} found, {len(found.flows)} hits"
    )
    ok &= found.found >= 20 and len(found.flows) > 0 and len(found.facets) > 0
    ok &= all(h.flow.count(",") == 2 for h in found.flows)
    annual = min(
        next(f for f in found.facets if f.name == "Frequency").values, key=lambda v: v.count
    )
    narrowed = await client.search_flows(
        "ccei", "greenhouse gas", filters={"Frequency": [annual.filter_value]}
    )
    print(f"OK: facet filter {annual.label!r} -> {narrowed.found} found")
    ok &= 0 < narrowed.found < found.found
    trade = await client.search_flows("stcshared", "trade")
    print(f"OK: search_flows(stcshared, 'trade') -> {trade.found} found in {trade.tenants}")
    ok &= trade.found > 20 and len(trade.tenants) == 3
    for tenant in ("rural", "cith", "pceip"):
        one = await client.search_flows("stcshared", "employment", tenant=tenant, limit=3)
        print(f"OK: search_flows(stcshared, tenant={tenant}) -> {one.found} found")
        ok &= one.tenants == [tenant]
    none = await client.search_flows("ccei", "zzzqqqxx")
    ok &= none.found == 0 and none.flows == []

    # Structure of the ECCC inventory flow: key order, codes with data, size.
    structure = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")
    print(
        f"OK: get_structure -> {structure.flow}, key {'.'.join(structure.key_order)}, "
        f"{structure.observation_count} observations, {structure.start_period} to "
        f"{structure.end_period}"
    )
    ok &= structure.key_order == ["FREQ", "REF_AREA", "IPCC_CATEGORY", "GHG_ECCC"]
    ok &= structure.non_production and (structure.observation_count or 0) > 100_000
    area = structure.dimensions[1]
    ok &= area.code_count < area.codelist_size and {c.id for c in area.codes} >= {"CA", "CA_AB"}
    alberta = await client.get_structure(
        "ccei", "GHG_IPCC_TABLE", dimension="REF_AREA", code_query="alberta"
    )
    ok &= [c.id for c in alberta.dimensions[0].codes] == ["CA_AB"]

    # Data: latest observations, a period range, several codes, projections.
    latest = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA_AB.0.CO2EQ")
    obs = latest.series[0].observations
    print(
        f"OK: get_data(Alberta total CO2EQ) -> {obs[-1].period}={obs[-1].value} {latest.series[0].attributes}"
    )
    ok &= len(obs) == 12 and int(obs[-1].period) >= 2024 and obs[-1].value is not None
    ok &= latest.series[0].attributes.get("UNIT_MEASURE") == "KT"
    ok &= "NonProductionDataflow" in (latest.provenance.coverage or "")
    ok &= "Open Government Licence" in (latest.provenance.licence or "")
    ranged = await client.get_data(
        "ccei", "CCEI,GHG_IPCC_TABLE", "A.CA+CA_AB.0.CO2EQ", start_period="2020", end_period="2022"
    )
    print(f"OK: get_data(range) -> {ranged.row_count} rows in {ranged.series_total} series")
    ok &= ranged.row_count == 6 and ranged.series_total == 2
    by_id = await client.get_data("ccei", "GHG_IPCC_TABLE", "A.CA.0.CO2EQ", last_n_observations=2)
    ok &= by_id.row_count == 2 and by_id.flow == "CCEI,GHG_IPCC_TABLE,2.0"
    projections = await client.search_flows("ccei", "projections")
    proj = next(h for h in projections.flows if h.id.startswith("GHG_IPCC_PROJ"))
    proj_structure = await client.get_structure("ccei", proj.flow)
    print(f"OK: projections flow {proj.flow} key {'.'.join(proj_structure.key_order)}")
    ok &= len(proj_structure.dimensions) >= 4

    # Shared space: ISC long-term drinking water advisories (37 in 2025).
    water = await client.get_data(
        "stcshared", "CA1.QOL.ISC,DF_WATER_ADVISORY", "A.CA.WAT_ADV", last_n_observations=3
    )
    print(f"OK: water advisories -> {[(o.period, o.value) for o in water.series[0].observations]}")
    ok &= water.row_count >= 1 and water.series[0].observations[-1].value is not None
    ok &= "Open Government Licence" in (water.provenance.licence or "")

    # Errors the live service gives, each mapped to a typed error.
    checks = [
        (
            "key with no data",
            NotFound,
            client.get_data(
                "ccei",
                "CCEI,GHG_IPCC_TABLE",
                "A.ZZ.0.CO2EQ",
                start_period="1990",
                end_period="1990",
            ),
        ),
        (
            "extra key segment",
            InvalidInput,
            client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0.CO2EQ.X"),
        ),
        ("whole large flow", InvalidInput, client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "all")),
        (
            "bad period",
            InvalidInput,
            client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0.CO2EQ", start_period="2020/01"),
        ),
        ("unknown flow", NotFound, client.get_data("ccei", "CCEI,NO_SUCH_FLOW", "A.CA")),
        ("unknown id", NotFound, client.get_structure("ccei", "NO_SUCH_FLOW")),
        (
            "flow without data",
            NotFound,
            client.get_data("stcshared", "CA1.RURAL,DF_RURAL_12100138", "A.CA.EXP_EST.IND_T"),
        ),
        ("wrong tenant", InvalidInput, client.search_flows("ccei", "x", tenant="cith")),
    ]
    for label, error, call in checks:
        try:
            await call
            print(f"FAIL: {label} did not raise {error.__name__}")
            ok = False
        except error as exc:
            print(f"OK: {label} -> {error.__name__}: {str(exc)[:110]}")

    print("\nSTATCAN SDMX SPACES SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

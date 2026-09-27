"""Live smoke test for every module without its own smoke_test_<module>.py.

Calls each tool through the real server (in-process fastmcp.Client, via
the call_tool meta-tool), so registration, argument validation and the
client are all exercised against the live source. Later steps take
identifiers from earlier results (a CIHI slug, a DFO station code), so
the chain also checks that one tool's output feeds the next.

tests/test_live_coverage.py fails if a module has neither its own
script nor a step here, so a new module cannot ship without a live check.

Usage:
    uv run python scripts/smoke_test_modules.py            # every module
    uv run python scripts/smoke_test_modules.py cihi aer   # some modules
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastmcp import Client
from mcp.types import TextContent

from maplestats_mcp.server import mcp

Context = dict[str, Any]
Args = dict[str, Any] | Callable[[Context], dict[str, Any]]
Check = Callable[[Any], bool]


@dataclass(frozen=True)
class Step:
    module: str
    tool: str
    args: Args
    check: Check = lambda data: True


def _non_empty(key: str) -> Check:
    return lambda data: bool(data.get(key))


_TODAY = datetime.now(UTC).date()

STEPS: list[Step] = [
    # Alberta Economic Dashboard
    Step("ab_economic", "ab_economic_list_indicators", {}, _non_empty("indicators")),
    Step(
        "ab_economic",
        "ab_economic_get_indicator_series",
        lambda ctx: {"indicator": ctx["ab_economic_list_indicators"]["indicators"][0]["name"]},
    ),
    Step("ab_economic", "ab_economic_list_tables", {"query": "employment"}, _non_empty("tables")),
    Step(
        "ab_economic",
        "ab_economic_get_table_fields",
        lambda ctx: {"table": ctx["ab_economic_list_tables"]["tables"][0]["table"]},
    ),
    Step(
        "ab_economic",
        "ab_economic_get_data",
        lambda ctx: {"table": ctx["ab_economic_list_tables"]["tables"][0]["table"], "limit": 5},
    ),
    # Alberta Energy Regulator
    Step("aer", "aer_get_well_licences_daily", {}, _non_empty("raw_text")),
    Step("aer", "aer_get_well_licence_archive_link", {"year": _TODAY.year - 1}),
    Step("aer", "aer_get_production_volumes_link", {"product": "oil"}),
    # BC Geographic Warehouse
    Step("bcgw", "bcgw_get_active_wildfires", {"limit": 3}, _non_empty("wildfires")),
    Step("bcgw", "bcgw_get_mining_tenure", {"limit": 3}),
    Step(
        "bcgw",
        "bcgw_query_layer",
        {"type_name": "WHSE_LAND_AND_NATURAL_RESOURCE.PROT_CURRENT_FIRE_PNTS_SP", "limit": 2},
    ),
    # CanadaBuys
    Step("canadabuys", "canadabuys_search_tenders", {"limit": 3}, _non_empty("tenders")),
    Step("canadabuys", "canadabuys_search_awards", {"limit": 3}, _non_empty("awards")),
    Step("canadabuys", "canadabuys_search_contracts", {"limit": 3}, _non_empty("contracts")),
    Step(
        "canadabuys",
        "canadabuys_get_notice",
        lambda ctx: {
            "reference_number": ctx["canadabuys_search_tenders"]["tenders"][0]["reference_number"]
        },
    ),
    Step("canadabuys", "canadabuys_list_bulk_files", {}, _non_empty("files")),
    # Canada Energy Regulator
    Step("cer", "cer_list_datasets", {"query": "pipeline throughput"}, _non_empty("datasets")),
    Step(
        "cer",
        "cer_query_file",
        lambda ctx: {"url": ctx["cer_list_datasets"]["datasets"][0]["files"][0]["url"], "limit": 3},
    ),
    # CIHI
    Step("cihi", "cihi_search_indicators", {"query": "readmission"}, _non_empty("indicators")),
    Step(
        "cihi",
        "cihi_get_indicator",
        lambda ctx: {"indicator": ctx["cihi_search_indicators"]["indicators"][0]["slug"]},
    ),
    Step(
        "cihi",
        "cihi_get_indicator_data",
        lambda ctx: {
            "indicator": ctx["cihi_search_indicators"]["indicators"][0]["slug"],
            "place": "Alberta",
            "limit": 5,
        },
    ),
    # CRA digital economy platform operators
    Step(
        "cra_digital_economy_registry",
        "cra_digital_economy_registry_search",
        {"query": "Airbnb"},
        _non_empty("registrants"),
    ),
    # DFO tides and water levels
    Step("dfo_iwls", "dfo_iwls_search_stations", {"query": "Halifax"}, _non_empty("stations")),
    Step(
        "dfo_iwls",
        "dfo_iwls_get_station",
        lambda ctx: {"station_code": ctx["dfo_iwls_search_stations"]["stations"][0]["code"]},
    ),
    Step(
        "dfo_iwls",
        "dfo_iwls_get_water_levels",
        lambda ctx: {"station_code": ctx["dfo_iwls_search_stations"]["stations"][0]["code"]},
    ),
    # Earthquakes Canada
    Step("earthquakes", "earthquakes_search", {"min_magnitude": 2}, _non_empty("earthquakes")),
    Step(
        "earthquakes",
        "earthquakes_search",
        lambda ctx: {"event_id": ctx["earthquakes_search"]["earthquakes"][0]["event_id"]},
        lambda data: data["returned_count"] == 1,
    ),
    # Elections Canada financial returns
    Step(
        "elections_financial_returns",
        "elections_financial_returns_list_elections",
        {},
        _non_empty("elections"),
    ),
    Step(
        "elections_financial_returns",
        "elections_financial_returns_search_candidates",
        lambda ctx: {
            "election_id": ctx["elections_financial_returns_list_elections"]["elections"][0]["id"],
            "last_name": "Smith",
        },
    ),
    # Canada Gazette
    Step("gazette", "gazette_list_issues", {"limit": 2}, _non_empty("issues")),
    Step("gazette", "gazette_get_issue", {"part": 1}),
    Step(
        "gazette",
        "gazette_get_notice",
        lambda ctx: {"url": _first_notice_url(ctx["gazette_get_issue"])},
    ),
    # GC InfoBase
    Step("gc_infobase", "gc_infobase_list_files", {"query": "transfer"}, _non_empty("files")),
    Step(
        "gc_infobase",
        "gc_infobase_query",
        lambda ctx: {
            "resource_id": ctx["gc_infobase_list_files"]["files"][0]["resource_id"],
            "limit": 3,
        },
    ),
    # NRCan energy use
    Step("nrcan_energy_use", "nrcan_energy_use_list_products", {}, _non_empty("surveys")),
    Step(
        "nrcan_energy_use",
        "nrcan_energy_use_list_tables",
        lambda ctx: {"product": ctx["nrcan_energy_use_list_products"]["surveys"][0]["product"]},
    ),
    Step(
        "nrcan_energy_use",
        "nrcan_energy_use_get_table",
        lambda ctx: {"table_key": _first_table_key(ctx["nrcan_energy_use_list_tables"])},
    ),
    # NRCan geocoding and place names
    Step("nrcan_geo", "nrcan_geo_locate", {"query": "Ottawa"}, _non_empty("locations")),
    Step("nrcan_geo", "nrcan_geo_search_names", {"query": "Lake Louise", "province": "AB"}),
    # House of Commons (OpenParliament.ca)
    Step("openparliament", "parliament_search_bills", {"limit": 3}, _non_empty("bills")),
    Step(
        "openparliament",
        "parliament_get_bill",
        lambda ctx: {
            "session": ctx["parliament_search_bills"]["bills"][0]["session"],
            "number": ctx["parliament_search_bills"]["bills"][0]["number"],
        },
    ),
    Step("openparliament", "parliament_search_votes", {"limit": 3}, _non_empty("votes")),
    Step(
        "openparliament",
        "parliament_get_vote",
        lambda ctx: {
            "session": ctx["parliament_search_votes"]["votes"][0]["session"],
            "number": ctx["parliament_search_votes"]["votes"][0]["number"],
            "include_ballots": True,
        },
        _non_empty("ballots"),
    ),
    Step(
        "openparliament",
        "parliament_search_politicians",
        {"province": "PE"},
        _non_empty("politicians"),
    ),
    Step(
        "openparliament",
        "parliament_get_politician",
        lambda ctx: {"slug": ctx["parliament_search_politicians"]["politicians"][0]["slug"]},
    ),
    Step(
        "openparliament",
        "parliament_search_speeches",
        lambda ctx: {
            "politician": ctx["parliament_search_politicians"]["politicians"][0]["slug"],
            "limit": 3,
        },
    ),
    Step(
        "openparliament",
        "parliament_search_hansard",
        {"query": "pharmacare", "sort": "newest"},
        _non_empty("hits"),
    ),
    Step(
        "openparliament",
        "parliament_list_committees",
        {"keyword": "finance"},
        _non_empty("committees"),
    ),
    Step(
        "openparliament",
        "parliament_get_committee",
        lambda ctx: {"committee": ctx["parliament_list_committees"]["committees"][0]["slug"]},
        _non_empty("sessions"),
    ),
    Step(
        "openparliament",
        "parliament_search_committee_meetings",
        lambda ctx: {
            "committee": ctx["parliament_list_committees"]["committees"][0]["slug"],
            "in_camera": False,
            "date_to": _TODAY.isoformat(),
            "limit": 20,
        },
        _non_empty("meetings"),
    ),
    Step(
        "openparliament",
        "parliament_get_committee_meeting",
        lambda ctx: {
            **next(
                {"committee": m["committee"], "session": m["session"], "number": m["number"]}
                for m in ctx["parliament_search_committee_meetings"]["meetings"]
                if m["has_evidence"]
            ),
            "limit": 5,
            "lang": "fr",
        },
        _non_empty("speeches"),
    ),
    # Senate of Canada votes
    Step("senate", "senate_list_votes", {"limit": 3}, _non_empty("votes")),
    Step(
        "senate",
        "senate_get_vote",
        lambda ctx: {
            "vote_id": ctx["senate_list_votes"]["votes"][0]["vote_id"],
            "session": ctx["senate_list_votes"]["session"],
        },
        _non_empty("ballots"),
    ),
    Step("senate", "senate_list_votes", {"session": "44-1", "bill": "C-69", "lang": "fr"}),
    # Query planner (no network; checks registration through the server)
    Step(
        "planner",
        "plan_query",
        {"question": "How have rents and mortgage rates changed in Calgary?"},
        _non_empty("topics"),
    ),
    # StatCan PUMFs (range reads inside the ZIPs)
    Step("statcan", "statcan_pumf_search", {"query": "labour"}, _non_empty("products")),
    Step(
        "statcan", "statcan_pumf_list_files", {"catalogue_number": "98M0001X"}, _non_empty("files")
    ),
    Step(
        "statcan",
        "statcan_pumf_list_zip",
        lambda ctx: {"url": ctx["statcan_pumf_list_files"]["files"][0]["url"]},
        _non_empty("codebook_files"),
    ),
    Step(
        "statcan",
        "statcan_pumf_get_codebook",
        lambda ctx: {"url": ctx["statcan_pumf_list_files"]["files"][0]["url"], "query": "tenure"},
        _non_empty("weight_variables"),
    ),
    Step(
        "statcan",
        "statcan_pumf_tabulate",
        {
            "url": "https://www150.statcan.gc.ca/n1/pub/89m0025x/2022001/2024.zip",
            "rows": ["GENDER"],
        },
        _non_empty("cells"),
    ),
    # Census data tables 2006-2016
    Step(
        "statcan",
        "statcan_census_tables_search",
        {"query": "income household", "release": "2016"},
        _non_empty("tables"),
    ),
    Step(
        "statcan",
        "statcan_census_tables_get_downloads",
        lambda ctx: {"pid": ctx["statcan_census_tables_search"]["tables"][0]["pid"]},
        _non_empty("downloads"),
    ),
    Step("statcan", "statcan_census_tables_search", {"query": "language", "release": "2006"}),
    # Reproduction code (argument-based and provenance-based)
    Step(
        "reproduce",
        "reproduce_code",
        {"tool_name": "boc_get_observations", "arguments": {"series_names": ["FXUSDCAD"]}},
        _non_empty("scripts"),
    ),
    Step(
        "reproduce",
        "reproduce_code",
        {"tool_name": "cer_list_datasets", "arguments": {"query": "keystone"}, "language": "stata"},
        _non_empty("scripts"),
    ),
    # Recorded request: the station filter must reach the script.
    Step(
        "reproduce",
        "reproduce_code",
        {
            "tool_name": "eccc_query_items",
            "arguments": {
                "collection_id": "climate-daily",
                "filters": {"CLIMATE_IDENTIFIER": "3031093"},
                "limit": 5,
            },
            "language": "python",
        },
        lambda data: "CLIMATE_IDENTIFIER=3031093" in data["scripts"][0]["code"],
    ),
    # File filtered by the tool itself: the script repeats the filters.
    Step(
        "reproduce",
        "reproduce_code",
        {"tool_name": "canadabuys_search_awards", "arguments": {"query": "snow removal"}},
        lambda data: len(data["scripts"]) == 4 and "snow" in data["scripts"][1]["code"],
    ),
    # Transport Canada vehicle recalls
    Step(
        "tc_recalls",
        "tc_recalls_search",
        {"make": "Honda", "year_from": _TODAY.year - 3, "limit": 3},
        _non_empty("recalls"),
    ),
    Step(
        "tc_recalls",
        "tc_recalls_get",
        lambda ctx: {"recall_number": ctx["tc_recalls_search"]["recalls"][0]["recall_number"]},
    ),
]

COVERED_MODULES = frozenset(step.module for step in STEPS)


def _first_notice_url(issue: dict[str, Any]) -> str:
    for value in issue.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("url"):
                    return item["url"]
    raise KeyError("no notice url in gazette_get_issue result")


def _first_table_key(tables: dict[str, Any]) -> str:
    for value in tables.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("table_key"):
                    return item["table_key"]
    raise KeyError("no table_key in nrcan_energy_use_list_tables result")


def _text(result: Any) -> str:
    for block in result.content:
        if isinstance(block, TextContent):
            return block.text
    return ""


async def main(modules: set[str]) -> int:
    ctx: Context = {}
    failures: list[str] = []
    async with Client(mcp) as client:
        for step in STEPS:
            if modules and step.module not in modules:
                continue
            label = step.tool
            try:
                args = step.args(ctx) if callable(step.args) else step.args
            except (KeyError, IndexError, TypeError) as exc:
                failures.append(label)
                print(f"SKIP {label}: no input from an earlier step ({exc!r})")
                continue
            result = await client.call_tool(
                "call_tool", {"name": step.tool, "arguments": args}, raise_on_error=False
            )
            text = _text(result)
            if result.is_error:
                failures.append(label)
                print(f"FAIL {label} {args}: {text[:300]}")
                continue
            data = json.loads(text)
            ctx[step.tool] = data
            if not step.check(data):
                failures.append(label)
                print(f"FAIL {label} {args}: check failed on {text[:300]}")
                continue
            print(f"OK   {label} {args}")
    print()
    if failures:
        print(f"MODULES SMOKE TEST FAILED ({len(failures)}): {', '.join(failures)}")
        return 1
    print("MODULES SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(set(sys.argv[1:]))))

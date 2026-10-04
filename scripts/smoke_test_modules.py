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

# Modules whose upstream is down; remove an entry once the source responds.
DOWN_MODULES: dict[str, str] = {}

# Single tools whose upstream is down while the rest of their module works.
DOWN_TOOLS = {
    # oee.nrcan.gc.ca accepts the TCP connection and then resets the TLS
    # handshake (curl exit 35; httpx "All connection attempts failed"), checked
    # 2026-10-03. list_products still answers from the static survey list.
    "nrcan_energy_use_list_tables": "oee.nrcan.gc.ca resets the TLS handshake",
    "nrcan_energy_use_get_table": "oee.nrcan.gc.ca resets the TLS handshake",
}

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
    Step(
        "elections_financial_returns",
        "elections_financial_returns_get_financial_return_part",
        lambda ctx: {
            "candidate_client_id": ctx["elections_financial_returns_search_candidates"][
                "candidates"
            ][0]["client_id"],
            "part": "1",
            "election_id": ctx["elections_financial_returns_list_elections"]["elections"][0]["id"],
        },
    ),
    # Elections Canada official results (through the tools, not only the client)
    Step("elections_results", "elections_results_list_elections", {}, _non_empty("elections")),
    Step(
        "elections_results",
        "elections_results_get_table",
        {"election": 45, "table": "candidates", "province": "Alberta", "limit": 5},
        _non_empty("rows"),
    ),
    Step(
        "elections_results",
        "elections_results_get_historical",
        {"election": 40, "province": "Alberta", "limit": 5},
        _non_empty("ridings"),
    ),
    Step(
        "elections_results",
        "elections_results_get_historical_candidates",
        {"election": 30, "province": "Alberta", "winners_only": True, "limit": 5},
        _non_empty("candidates"),
    ),
    # Provincial election results (through the tools)
    Step(
        "elections_provincial",
        "elections_provincial_list_elections",
        {},
        _non_empty("elections"),
    ),
    Step(
        "elections_provincial",
        "elections_provincial_get_seats",
        {"province": "ab", "election": "2023"},
        _non_empty("parties"),
    ),
    Step(
        "elections_provincial",
        "elections_provincial_get_results",
        {"province": "qc", "election": "2022", "district": "gaspe", "winners_only": True},
        _non_empty("rows"),
    ),
    Step(
        "elections_provincial",
        "elections_provincial_get_voting_areas",
        {"district": "Fort Rouge", "election": "2023", "limit": 5},
        _non_empty("rows"),
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
    # House of Commons open data (through the tools)
    Step("ourcommons", "ourcommons_list_members", {"province": "Alberta"}, _non_empty("members")),
    Step(
        "ourcommons",
        "ourcommons_get_member_roles",
        lambda ctx: {"person_id": ctx["ourcommons_list_members"]["members"][0]["person_id"]},
        _non_empty("seats"),
    ),
    Step("ourcommons", "ourcommons_get_party_standings", {}, _non_empty("by_party")),
    Step("ourcommons", "ourcommons_get_ministry", {"lang": "fr"}, _non_empty("ministers")),
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
    # Open North Represent (elected officials and districts). Calls are paced to
    # 1 a second, so keep the postal codes and points to a spread across provinces.
    Step(
        "represent",
        "represent_lookup_postcode",
        {"postcode": "T5J0N3"},
        lambda d: bool(d["representatives"]) and bool(d["boundary_sets"]),
    ),
    Step(
        "represent",
        "represent_lookup_postcode",
        {"postcode": "H3B 4W8", "lang": "fr"},
        _non_empty("boundaries"),
    ),
    Step(
        "represent",
        "represent_lookup_postcode",
        {"postcode": "V6B1A1", "sets": "federal-electoral-districts", "include_set_details": False},
        _non_empty("boundaries"),
    ),
    Step(
        "represent",
        "represent_lookup_point",
        {"latitude": 45.524, "longitude": -73.596},
        lambda d: any(r["level"] == "federal" for r in d["representatives"]),
    ),
    Step(
        "represent",
        "represent_search_representatives",
        {"name": "Bendayan", "limit": 5},
        _non_empty("representatives"),
    ),
    Step(
        "represent",
        "represent_search_representatives",
        {"level": "provincial", "office": "MLA", "limit": 5},
        _non_empty("representatives"),
    ),
    Step(
        "represent",
        "represent_list_boundary_sets",
        {"domain": "Canada", "limit": 3},
        lambda d: all(s["licence_url"] for s in d["sets"]) and bool(d["sets"]),
    ),
    Step(
        "represent",
        "represent_list_representative_sets",
        {"level": "federal"},
        _non_empty("sets"),
    ),
    # Query planner (no network; checks registration through the server)
    Step(
        "planner",
        "plan_query",
        {"question": "How have rents and mortgage rates changed in Calgary?"},
        _non_empty("topics"),
    ),
    # StatCan SDMX. 14100063's structure document is empty upstream (HTTP 200,
    # zero bytes), so its steps also prove the WDS fallback; the data steps
    # prove the newest observations come back by default.
    Step(
        "statcan/sdmx",
        "sdmx_get_structure",
        {"product_id": 14100063},
        lambda data: len(data["dimensions"]) == 6,
    ),
    Step(
        "statcan/sdmx",
        "sdmx_get_structure",
        {"product_id": 98100002, "dimension_position": 1, "limit": 5},
        lambda data: (
            len(data["dimensions"][0]["codes"]) == 5
            and "paged" in (data["provenance"]["limits"] or "")
        ),
    ),
    Step(
        "statcan/sdmx",
        "sdmx_get_key_for_dimension",
        {"product_id": 14100063, "dimension_position": 4},
        _non_empty("or_key"),
    ),
    Step(
        "statcan/sdmx",
        "sdmx_get_data",
        {"product_id": 18100004, "key": "2.2"},
        lambda data: data["series"][0]["observations"][-1]["period"] >= "2026",
    ),
    Step(
        "statcan/sdmx",
        "sdmx_get_vector_data",
        {"vector_id": 41690973, "last_n_observations": 3},
        lambda data: data["row_count"] == 3,
    ),
    # StatCan RDaaS
    Step(
        "statcan/rdaas", "rdaas_search_classifications", {"query": "NAICS"}, _non_empty("results")
    ),
    Step(
        "statcan/rdaas",
        "rdaas_search_classifications",
        {"query": "NAICS", "status": ["RELEASED"], "limit": 3},
        lambda data: all(r["status"] == "RELEASED" for r in data["results"]),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_search_filters",
        {"kind": "classification"},
        _non_empty("filters"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_search_filters",
        {"kind": "concordance"},
        _non_empty("filters"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_classification",
        lambda ctx: {"classification_id": ctx["rdaas_search_classifications"]["results"][0]["id"]},
        _non_empty("levels"),
    ),
    # NAICS 2017.3.0 (the current NAICS 2022 has no detailed categories upstream).
    Step(
        "statcan/rdaas",
        "rdaas_get_classification_categories_detailed",
        {"classification_id": "S049Pjk4RIUgw6j2", "limit": 5},
        lambda data: len(data["categories"]) == 5 and data["total_count"] > 5,
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_classification_exclusions",
        {"classification_id": "P1PiDASifm2o9oHQ"},
        _non_empty("exclusions"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_term_exclusion",
        lambda ctx: {
            "term_exclusion_id": ctx["rdaas_get_classification_exclusions"]["exclusions"][0]["id"]
        },
        _non_empty("term"),
    ),
    # NAICS 2022's index is 8 MB: the paged call must stay small.
    Step(
        "statcan/rdaas",
        "rdaas_get_classification_indexes",
        {"classification_id": "MJRdRiFsfmJAprtT", "query": "bakery", "limit": 5},
        lambda data: 0 < len(data["entries"]) <= 5 and data["total_count"] >= len(data["entries"]),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_classification_index_entry",
        lambda ctx: {
            "classification_id": "MJRdRiFsfmJAprtT",
            "index_id": ctx["rdaas_get_classification_indexes"]["entries"][0]["index_id"],
        },
        _non_empty("primary_term"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_search_concordances",
        {"query": "NAICS", "limit": 3},
        _non_empty("results"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_concordance",
        lambda ctx: {"concordance_id": ctx["rdaas_search_concordances"]["results"][0]["id"]},
        _non_empty("source_id"),
    ),
    Step(
        "statcan/rdaas",
        "rdaas_get_concordance_maps",
        lambda ctx: {"concordance_id": ctx["rdaas_search_concordances"]["results"][0]["id"]},
        _non_empty("maps"),
    ),
    # StatCan PUMFs (range reads inside the ZIPs)
    Step("statcan/pumf", "statcan_pumf_search", {"query": "labour"}, _non_empty("products")),
    Step(
        "statcan/pumf",
        "statcan_pumf_list_files",
        {"catalogue_number": "98M0001X"},
        _non_empty("files"),
    ),
    Step(
        "statcan/pumf",
        "statcan_pumf_list_zip",
        lambda ctx: {"url": ctx["statcan_pumf_list_files"]["files"][0]["url"]},
        _non_empty("codebook_files"),
    ),
    Step(
        "statcan/pumf",
        "statcan_pumf_get_codebook",
        lambda ctx: {"url": ctx["statcan_pumf_list_files"]["files"][0]["url"], "query": "tenure"},
        _non_empty("weight_variables"),
    ),
    Step(
        "statcan/pumf",
        "statcan_pumf_tabulate",
        {
            "url": "https://www150.statcan.gc.ca/n1/pub/89m0025x/2022001/2024.zip",
            "rows": ["GENDER"],
        },
        _non_empty("cells"),
    ),
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
        {
            "tool_name": "ircc_list_express_entry_rounds",
            "arguments": {"program": "Canadian Experience Class"},
        },
        lambda data: "experience" in data["scripts"][1]["code"].lower(),
    ),
    # Excel: a Power Query reading the key's series, and a formatted workbook.
    Step(
        "reproduce",
        "reproduce_code",
        {
            "tool_name": "sdmx_get_data",
            "arguments": {"product_id": 18100004, "key": "2.2", "last_n_observations": 3},
            "language": "excel",
        },
        lambda data: "Xml.Document" in data["scripts"][0]["code"],
    ),
    Step(
        "reproduce",
        "reproduce_workbook",
        {
            "tool_name": "boc_get_observations",
            "arguments": {"series_names": ["FXUSDCAD"], "recent": 5},
            "delivery": "base64",
        },
        lambda data: bool(data["workbook_base64"]) and "Source" in data["sheets"],
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
            if step.module in DOWN_MODULES or step.tool in DOWN_TOOLS:
                reason = DOWN_MODULES.get(step.module) or DOWN_TOOLS[step.tool]
                print(f"SKIP {step.tool}: {reason}")
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

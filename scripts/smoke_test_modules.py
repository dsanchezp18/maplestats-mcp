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
from datetime import UTC, datetime, timedelta
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
    # When set, the step passes only if the call is an error whose text
    # contains this string (a bad input that must be refused, not answered).
    expect_error: str | None = None


def _non_empty(key: str) -> Check:
    return lambda data: bool(data.get(key))


_TODAY = datetime.now(UTC).date()

# Modules whose upstream is down; remove an entry once the source responds.
DOWN_MODULES: dict[str, str] = {}

# Single tools whose upstream is down while the rest of their module works.
# oee.nrcan.gc.ca times out at TCP connect on port 443 (2026-10-03; it failed
# the TLS handshake on 2026-09-29). nrcan_energy_use_list_products still
# answers from its fixed survey list, so it keeps its step.
_OEE_DOWN = "oee.nrcan.gc.ca does not accept a TCP connection"
DOWN_TOOLS: dict[str, str] = {
    "nrcan_energy_use_list_tables": _OEE_DOWN,
    "nrcan_energy_use_get_table": _OEE_DOWN,
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
    # The default (yesterday) is the latest posted list, so it carries no stale note.
    Step(
        "aer",
        "aer_get_well_licences_daily",
        {},
        lambda data: bool(data["raw_text"]) and data["note"] is None,
    ),
    # Sizes come back only when the HEAD asks for identity encoding.
    Step(
        "aer",
        "aer_get_well_licence_archive_link",
        {"year": _TODAY.year - 1},
        lambda data: data["exists"] and (data["size_bytes"] or 0) > 0,
    ),
    Step("aer", "aer_get_well_licence_archive_link", {"year": 1850}, expect_error="2017"),
    Step(
        "aer",
        "aer_get_production_volumes_link",
        {"product": "oil"},
        lambda data: data["exists"] and (data["size_bytes"] or 0) > 0,
    ),
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
    # A year-only end covers the whole year: Keystone has monthly rows for
    # several key points, so 2024 alone gives more than the January rows.
    Step(
        "cer",
        "cer_query_file",
        {
            "url": "https://www.cer-rec.gc.ca/open/energy/throughput-capacity/"
            "keystone-throughput-and-capacity.csv",
            "start": "2024",
            "end": "2024",
            "columns": ["Date"],
            "limit": 1000,
        },
        lambda data: {r["Date"][:7] for r in data["rows"]} >= {"2024-01", "2024-12"},
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
    # One whole day by date (start = end used to be refused), and a week of
    # predictions at the hourly default rather than one-minute points.
    Step(
        "dfo_iwls",
        "dfo_iwls_get_water_levels",
        {
            "station_code": "07120",
            "series_code": "wlp",
            "start": _TODAY.isoformat(),
            "end": _TODAY.isoformat(),
        },
        lambda data: len(data["points"]) >= 20,
    ),
    Step(
        "dfo_iwls",
        "dfo_iwls_get_water_levels",
        {
            "station_code": "07120",
            "series_code": "wlp",
            "start": _TODAY.isoformat(),
            "end": (_TODAY + timedelta(days=6)).isoformat(),
        },
        lambda data: data["resolution"] == "SIXTY_MINUTES" and len(data["points"]) <= 7 * 24 + 1,
    ),
    # Electricity (the rest is in smoke_test_electricity.py): the latest Quebec
    # trade hour must carry published exports, not a zero placeholder.
    Step(
        "electricity",
        "electricity_quebec_get_trade",
        {"limit": 3},
        lambda data: len(data["points"]) == 3 and bool(data["points"][-1]["exports_total_mw"]),
    ),
    # CWFIS (the rest is in smoke_test_cwfis.py): an FRP sort keeps detections
    # without FRP (2023 archive rows have none), geometry stays within budget.
    Step(
        "cwfis",
        "cwfis_get_hotspots",
        {
            "agency": "BC",
            "start_date": "2023-08-18",
            "end_date": "2023-08-18",
            "sort_by": "frp",
            "limit": 2,
        },
        lambda data: data["total_matched"] > 1000 and data["returned_count"] == 2,
    ),
    Step("cwfis", "cwfis_get_hotspots", {"agency": "ZZ"}, expect_error="agency"),
    Step(
        "cwfis",
        "cwfis_get_fire_perimeters",
        {"include_geometry": True, "limit": 20},
        lambda data: len(json.dumps(data)) < 600_000,
    ),
    Step(
        "cwfis",
        "cwfis_get_weather_stations",
        {"name": "NO SUCH STATION ZZ"},
        lambda data: not data["stations"] and "layer currently holds" in (data["note"] or ""),
    ),
    # NBAC (the rest is in smoke_test_nrcan_nbac.py): the five largest 2023 BC
    # fires with polygons were 32.9 MB before the geometry budget.
    Step(
        "nrcan_nbac",
        "nrcan_nbac_query_fires",
        {
            "cql_filter": "admin_area = 'BC' AND year = 2023",
            "include_geometry": True,
            "sort_by": "adj_ha D",
            "limit": 5,
        },
        lambda data: len(json.dumps(data)) < 3_000_000 and len(data["fires"]) == 5,
    ),
    Step(
        "nrcan_nbac",
        "nrcan_nbac_query_fires",
        {"cql_filter": "year = 2999"},
        lambda data: not data["fires"] and (data["latest_year"] or 0) >= 2024,
    ),
    # NFD (the rest is in smoke_test_nfd.py): a one-province group keeps its name.
    Step(
        "nfd",
        "nfd_query_table",
        {"table_id": "3.2.1", "province": "BC", "group_by": ["year"], "limit": 3},
        lambda data: bool(data["rows"]) and all(r["iso"] == "BC" for r in data["rows"]),
    ),
    # Alberta wildfire (the rest is in smoke_test_ab_wildfire.py): every
    # timestamp is UTC, the status date included.
    Step(
        "ab_wildfire",
        "ab_wildfire_get_fires",
        {"limit": 3},
        lambda data: (
            bool(data["fires"])
            and all(
                f["status_changed"] is None or f["status_changed"].endswith(("Z", "+00:00"))
                for f in data["fires"]
            )
        ),
    ),
    # ECCC GeoMet (the rest is in smoke_test_eccc.py): French search text,
    # a local datetime check, and a byte budget on heavy swob rows.
    Step(
        "eccc",
        "eccc_search_collections",
        {"query": "alerte", "lang": "fr"},
        lambda data: any(c["id"] == "weather-alerts" for c in data["collections"]),
    ),
    Step(
        "eccc",
        "eccc_query_items",
        {"collection_id": "hydrometric-realtime", "datetime_filter": "notadate"},
        expect_error="RFC 3339",
    ),
    Step(
        "eccc",
        "eccc_query_items",
        {"collection_id": "swob-realtime", "limit": 1000},
        lambda data: len(json.dumps(data)) < 1_500_000 and bool(data["items"]),
    ),
    # IRCC Express Entry (the rest is in smoke_test_ircc.py): French text is
    # decoded right, through the tool, and a non-numeric draw is refused.
    Step(
        "ircc",
        "ircc_get_latest_express_entry_round",
        {"lang": "fr"},
        lambda data: (
            "Ã" not in json.dumps(data, ensure_ascii=False)
            and "é" in json.dumps(data["round"], ensure_ascii=False)
        ),
    ),
    Step(
        "ircc", "ircc_get_express_entry_round", {"draw_number": "abc"}, expect_error="draw_number"
    ),
    # CMHC HMIP (the rest is in smoke_test_cmhc.py): an unknown province id is
    # refused instead of answered with the national categories.
    Step(
        "cmhc",
        "cmhc_list_categories",
        {"geography_type": "Province", "geography_id": "999"},
        expect_error="No province with id",
    ),
    # Earthquakes Canada
    Step("earthquakes", "earthquakes_search", {"min_magnitude": 2}, _non_empty("earthquakes")),
    Step(
        "earthquakes",
        "earthquakes_search",
        lambda ctx: {"event_id": ctx["earthquakes_search"]["earthquakes"][0]["event_id"]},
        lambda data: data["returned_count"] == 1,
    ),
    # Five years at limit 2: only limit + 1 rows travel (it was all 34,973).
    Step(
        "earthquakes",
        "earthquakes_search",
        {"start": "2021-01-01", "end": "2025-12-31", "limit": 2},
        lambda data: data["returned_count"] == 2 and data["has_more"],
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
    # Paging past the first 300 of an unfiltered general-election search.
    Step(
        "elections_financial_returns",
        "elections_financial_returns_search_candidates",
        {"election_id": "62", "offset": 300, "limit": 50},
        lambda data: data["returned_count"] == 50 and data["has_more"],
    ),
    # Accented names decode (they came back as U+FFFD before 2026-10-03).
    Step(
        "elections_financial_returns",
        "elections_financial_returns_get_financial_return_part",
        {"candidate_client_id": "56572", "part": "3A", "election_id": "62"},
        lambda data: (
            "�" not in json.dumps(data, ensure_ascii=False)
            and "é" in json.dumps(data["sections"], ensure_ascii=False)
        ),
    ),
    Step(
        "elections_financial_returns",
        "elections_financial_returns_get_financial_return_part",
        {"candidate_client_id": "56572", "part": "1", "election_id": "62", "lang": "fr"},
        lambda data: bool(data["export_header"]) and bool(data["sections"]),
    ),
    # A candidate under an election they did not run in, and an unknown election.
    Step(
        "elections_financial_returns",
        "elections_financial_returns_get_financial_return_part",
        {"candidate_client_id": "56572", "part": "1", "election_id": "53"},
        expect_error="did not run",
    ),
    Step(
        "elections_financial_returns",
        "elections_financial_returns_search_candidates",
        {"election_id": "9999"},
        expect_error="no election",
    ),
    # Canada Gazette
    Step("gazette", "gazette_list_issues", {"limit": 2}, _non_empty("issues")),
    # Part II's feed leads with non-issue items (the Consolidated Index); the
    # default must open a real issue, never the site's not-found page.
    Step(
        "gazette",
        "gazette_get_issue",
        {"part": 2},
        lambda data: (
            bool(data["notices"])
            and not any("404" in (n.get("section") or "") for n in data["notices"])
        ),
    ),
    Step(
        "gazette",
        "gazette_get_issue",
        {"part": 1, "issue_date": "2026-09-24"},
        expect_error="nothing published",
    ),
    Step(
        "gazette",
        "gazette_get_notice",
        {"url": "https://gazette.gc.ca/rp-pr/p1/2026/2026-10-03/html/zzz-eng.html"},
        expect_error="nothing published",
    ),
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
    # A float radius was a 404 upstream until 2026-10-03.
    Step(
        "nrcan_geo",
        "nrcan_geo_search_names",
        {"latitude": 51.05, "longitude": -114.07, "radius_km": 5.0, "limit": 3},
        _non_empty("names"),
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
    # The French list says "Abstention" in the singular; every vote has a count.
    Step(
        "senate",
        "senate_list_votes",
        {"lang": "fr", "limit": 5, "keyword": "troisieme"},
        lambda data: (
            bool(data["votes"]) and all(v["abstentions"] is not None for v in data["votes"])
        ),
    ),
    Step("senate", "senate_list_votes", {"session": "41-2"}, expect_error="42-1"),
    Step(
        "senate",
        "senate_get_vote",
        lambda ctx: {"vote_id": ctx["senate_list_votes"]["votes"][0]["vote_id"], "session": "44-1"},
        expect_error="not in session",
    ),
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
            if step.expect_error is not None:
                if result.is_error and step.expect_error in text:
                    print(f"OK   {label} {args} (refused as expected)")
                else:
                    failures.append(label)
                    print(f"FAIL {label} {args}: expected an error with {step.expect_error!r}")
                continue
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

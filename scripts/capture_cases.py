"""Record the case-study calls the website shows (site/_data/cases/*.json).

Each case is one or more real calls made through the server's own
call_tool, with the response and the R, Python, Stata and Julia scripts
reproduce_code writes for the first call. The website build reads these
files and never calls an upstream itself, so every chart is dated and
stays as recorded until this script is run again.

The PUMF case downloads the 2021 Census individuals file (about 170 MB) on
its first call, so it takes a few minutes.

Usage:
    uv run python scripts/capture_cases.py            # every case
    uv run python scripts/capture_cases.py boc ircc   # some cases
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

from maplestats_mcp.modules.reproduce import client as reproduce
from maplestats_mcp.server import mcp

OUT = Path(__file__).resolve().parent.parent / "site" / "_data" / "cases"

CENSUS_2021_PUMF = (
    "https://www150.statcan.gc.ca/n1/pub/98m0001x/2023001/cen21_ind_98m0001x_part_rec21.zip"
)

CASES: dict[str, list[dict[str, Any]]] = {
    # Statisticians: a weighted share from Census microdata, with standard
    # errors from the file's 16 replicate weights. Ages 25 to 64; only valid
    # education codes, so "not available" and "not applicable" are not counted.
    "pumf": [
        {
            "name": "statcan_pumf_tabulate",
            "arguments": {
                "url": CENSUS_2021_PUMF,
                "rows": ["PR", "HDGREE"],
                "statistic": "share",
                "filters": {
                    "AGEGRP": [str(code) for code in range(9, 17)],
                    "HDGREE": [str(code) for code in range(1, 14)],
                },
            },
        },
    ],
    # Demographers: new permanent residents by intended destination.
    "ircc": [
        {
            "name": "ircc_monthly_query",
            "arguments": {
                "table_id": "ODP-PR-PT_CMA",
                "filters": {"census_metropolitan_area": city},
                "period": "year",
                "year_from": 2015,
            },
        }
        for city in ("Edmonton", "Calgary")
    ],
    # Urban planners: housing starts by dwelling type, Canada, every month
    # since 1990 (CMHC table 5.6.1, centres of 10,000 people or more). The
    # second call counts CMHC's data categories for the verse.
    "housing": [
        {
            "name": "cmhc_get_table_data",
            "arguments": {
                "category_level_1": "New Housing Construction",
                "category_level_2": "Starts (Actual)",
                "column_field": "1",
                "row_field": "TIMESERIES",
            },
        },
        {"name": "cmhc_list_categories", "arguments": {}},
    ],
    # Microeconomists: the low-income rate (LIM-AT) by immigrant generation,
    # from the same Census microdata with replicate-weight standard errors.
    # Only valid codes, so "not available" is not counted as either outcome.
    "micro": [
        {
            "name": "statcan_pumf_tabulate",
            "arguments": {
                "url": CENSUS_2021_PUMF,
                "rows": ["GENSTAT", "LOLIMA"],
                "statistic": "share",
                "filters": {"GENSTAT": ["1", "2", "3", "4"], "LOLIMA": ["1", "2"]},
            },
        },
    ],
    # Marketers: every credit card offered in Alberta, with its annual fee,
    # purchase rate and rewards (FCAC's Credit Card Comparison Tool).
    "cards": [
        {
            "name": "fcac_search_credit_cards",
            "arguments": {"province": "AB", "limit": 100},
        },
    ],
    # The Statistics Canada page (site/statcan.html): the Consumer Price
    # Index, all-items, not seasonally adjusted (table 18-10-0004, vector
    # 41690973), with the scripts reproduce_code writes for it.
    "macro": [
        {
            "name": "wds_get_data_from_vectors",
            "arguments": {"vector_ids": [41690973], "latest_n": 84},
        },
    ],
    # Macroeconomists: the yield curve, the gap between the 10-year and
    # 2-year Government of Canada benchmark bond yields, every business day
    # since 2001 (Bank of Canada Valet).
    "curve": [
        {
            "name": "boc_get_observations",
            "arguments": {
                "series_names": ["BD.CDN.2YR.DQ.YLD", "BD.CDN.10YR.DQ.YLD"],
                "start_date": "2001-01-01",
            },
        },
    ],
    # Scientists: Canadian patent applications in IPC class G06N (computing
    # based on biological models, which is where machine learning is
    # classed), by filing year. The first call counts every patent with a
    # filing date; the rest count G06N one year at a time.
    "patents": [
        {
            "name": "ised_ip_horizons_search_patents",
            "arguments": {"filed_from": "1800-01-01", "limit": 1},
        },
        *(
            {
                "name": "ised_ip_horizons_search_patents",
                "arguments": {
                    "ipc": "G06N",
                    "filed_from": f"{year}-01-01",
                    "filed_to": f"{year}-12-31",
                    "limit": 1,
                },
            }
            for year in range(2005, 2024)
        ),
    ],
    # Analysts: the Bank of Canada's target for the overnight rate.
    "boc": [
        {
            "name": "boc_get_observations",
            "arguments": {"series_names": ["V39079"], "start_date": "2015-01-01"},
        },
    ],
    # The Statistics Canada page walks one series from search to SDMX: find
    # the CPI table, read its dimensions, turn coordinate 2.2 (Canada,
    # all-items) into its vector, then ask SDMX for the same series. The
    # WDS data call itself is the macro case above.
    "statcan": [
        {"name": "wds_search_cubes", "arguments": {"query": "consumer price index", "limit": 5}},
        {"name": "wds_get_cube_metadata", "arguments": {"product_id": 18100004}},
        {
            "name": "wds_get_series_info_from_cube_pid_coord",
            "arguments": {"product_id": 18100004, "coordinate": "2.2"},
        },
        {
            "name": "sdmx_get_vector_data",
            "arguments": {"vector_id": 41690973, "last_n_observations": 3},
        },
    ],
    # The counts in the verse: how much each audience can reach.
    "counts": [
        # every page of the Data catalogue's microdata results, counted by product
        {
            "name": "statcan_reference_search_data",
            "arguments": {"query": "public use microdata", "count": 100},
            "all_pages": True,
        },
        {"name": "ircc_monthly_list_tables", "arguments": {}},
        {"name": "wds_list_all_cubes", "arguments": {"lite": True}},
        {"name": "boc_list_series", "arguments": {}},
    ],
}


async def _call(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    result = await client.call_tool("call_tool", {"name": name, "arguments": arguments})
    data = result.structured_content or {}
    return data.get("result", data)


def _trim(name: str, response: Any) -> Any:
    """Keep what the page uses and the provenance; drop bulky lists it does not."""
    if name in ("wds_list_all_cubes", "boc_list_series"):
        return {"total_count": response["total_count"], "provenance": response["provenance"]}
    if name == "ircc_monthly_list_tables":
        return {
            "returned_count": response["returned_count"],
            "total_tables": response["total_tables"],
            "provenance": response["provenance"],
        }
    if name == "cmhc_list_categories":
        return {"total_count": response["total_count"], "provenance": response["provenance"]}
    if name == "ised_ip_horizons_search_patents":
        return {"total_matched": response["total_matched"], "provenance": response["provenance"]}
    if name == "statcan_pumf_list_files":
        return {"file_count": len(response["files"]), "provenance": response["provenance"]}
    if name == "wds_get_cube_metadata":
        # About 185 kB in full, mostly member names and footnote text: keep
        # each dimension's first members and counts.
        dimensions = [
            {
                **{k: v for k, v in dim.items() if k != "members"},
                "member_count": len(dim["members"]),
                "members": dim["members"][:5],
            }
            for dim in response["dimensions"]
        ]
        kept = {k: v for k, v in response.items() if k not in ("dimensions", "footnotes")}
        return {**kept, "footnote_count": len(response["footnotes"]), "dimensions": dimensions}
    return response


async def _microdata_products(client: Client, name: str, arguments: dict[str, Any]) -> Any:
    """Page through the Data catalogue and count distinct microdata products."""
    products: dict[str, str] = {}
    first: dict[str, Any] = {}
    page = 0
    while True:
        response = await _call(client, name, {**arguments, "page": page})
        first = first or response
        documents = response["documents"]
        for doc in documents:
            if "microd" in (doc.get("category") or "").lower() and doc.get("catalogue_number"):
                products[doc["catalogue_number"]] = doc["title"]
        if len(documents) < arguments["count"]:
            break
        page += 1
    return {"product_count": len(products), "pages": page + 1, "provenance": first["provenance"]}


async def _record(client: Client, call: dict[str, Any], with_scripts: bool) -> dict[str, Any]:
    name, arguments = call["name"], call["arguments"]
    if call.get("all_pages"):
        response = await _microdata_products(client, name, arguments)
    else:
        response = _trim(name, await _call(client, name, arguments))
    record: dict[str, Any] = {"name": name, "arguments": arguments, "response": response}
    if with_scripts:
        code = await reproduce.reproduce(name, arguments, "all")
        record["scripts"] = {s.language: s.code for s in code.scripts}
        record["script_notes"] = list(code.notes)
    return record


async def capture(key: str) -> Path:
    async with Client(mcp) as client:
        calls = [
            await _record(client, call, with_scripts=(n == 0 and key != "counts"))
            for n, call in enumerate(CASES[key])
        ]
    record = {"captured": datetime.now(UTC).date().isoformat(), "calls": calls}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{key}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return path


async def main(keys: list[str]) -> None:
    for key in keys:
        print(f"captured {await capture(key)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("cases", nargs="*", choices=list(CASES), help="default: every case")
    args = parser.parse_args()
    asyncio.run(main(args.cases or list(CASES)))

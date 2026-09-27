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
    # Economists: the monthly unemployment rate, Canada, seasonally adjusted
    # (Labour Force Survey, table 14-10-0287, vector v2062815).
    "labour": [
        {
            "name": "wds_get_data_from_vectors",
            "arguments": {"vector_ids": [2062815], "latest_n": 60},
        },
    ],
    # Analysts: the Bank of Canada's target for the overnight rate.
    "boc": [
        {
            "name": "boc_get_observations",
            "arguments": {"series_names": ["V39079"], "start_date": "2015-01-01"},
        },
    ],
    # The counts in the verse: how much each audience can reach.
    "counts": [
        {"name": "statcan_pumf_list_files", "arguments": {"catalogue_number": "98M0001X"}},
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
    if name == "statcan_pumf_list_files":
        return {"file_count": len(response["files"]), "provenance": response["provenance"]}
    return response


async def _record(client: Client, call: dict[str, Any], with_scripts: bool) -> dict[str, Any]:
    name, arguments = call["name"], call["arguments"]
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

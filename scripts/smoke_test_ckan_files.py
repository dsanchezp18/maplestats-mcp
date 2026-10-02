"""Live smoke test for ckan_describe_resource / ckan_read_resource on every portal.

Each portal is read one resource after another (its pacing: 1 request per
crawl-delay for the API calls, so the federal portal takes minutes), and the
portals run side by side. Resources and expectations were checked by hand on
2026-10-02:

- federal: CRA individual tax statistics by FSA (CSV, 1,679 rows), an ECCC
  French CSV in Windows-1252, the ISED insolvency workbook (four comparable
  sheets), a DFO "CSV" that is a zip and a 55 MB workbook (both refused);
- on: a 10 MB legacy .xls, a ministry-terms-of-use workbook (licence warning),
  an ".xls" that is a web page, a file on a host off the list;
- bc: a legacy .xls, an Access Only (licence 22) workbook and a "csv"-labelled
  .xlsx;
- nt: a snow survey workbook and the 2024 traffic workbook, whose declared
  65,536 x 16,217 sheet once took 250 s to read;
- yt (53 MB CSV refused), regina, montreal (85-sheet budget), qc (a
  Montreal library workbook, really .xls), toronto (CSV and the robots.txt
  override note) and ab.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

from maplestats_mcp.modules.ckan import files
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

failures: list[str] = []


def check(ok: bool, label: str) -> None:
    print(("OK: " if ok else "FAIL: ") + label)
    if not ok:
        failures.append(label)


async def expect_error(
    label: str, error: type[Exception], coro: Awaitable[object], needle: str
) -> None:
    try:
        await coro
    except error as exc:
        check(needle in str(exc), f"{label} -> {type(exc).__name__}: {str(exc)[:110]}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{label} raised {type(exc).__name__}: {str(exc)[:160]}")
    else:
        check(False, f"{label} did not raise")


async def federal() -> None:
    datastore = await files.read_resource(
        "federal", "3eb35dcd-9b0c-4ae9-a45c-e5e481567c23", limit=1
    )
    check(
        datastore.read_via == "datastore" and datastore.total_rows > 1000,
        f"federal DataStore-active resource -> read_via {datastore.read_via}",
    )
    rows = await files.read_resource("federal", "915fa192-d4df-4e97-81c0-482c025dec2d", limit=2)
    check(
        rows.format == "csv" and rows.total_rows > 1000 and rows.rows[0]["FSA"] == "A0A",
        f"federal CRA FSA table 1a -> {rows.total_rows} rows, first {rows.rows[0]['FSA']}",
    )
    check(
        rows.source.licence_status == "open" and rows.source.organization is not None,
        f"federal licence {rows.source.licence_id}, organization {rows.source.organization}",
    )
    french = await files.read_resource("federal", "161f8426-fcd8-4bf7-aed7-7a07e15b146e", limit=1)
    check(
        "Année" in french.all_columns and french.header_row == 3,
        f"federal ECCC French CSV (Windows-1252) -> {french.all_columns[:2]}",
    )
    insolvency = "e53c9ba1-a734-4f22-bc3d-f489921d2959"
    listing = await files.read_resource("federal", insolvency)
    check(
        listing.sheet_chosen_by == "none" and len(listing.sheets) == 4 and not listing.rows,
        f"federal ISED insolvency workbook -> sheet list {[s.name for s in listing.sheets]}",
    )
    monthly = await files.read_resource(
        "federal", insolvency, sheet=listing.sheets[0].name, limit=2
    )
    check(bool(monthly.rows), f"federal insolvency sheet {monthly.sheet!r} -> rows")
    await expect_error(
        "federal DFO 'CSV' that is a zip",
        InvalidInput,
        files.read_resource("federal", "045f7050-d608-3580-b55b-546c82350190"),
        ".zip",
    )
    await expect_error(
        "federal DFO 55 MB workbook",
        UpstreamError,
        files.read_resource("federal", "561cc38e-4ee3-37a3-9054-f79c6580a401"),
        "stops at",
    )


async def on() -> None:
    datastore = await files.read_resource("on", "ea9dc29c-b4f1-4426-b1f2-974ce995aca1", limit=1)
    check(
        datastore.read_via == "datastore", f"on DataStore-active resource -> {datastore.total_rows}"
    )
    started = time.monotonic()
    legacy = await files.read_resource("on", "8f707fda-3dca-4134-a3a7-b3cd4a80987d", limit=2)
    check(
        legacy.format == "xls" and legacy.total_rows > 40000,
        f"on MISA 2004 legacy .xls -> {legacy.total_rows} rows in {time.monotonic() - started:.0f} s",
    )
    tourism = await files.read_resource("on", "9ecd0009-a656-4709-8f0f-eb7581afb370", limit=1)
    check(
        tourism.source.licence_status == "restricted" and bool(tourism.source.licence_warning),
        f"on ministry terms of use -> {tourism.source.licence_id}, warning set",
    )
    await expect_error(
        "on '.xls' that is a web page",
        UpstreamError,
        files.read_resource("on", "43aa4b94-8040-459a-a219-d4e9949390c0"),
        "web page",
    )
    await expect_error(
        "on file off the host list",
        InvalidInput,
        files.read_resource("on", "802fabd4-7d53-4711-9d92-b0878ccebd3e"),
        "not on this portal's list",
    )


async def bc() -> None:
    xls = await files.read_resource("bc", "82823ecf-2cd2-46d6-922b-4d416b3aed3b", limit=2)
    check(
        xls.format == "xls" and xls.source.licence_status == "open" and xls.total_rows > 0,
        f"bc interest-rate .xls -> {xls.total_rows} rows, licence {xls.source.licence_id}",
    )
    access = await files.read_resource("bc", "b9c84f29-54e0-4dd7-a4a4-f9f1ffe8f61d", limit=1)
    check(
        access.source.licence_status == "restricted"
        and "Access Only" in (access.source.licence_warning or ""),
        "bc Access Only (22) -> restricted warning",
    )
    mislabelled = await files.read_resource("bc", "75097ce7-8ac5-42f2-ac2e-2a355a7cc3da", limit=1)
    check(mislabelled.format in ("xlsx", "csv"), f"bc csv-labelled file -> {mislabelled.format}")


async def nt() -> None:
    snow = await files.read_resource("nt", "5cb8c0b9-c76c-4d0c-8d13-627fc3615362", limit=2)
    check(snow.format == "xlsx" and snow.total_rows > 50, f"nt snow survey -> {snow.total_rows}")
    started = time.monotonic()
    traffic = await files.read_resource(
        "nt", "ba378c1c-517a-428f-88c2-49bb28d96f7e", sheet="Daily Traffic Summary", limit=2
    )
    seconds = time.monotonic() - started
    check(
        traffic.total_rows > 300 and seconds < 90,
        f"nt traffic workbook (declared 65,536 x 16,217) -> {traffic.total_rows} rows in {seconds:.0f} s",
    )
    listing = await files.read_resource("nt", "ba378c1c-517a-428f-88c2-49bb28d96f7e")
    check(listing.sheet_chosen_by == "none", "nt traffic workbook without sheet -> sheet list")


async def yt() -> None:
    median = await files.read_resource("yt", "e4770cee-daf9-4fb7-8646-1adb84bc4abf", limit=2)
    check(median.format == "csv" and "median_age" in median.all_columns, "yt median age CSV")
    await expect_error(
        "yt 53 MB population CSV",
        UpstreamError,
        files.read_resource("yt", "9639c193-0dfb-440a-a864-c1ea50efb874"),
        "stops at",
    )


async def regina() -> None:
    permits = await files.read_resource("regina", "dcea70fc-87dd-4e04-bc34-b3ce6580daac", limit=2)
    check(
        permits.format == "xlsx" and "Permit Number" in permits.all_columns,
        f"regina building permits -> {permits.total_rows} rows",
    )


async def montreal() -> None:
    budget = await files.read_resource("montreal", "0f93bf05-44a8-49d5-854c-03d52afbd746")
    check(
        budget.sheet_chosen_by == "none" and len(budget.sheets) > 50,
        f"montreal budget workbook -> {len(budget.sheets)} sheets, no rows until one is named",
    )


async def qc() -> None:
    # A Montreal library workbook listed on Données Québec; labelled XLSX, really .xls.
    library = await files.read_resource("qc", "3e187baa-4cd7-47f0-9984-6e7ed8667047")
    check(
        library.format == "xls" and library.sheet_chosen_by == "none",
        f"qc Montreal library workbook (xlsx label, xls bytes) -> {library.format}",
    )


async def toronto() -> None:
    parking = await files.read_resource("toronto", "53caa383-5515-4b01-81aa-cfdced622548", limit=1)
    check(
        parking.format == "csv"
        and "overrides the site's robots.txt" in (parking.provenance.limits or ""),
        "toronto CSV with the robots.txt override stated in limits",
    )
    check(parking.source.licence_status == "not_stated", "toronto licence not stated -> warning")


async def ab() -> None:
    aish = await files.read_resource("ab", "be94d17b-66b8-4fad-9d2e-780bdc563bd7", limit=2)
    check(
        aish.format == "xlsx" and aish.rows[0]["Geography"] == "Alberta",
        f"ab AISH caseload -> {aish.total_rows} rows",
    )


PORTALS: dict[str, Callable[[], Awaitable[None]]] = {
    "federal": federal,
    "on": on,
    "bc": bc,
    "nt": nt,
    "yt": yt,
    "regina": regina,
    "montreal": montreal,
    "qc": qc,
    "toronto": toronto,
    "ab": ab,
}


async def run(name: str, step: Callable[[], Awaitable[None]]) -> None:
    try:
        await step()
    except Exception as exc:  # noqa: BLE001
        check(False, f"{name}: {type(exc).__name__}: {str(exc)[:200]}")


async def main(selected: list[str]) -> int:
    chosen = {k: v for k, v in PORTALS.items() if not selected or k in selected}
    await asyncio.gather(*(run(k, v) for k, v in chosen.items()))
    print("CKAN FILES SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))

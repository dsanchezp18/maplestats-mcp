"""Live smoke test for the BC Stats Excel module.

Reads real BC Stats workbooks and checks figures against numbers published
elsewhere (Statistics Canada tables, checked by hand on 2026-10-01):
- GDP by industry, BC, all industries, 2021, current dollars: 330,874
  ($ millions), Statistics Canada table 36-10-0402-01.
- Population estimates, BC, 1971: 2,240,470 (2,240.5 thousand), Statistics
  Canada table 17-10-0005-01.
- Consumer price index, BC all-items, August 2026: 163.8, Statistics Canada
  table 18-10-0004-01 (the workbook is replaced monthly, so only the pattern
  of the label row is asserted for later months).
- Labour Force Survey, BC employment (thousands), unadjusted, August 2026:
  2,948.8, Statistics Canada table 14-10-0287-01 (same caveat).
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.bc_stats import client
from maplestats_mcp.shared.http import new_client


async def _read(query: str, **kwargs):
    listing = await client.list_files(query=query)
    if not listing.files:
        raise RuntimeError(f"no BC Stats file matches {query!r}")
    return listing.files[0], await client.read_file(listing.files[0].url, **kwargs)


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += 0 if ok else 1

    async with new_client():
        listing = await client.list_files(limit=200)
        check(listing.total_files >= 40, f"list_files -> {listing.total_files} Excel files")
        check(
            all(f.licence for f in listing.files),
            "every listed file carries a licence",
        )
        check(
            any("Open Government Licence - British Columbia" == f.licence for f in listing.files),
            "OGL-BC files present",
        )

        _, gdp = await _read("GDP by Industry", sheet="BC GDP $Current", contains="All industries")
        by_year = dict(zip(gdp.header, gdp.rows[0], strict=False)) if gdp.rows else {}
        check(by_year.get("2021") == "330874", f"GDP 2021 = {by_year.get('2021')} (StatCan 330874)")

        _, pop = await _read(
            "Population Projections", sheet="Table 1", header_row=6, contains="Estimate", limit=500
        )
        row_1971 = next((r for r in pop.rows if r[1] == "1971"), None)
        check(
            row_1971 is not None and row_1971[2] == "2240.5",
            f"population 1971 = {row_1971 and row_1971[2]} thousand (StatCan 2,240,470)",
        )

        _cpi_file, cpi = await _read(
            "Consumer Price Index (CPI), Monthly", sheet="page1", header_row=6, contains="All-items"
        )
        check(
            bool(cpi.rows) and cpi.rows[0][1] == "All-items" and cpi.header[2].count(" ") == 1,
            f"CPI {cpi.header[2]!r} all-items BC = {cpi.rows[0][2] if cpi.rows else None} "
            "(StatCan 18-10-0004-01: 163.8 for Aug 26)",
        )

        _lfs_file, lfs = await _read(
            "Monthly Data Tables (XLS)", sheet="BC_LFS_DATA", contains="Aug", limit=10
        )
        check(
            bool(lfs.rows) and lfs.rows[0][2] != "",
            f"LFS BC_LFS_DATA {lfs.rows[0][:6] if lfs.rows else None} "
            "(StatCan 14-10-0287-01: unadjusted Aug 2026 employment 2948.8)",
        )

        # The largest workbook (32 MB, bilingual wages) exercises the size path.
        big = max(listing.files, key=lambda f: f.size_bytes or 0)
        data = await client.read_file(big.url, limit=3)
        check(bool(data.rows), f"largest file {big.title[:50]!r} ({big.size_bytes} bytes) reads")

    print("BC STATS SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Live smoke test for the Open Alberta file reader.

Every call is paced at one request per 10 seconds (portal crawl delay), so
the run takes several minutes. Checked by hand on 2026-10-02:
- AISH caseload workbook: first data row is April 2008, Alberta, family
  composition "Single Total".
- Traffic volumes workbook and the wildfire CSV open and page.
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.ab_opendata import client
from maplestats_mcp.shared.http import new_client


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += 0 if ok else 1

    async with new_client():
        orgs = await client.list_organizations(format="xlsx")
        check(len(orgs.organizations) >= 15, f"list_organizations -> {len(orgs.organizations)}")

        found = await client.search_datasets(query="AISH caseload", format="xlsx", limit=5)
        check(found.total_datasets >= 1, f"search_datasets -> {found.total_datasets}")
        dataset = next(d for d in found.datasets if "aish" in d.name)
        check(dataset.ogl_alberta, "AISH dataset is under the OGL-Alberta")
        detail = await client.get_dataset(dataset.name)
        check(detail.dataset.name == dataset.name, "get_dataset")

        resource = next(r for r in dataset.resources if r.readable and r.format == "XLSX")
        structure = await client.describe_resource(resource.url)
        check(bool(structure.sheets and structure.sheets[0].column_names), "describe_resource")
        rows = await client.read_resource(resource.url, filters={"Geography": "Alberta"}, limit=3)
        check(
            bool(rows.rows) and rows.rows[0].get("Ref_Date", "").startswith("2008"),
            f"read_resource -> {rows.total_rows} Alberta rows, first {rows.rows[:1]}",
        )
        check(
            rows.attribution is not None and "Open Government Licence" in rows.attribution,
            "attribution present",
        )

        csv_resource = next(r for r in dataset.resources if r.readable and r.format == "CSV")
        data = await client.read_resource(csv_resource.url, limit=2)
        check(data.format == "csv" and bool(data.rows), "read_resource on the CSV copy")

        traffic = await client.search_datasets(query="traffic volumes highway", limit=3)
        t_resource = next(
            r for d in traffic.datasets for r in d.resources if r.readable and r.format == "XLSX"
        )
        t_rows = await client.read_resource(t_resource.url, limit=2)
        check(bool(t_rows.rows), f"traffic volumes -> {t_rows.sheet!r}, {t_rows.columns[:4]}")

    print("AB OPENDATA SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

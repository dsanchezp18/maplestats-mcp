"""Live smoke test for every Socrata portal (or only those named as arguments)."""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.socrata import client, constants
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def check_portal(portal: str) -> bool:
    print(f"--- {portal}")
    search = await client.search_datasets(portal, limit=3)
    print(f"OK: search_datasets -> {search.total_count} datasets")
    tabular = next((d for d in search.datasets if d.dataset_type == "tabular"), None)
    if tabular is None:
        print("FAIL: no tabular dataset in the first page of results")
        return False

    detail = await client.get_dataset(portal, tabular.id)
    print(f"OK: get_dataset({tabular.id}) -> {len(detail.columns)} columns")
    rows = await client.query_dataset_rows(portal, tabular.id, limit=2)
    print(f"OK: query_dataset_rows -> {rows.returned_count} rows")
    categories = await client.list_categories(portal)
    print(f"OK: list_categories -> {len(categories.categories)}")

    try:
        await client.get_dataset(portal, "zzzz-zzzz")
    except NotFound:
        print("OK: unknown dataset raises NotFound")
    try:
        await client.search_datasets(portal, limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    return True


async def main() -> int:
    portals = sys.argv[1:] or list(constants.PORTALS)
    failed: list[str] = []
    for portal in portals:
        try:
            if not await check_portal(portal):
                failed.append(portal)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: {portal} -> {type(exc).__name__}: {exc}")
            failed.append(portal)
    if failed:
        print(f"SOCRATA SMOKE TEST FAILED for: {', '.join(failed)}")
        return 1
    print(f"SOCRATA SMOKE TEST PASSED ({len(portals)} portals)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

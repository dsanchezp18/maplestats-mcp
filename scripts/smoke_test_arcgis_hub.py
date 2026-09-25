"""Live smoke test for every ArcGIS Hub portal (or only those named as arguments)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maplestats_mcp.modules.arcgis_hub import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def check_portal(portal: str) -> int:
    print(f"--- {portal}")
    search = await _check(
        "search_datasets(water)", client.search_datasets(portal, "water", limit=3)
    )
    if not search.items:
        # A catalogue's content is not guaranteed to include any given
        # keyword -- confirmed live that some portals return zero
        # "water" matches despite having plenty of other datasets.
        print("(no 'water' matches; falling back to an unfiltered listing)")
        search = await _check("search_datasets()", client.search_datasets(portal, limit=3))
    if not search.items:
        print(f"FAIL: {portal} returned no search results at all")
        return 1

    item = search.items[0]
    detail = await _check("get_dataset", client.get_dataset(portal, item.id))
    if not detail.download_urls:
        print(f"FAIL: {portal} item has no download links")
        return 1

    if detail.service_url:
        rows = await _check(
            "query_feature_layer", client.query_feature_layer(portal, item.id, limit=2)
        )
        if not rows.rows:
            print(f"FAIL: {portal} query_feature_layer returned no rows")
            return 1
    else:
        print("OK (skip): item has no service_url to query")

    try:
        await client.get_dataset(portal, "__maple_missing_item__")
    except NotFound:
        print("OK: unknown item raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown item raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.search_datasets(portal, "x", limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"{portal} total matches for {search.query!r}: {search.total_count}")
    return 0


async def main() -> int:
    portals = sys.argv[1:] or list(constants.PORTALS)
    failed: list[str] = []
    for portal in portals:
        try:
            if await check_portal(portal):
                failed.append(portal)
        except Exception:  # noqa: BLE001
            failed.append(portal)
    if failed:
        print(f"ARCGIS-HUB SMOKE TEST FAILED for: {', '.join(failed)}")
        return 1
    print(f"ARCGIS-HUB SMOKE TEST PASSED ({len(portals)} portals)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

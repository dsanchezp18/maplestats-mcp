"""Live smoke test for the Data MB (Manitoba) ArcGIS Hub client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.arcgis_mb import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    search = await _check("search_datasets(water)", client.search_datasets("water", limit=3))
    if not search.items:
        print("FAIL: Manitoba returned no water search results")
        return 1

    item = search.items[0]
    detail = await _check("get_dataset", client.get_dataset(item.id))
    if not detail.download_urls:
        print("FAIL: Manitoba item has no download links")
        return 1

    if detail.service_url:
        rows = await _check("query_feature_layer", client.query_feature_layer(item.id, limit=2))
        if not rows.rows:
            print("FAIL: Manitoba query_feature_layer returned no rows")
            return 1
    else:
        print("OK (skip): item has no service_url to query")

    try:
        await client.get_dataset("__maple_missing_item__")
    except NotFound:
        print("OK: unknown item raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown item raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.search_datasets("x", limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Manitoba total matches for 'water': {search.total_count}")
    print("ARCGIS-MB SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

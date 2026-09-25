"""Live smoke test for the City of Vancouver Opendatasoft client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maplestats_mcp.modules.opendatasoft_vancouver import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def main() -> int:
    search = await _check("search_datasets(park)", client.search_datasets("park", limit=3))
    if not search.datasets:
        print("(no 'park' matches; falling back to an unfiltered listing)")
        search = await _check("search_datasets()", client.search_datasets(limit=3))
    if not search.datasets:
        print("FAIL: Vancouver returned no search results at all")
        return 1

    dataset = search.datasets[0]
    detail = await _check("get_dataset", client.get_dataset(dataset.id))
    if not detail.download_urls:
        print("FAIL: Vancouver dataset has no download links")
        return 1

    records = await _check("query_records", client.query_records(dataset.id, limit=2))
    if detail.records_count > 0 and not records.rows:
        print("FAIL: Vancouver query_records returned no rows for a non-empty dataset")
        return 1

    try:
        await client.get_dataset("__maple_missing_dataset__")
    except NotFound:
        print("OK: unknown dataset raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown dataset raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.search_datasets("x", limit=0)
    except InvalidInput:
        print("OK: limit=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: limit=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Vancouver total matches for {search.query!r}: {search.total_count}")
    print("OPENDATASOFT-VANCOUVER SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

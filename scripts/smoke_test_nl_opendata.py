"""Live smoke test for the Newfoundland and Labrador HTML catalogue client.

Run from the repository root with:

    uv run python scripts/smoke_test_nl_opendata.py
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.nl_opendata import client
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
    all_datasets = await _check(
        "search_datasets(all)", client.search_datasets(limit=3, dataset_type="all")
    )
    tabular = await _check(
        "search_datasets(tabular query)",
        client.search_datasets("birth", dataset_type="tabular", limit=3),
    )
    await _check(
        "search_datasets(spatial released_desc)",
        client.search_datasets(dataset_type="spatial", sort="released_desc", limit=3),
    )
    await _check(
        "search_datasets(tabular released_asc)",
        client.search_datasets(dataset_type="tabular", sort="released_asc", limit=3),
    )
    tags = await _check("list_tags", client.list_tags())
    if not tags.tags:
        print("FAIL: Newfoundland and Labrador returned no topic tags")
        return 1

    await _check(
        "search_datasets(tag)",
        client.search_datasets(dataset_type="all", tag_id=tags.tags[0].id, limit=3),
    )
    if not tabular.datasets:
        print("FAIL: Newfoundland and Labrador returned no birth search results")
        return 1
    detail = await _check("get_dataset", client.get_dataset(tabular.datasets[0].id))
    if not detail.files:
        print("FAIL: Newfoundland and Labrador sample has no downloadable files")
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

    print(f"Catalogue records returned by all-listing smoke call: {all_datasets.total_count}")
    print("NL-OPENDATA SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Live smoke test for the Ontario Data Catalogue CKAN client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ckan_on import client
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
    search = await _check("search_datasets(housing)", client.search_datasets("housing", rows=5))
    if not search.packages:
        print("FAIL: Ontario returned no housing search results")
        return 1

    detail = await _check("get_dataset(fr)", client.get_dataset(search.packages[0].id, lang="fr"))
    if not detail.resources or detail.organization is None:
        print("FAIL: Ontario sample has no organization or resource to continue smoke checks")
        return 1

    organizations = await _check("list_organizations", client.list_organizations())
    await _check("get_organization", client.get_organization(detail.organization.name, lang="fr"))
    await _check("get_resource", client.get_resource(detail.resources[0].id, lang="fr"))
    await _check("list_licenses", client.list_licenses(lang="fr"))
    await _check("list_tags", client.list_tags())
    await _check("list_groups", client.list_groups(lang="fr"))

    try:
        await client.get_dataset("__maple_missing_dataset__")
    except NotFound:
        print("OK: unknown dataset raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown dataset raised {type(exc).__name__}: {exc}")
        return 1

    try:
        await client.search_datasets("x", rows=0)
    except InvalidInput:
        print("OK: rows=0 raises InvalidInput")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: rows=0 raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Ontario organizations: {organizations.total_count}")
    print("CKAN-ON SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

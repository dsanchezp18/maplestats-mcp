"""Live smoke test for the City of Regina Open Data (CKAN Regina) client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ckan_regina import client
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
    search = await _check("search_datasets(building)", client.search_datasets("building", rows=5))
    if not search.packages:
        print("FAIL: Regina returned no building search results")
        return 1

    detail = await _check("get_dataset", client.get_dataset(search.packages[0].id))
    if not detail.resources:
        print("FAIL: Regina sample has no resources to continue smoke checks")
        return 1

    organizations = await _check("list_organizations", client.list_organizations())
    if organizations.total_count != 1:
        print(f"FAIL: expected exactly one organization, got {organizations.total_count}")
        return 1
    await _check("get_organization", client.get_organization(detail.organization.name))
    await _check("get_resource", client.get_resource(detail.resources[0].id))
    await _check("list_licenses", client.list_licenses())
    await _check("list_tags", client.list_tags())

    groups = await _check("list_groups", client.list_groups())
    if not groups.groups:
        print("FAIL: Regina returned no groups")
        return 1
    await _check("get_group", client.get_group(groups.groups[0].name))

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

    print(f"Regina organizations: {organizations.total_count}, groups: {groups.total_count}")
    print("CKAN-REGINA SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Live smoke test for every CKAN portal (or only those named as arguments)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maplestats_mcp.modules.ckan import client, constants
from maplestats_mcp.shared.errors import NotFound

# One DataStore-active resource per portal, confirmed live when each
# portal was added. Alberta's DataStore is disabled: it returns HTTP 500
# for every resource (re-test with f660db62-5687-4614-8f53-327652856f80).
DATASTORE_RESOURCES = {
    "federal": "3eb35dcd-9b0c-4ae9-a45c-e5e481567c23",
    "on": "ea9dc29c-b4f1-4426-b1f2-974ce995aca1",
    "bc": "d9377320-2c9e-4a3a-ba4a-af84ae3e344c",
    "qc": "9136d84a-8273-4777-ad68-9ab05d270322",
    "nt": "539e9585-ed0e-410f-9dcc-fe6a9fdacbb0",
    "montreal": "b7817317-55ca-4f23-98fe-30cf6c36d57c",
    "toronto": "e9f77756-2baf-46ba-b2c6-4050e2fba755",
    "regina": "38971b87-f58d-4499-8382-a30159a6da01",
}


async def _check(label: str, awaitable: Awaitable[Any]) -> Any:
    try:
        result = await awaitable
        print(f"OK: {label} -> {type(result).__name__}")
        return result
    except Exception as exc:
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        raise


async def check_portal(portal: str) -> int:
    info = constants.PORTALS[portal]
    print(f"--- {portal}")
    search = await _check("search_datasets()", client.search_datasets(portal, rows=3))
    if not search.packages:
        print(f"FAIL: {portal} returned no datasets")
        return 1

    detail = await _check("get_dataset", client.get_dataset(portal, search.packages[0].id, "fr"))
    if detail.resources:
        await _check("get_resource", client.get_resource(portal, detail.resources[0].id))

    orgs = await _check("list_organizations", client.list_organizations(portal))
    if orgs.organizations:
        await _check(
            "get_organization", client.get_organization(portal, orgs.organizations[0].name)
        )
    await _check("list_licenses", client.list_licenses(portal))
    if info.has_tags:
        await _check("list_tags", client.list_tags(portal))
    if info.groups != "none":
        groups = await _check("list_groups", client.list_groups(portal))
        if groups.groups:
            await _check("get_group", client.get_group(portal, groups.groups[0].name))

    if info.has_datastore:
        rows = await _check(
            "datastore_search",
            client.datastore_search(portal, DATASTORE_RESOURCES[portal], limit=2),
        )
        if not rows.records:
            print(f"FAIL: {portal} datastore_search returned no rows")
            return 1

    try:
        await client.get_dataset(portal, "__maple_missing_dataset__")
        print("FAIL: unknown dataset did not raise")
        return 1
    except NotFound:
        print("OK: unknown dataset raises NotFound")
    return 0


async def main() -> int:
    portals = sys.argv[1:] or list(constants.PORTALS)
    failures = 0
    for portal in portals:
        try:
            failures += await check_portal(portal)
        except Exception:  # noqa: BLE001
            failures += 1
    print(f"\n{len(portals) - failures}/{len(portals)} portals passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

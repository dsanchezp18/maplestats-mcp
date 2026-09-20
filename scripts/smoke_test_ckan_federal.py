"""Live smoke test for the Government of Canada CKAN client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

from maple_data_mcp.modules.ckan_federal import client
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
    search = await _check("search_datasets(climate)", client.search_datasets("climate", rows=5))
    if not search.packages:
        print("FAIL: federal catalogue returned no climate search results")
        return 1

    detail = await _check("get_dataset", client.get_dataset(search.packages[0].id))
    if not detail.resources or detail.organization is None:
        print("FAIL: federal sample has no organization or resource to continue smoke checks")
        return 1

    organizations = await _check("list_organizations", client.list_organizations())
    await _check("get_organization", client.get_organization(detail.organization.name))
    await _check("get_resource", client.get_resource(detail.resources[0].id))
    await _check("list_licenses", client.list_licenses(lang="fr"))

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

    # A confirmed-live DataStore-active resource: CRA's "2024 List of
    # charities" directors/officers table (569k+ rows). If this specific
    # resource id is ever retired, replace it with a current one found via
    # ckan_search_datasets(fq="organization:cra-arc") + a resource with
    # datastore_active=True.
    charity_directors_resource_id = "3eb35dcd-9b0c-4ae9-a45c-e5e481567c23"
    ds = await _check(
        "datastore_search",
        client.datastore_search(charity_directors_resource_id, limit=2),
    )
    if not ds.records:
        print("FAIL: DataStore-active resource returned no rows")
        return 1
    filtered = await _check(
        "datastore_search(filters)",
        client.datastore_search(charity_directors_resource_id, filters={"BN": ds.records[0]["BN"]}),
    )
    if filtered.total_count < 1:
        print("FAIL: filtered DataStore query returned no matches for its own sample row")
        return 1

    try:
        await client.datastore_search("__maple_missing_resource__")
    except NotFound:
        print("OK: non-DataStore resource id raises NotFound")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unknown DataStore resource raised {type(exc).__name__}: {exc}")
        return 1

    print(f"Federal organizations: {organizations.total_count}")
    print("CKAN-FEDERAL SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

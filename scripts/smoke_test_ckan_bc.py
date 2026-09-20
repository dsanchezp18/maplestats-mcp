"""Live smoke test for the ckan_bc module's client.py: calls every
exported function directly against the real BC Data Catalogue API
(catalogue.data.gov.bc.ca, not mocks), per AGENTS.md's "lesson from
auditing the StatCan module" -- a clean mocked pytest run only proves
the code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_bc.py
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any

from maple_data_mcp.modules.ckan_bc import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro: Coroutine[Any, Any, Any]) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def _expect_error(
    label: str, coro: Coroutine[Any, Any, Any], exc_cls: type[Exception]
) -> bool:
    try:
        await coro
        print(f"FAIL: {label} did not raise")
        return False
    except exc_cls as exc:
        print(f"OK: {label} raised {exc_cls.__name__}: {exc}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {label} raised {type(exc).__name__} instead of {exc_cls.__name__}: {exc}")
        return False


async def main() -> int:
    ok = True

    # --- search_datasets -------------------------------------------------
    search_result = await client.search_datasets("wildfire", rows=5)
    print(f"OK: search_datasets('wildfire') -> {search_result.total_count} total matches")
    print("  sample:", search_result.packages[0] if search_result.packages else None)
    ok &= len(search_result.packages) > 0

    match_all = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') match-all -> {match_all.total_count} total")
    ok &= match_all.total_count > 1000  # catalogue is ~3,357 datasets

    fq_result = await client.search_datasets("", fq="organization:bc-stats", rows=1)
    print(f"OK: search_datasets(fq=organization:bc-stats) -> {fq_result.total_count} total")
    ok &= fq_result.total_count > 0

    sorted_result = await client.search_datasets("", rows=1, sort="metadata_modified desc")
    print(f"OK: search_datasets(sort=metadata_modified desc) -> {sorted_result.total_count} total")

    ok &= await _expect_error(
        "search_datasets(rows=0)", client.search_datasets("x", rows=0), InvalidInput
    )

    # --- get_dataset -------------------------------------------------------
    dataset_id = search_result.packages[0].id
    dataset = await client.get_dataset(dataset_id)
    print(f"OK: get_dataset({dataset_id}) -> title={dataset.title!r}")
    print(f"  tags={dataset.tags[:5]} groups={dataset.groups}")
    print(f"  resources={len(dataset.resources)}, first={dataset.resources[0].model_dump()}")
    ok &= dataset.id == dataset_id

    # A dataset known live to carry both populated tags and groups, so the
    # tags/groups parsing path is exercised even if the first search hit
    # happens to have neither.
    census_dataset = await client.get_dataset(
        "census-profiles-for-bc-census-subdivisions-2016-census"
    )
    print(f"OK: get_dataset(census profiles) -> tags={census_dataset.tags}")
    print(f"  groups={census_dataset.groups}")
    ok &= len(census_dataset.tags) > 0
    ok &= len(census_dataset.groups) > 0

    ok &= await _expect_error(
        "get_dataset(unknown)", client.get_dataset("not-a-real-dataset-xyz-123"), NotFound
    )

    # --- list_organizations / get_organization -----------------------------
    orgs = await client.list_organizations()
    print(f"OK: list_organizations -> {orgs.total_count} organizations")
    ok &= orgs.total_count > 100  # confirmed live: 164 with >=1 dataset (of ~244 registered)

    org = await client.get_organization("bc-stats")
    print(f"OK: get_organization(bc-stats) -> {org.model_dump()}")
    ok &= org.name == "bc-stats"
    ok &= org.image_url is not None and org.image_url.startswith("https://")
    ok &= org.website_url is not None

    ok &= await _expect_error(
        "get_organization(unknown)", client.get_organization("not-a-real-org-xyz"), NotFound
    )

    # --- get_resource --------------------------------------------------------
    resource_id = dataset.resources[0].id
    resource_detail = await client.get_resource(resource_id)
    print(f"OK: get_resource({resource_id}) -> {resource_detail.resource.model_dump()}")
    ok &= resource_detail.resource.id == resource_id

    ok &= await _expect_error(
        "get_resource(unknown)", client.get_resource("not-a-real-resource-xyz"), NotFound
    )

    # --- list_licenses ---------------------------------------------------------
    licenses = await client.list_licenses()
    print(f"OK: list_licenses -> {len(licenses.licenses)} licenses")
    print("  sample:", licenses.licenses[0].model_dump())
    ok &= len(licenses.licenses) > 5

    # --- list_tags / search --------------------------------------------------
    all_tags = await client.list_tags()
    print(f"OK: list_tags() -> total_count={all_tags.total_count}, truncated={all_tags.truncated}")
    ok &= all_tags.total_count > 1000  # confirmed live: ~7,087
    ok &= all_tags.truncated is True
    ok &= len(all_tags.tags) <= 200

    wildfire_tags = await client.list_tags(query="wildfire")
    print(f"OK: list_tags(query='wildfire') -> {[t.name for t in wildfire_tags.tags]}")
    ok &= wildfire_tags.truncated is False
    ok &= len(wildfire_tags.tags) > 0

    # --- list_groups / get_group ------------------------------------------
    groups = await client.list_groups()
    print(f"OK: list_groups -> {groups.total_count} groups")
    print("  sample:", groups.groups[0].model_dump() if groups.groups else None)
    ok &= groups.total_count > 10  # confirmed live: 21 groups with >=1 dataset of 26 total

    group_name = groups.groups[0].name
    group_detail = await client.get_group(group_name)
    print(f"OK: get_group({group_name}) -> {group_detail.model_dump()}")
    ok &= group_detail.name == group_name

    ok &= await _expect_error(
        "get_group(unknown)", client.get_group("not-a-real-group-xyz"), NotFound
    )

    # --- datastore_search ---------------------------------------------------
    # A confirmed-live DataStore-active resource: BC's Foundation Skills
    # Assessment 2021/22-2025/26 district-level results. If this specific
    # resource id is ever retired, replace it with a current one found via
    # ckan_bc_search_datasets("foundation skills assessment") + a resource
    # with datastore_active=True.
    fsa_resource_id = "d9377320-2c9e-4a3a-ba4a-af84ae3e344c"
    ds = await client.datastore_search(fsa_resource_id, limit=2)
    print(f"OK: datastore_search -> {ds.total_count} total, {ds.returned_count} returned")
    ok &= ds.returned_count > 0

    filtered = await client.datastore_search(
        fsa_resource_id,
        filters={"DATA_LEVEL": "District Level", "FSA_SKILL_CODE": "Numeracy", "GRADE": "4"},
        limit=2,
    )
    print(f"OK: datastore_search(filters) -> {filtered.total_count} total")
    ok &= filtered.total_count > 0

    ok &= await _expect_error(
        "datastore_search(non-datastore resource)",
        client.datastore_search("__maple_missing_resource__"),
        NotFound,
    )

    print()
    print("CKAN-BC SMOKE TEST PASSED" if ok else "CKAN-BC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

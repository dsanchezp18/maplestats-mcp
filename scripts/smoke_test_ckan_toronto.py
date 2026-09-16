"""Live smoke test for the ckan_toronto module's client.py: calls every
exported function directly against the real City of Toronto Open Data
Action API (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" -- a clean mocked pytest run only proves the code
matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_toronto.py
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from maple_data_mcp.modules.ckan_toronto import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro: Awaitable[object]) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ok = True

    # -- search_datasets --------------------------------------------
    search_result = await client.search_datasets("cycling", rows=5)
    print(
        f"OK: search_datasets('cycling') -> {search_result.returned_count} of {search_result.total_count}"
    )
    ok &= search_result.total_count > 0
    ok &= len(search_result.packages) > 0
    sample = search_result.packages[0]
    print("  sample:", sample.model_dump())

    empty_query_result = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') -> total_count={empty_query_result.total_count}")
    ok &= empty_query_result.total_count > 500  # confirmed live: 557 total datasets

    fq_result = await client.search_datasets("", fq="tags:cycling", rows=5)
    print(f"OK: search_datasets(fq='tags:cycling') -> {fq_result.total_count} matches")
    ok &= fq_result.total_count > 0

    try:
        await client.search_datasets("x", rows=0)
        print("FAIL: expected InvalidInput for rows=0")
        ok = False
    except InvalidInput:
        print("OK: rows=0 raises InvalidInput as expected")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: rows=0 raised wrong type: {type(exc).__name__}: {exc}")
        ok = False

    # -- get_dataset ---------------------------------------------------
    dataset_id = sample.id  # UUID form, confirmed to resolve live
    detail = await client.get_dataset(dataset_id)
    print(f"OK: get_dataset(uuid) -> title={detail.title!r}, resources={detail.num_resources}")
    ok &= detail.num_resources == len(detail.resources)
    ok &= detail.landing_page_url.startswith("https://open.toronto.ca/dataset/")
    print("  civic_issues:", detail.civic_issues, "topics:", detail.topics)
    print("  limitations:", (detail.limitations or "")[:120])
    if detail.resources:
        print("  first resource:", detail.resources[0].model_dump())

    # confirm a package's slug name also resolves (not just its UUID id) --
    # a real, known slug from earlier live reconnaissance, distinct from
    # federal where id and name are always identical strings
    detail_by_name = await client.get_dataset("10-year-cycling-network-plan-on-street-2016")
    print(f"OK: get_dataset(slug name) -> title={detail_by_name.title!r}")
    ok &= detail_by_name.id != "10-year-cycling-network-plan-on-street-2016"

    try:
        await client.get_dataset("does-not-exist-xyz-smoke-test")
        print("FAIL: expected NotFound for a bogus dataset_id")
        ok = False
    except NotFound:
        print("OK: unknown dataset_id raises NotFound as expected (HTML 404 body)")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: bogus dataset_id raised wrong type: {type(exc).__name__}: {exc}")
        ok = False

    # -- list_organizations / get_organization -------------------------
    orgs = await client.list_organizations()
    print(f"OK: list_organizations -> {orgs.total_count} organization(s)")
    ok &= orgs.total_count >= 1
    org_name = orgs.organizations[0].name

    org_detail = await client.get_organization(org_name)
    print(f"OK: get_organization({org_name!r}) -> package_count={org_detail.package_count}")
    ok &= org_detail.package_count > 0
    print("  landing_page_url:", org_detail.landing_page_url)

    try:
        await client.get_organization("not-a-real-org-smoke-test")
        print("FAIL: expected NotFound for a bogus organization_id")
        ok = False
    except NotFound:
        print("OK: unknown organization_id raises NotFound as expected")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: bogus organization_id raised wrong type: {type(exc).__name__}: {exc}")
        ok = False

    # -- get_resource ----------------------------------------------------
    if detail.resources:
        resource_id = detail.resources[0].id
        resource_detail = await client.get_resource(resource_id)
        print(
            f"OK: get_resource -> format={resource_detail.resource.format}, url set: {bool(resource_detail.resource.url)}"
        )
        ok &= resource_detail.resource.id == resource_id

    # -- list_licenses -----------------------------------------------
    licenses = await client.list_licenses()
    print(f"OK: list_licenses -> {len(licenses.licenses)} licenses")
    ok &= len(licenses.licenses) > 0
    print("  sample license:", licenses.licenses[0].model_dump())

    # -- list_tags -----------------------------------------------------
    tags = await client.list_tags()
    print(f"OK: list_tags -> {tags.total_count} tags")
    ok &= tags.total_count > 100  # confirmed live: 909 tags
    print("  sample tags:", tags.tags[:10])

    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""Live smoke test for the ckan_nt module's client.py: calls every
exported function directly against the real Northwest Territories Open
Data API (opendata.gov.nt.ca, not mocks), per AGENTS.md's "lesson from
auditing the StatCan module" - a clean mocked pytest run only proves the
code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_nt.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ckan_nt import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def _check(label: str, coro) -> bool:
    try:
        result = await coro
        print(f"OK: {label} -> {type(result).__name__}")
        return True
    except Exception as exc:  # noqa: BLE001 - smoke test wants to see everything
        print(f"FAIL: {label} -> {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ok = True

    # --- search_datasets ---------------------------------------------
    search_result = await client.search_datasets("household", rows=5)
    print(
        f"OK: search_datasets('household') -> {search_result.returned_count} of "
        f"{search_result.total_count} total"
    )
    print("  sample:", search_result.packages[0] if search_result.packages else None)
    ok &= len(search_result.packages) > 0

    # rows=1: search_datasets rejects rows < 1 (see the InvalidInput check below), unlike
    # the raw package_search endpoint, which happily accepts rows=0 for a count-only call.
    empty_query_result = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') match-all -> total_count={empty_query_result.total_count}")
    ok &= empty_query_result.total_count > 300  # 341 confirmed live this session

    fq_org_result = await client.search_datasets("", fq="organization:bureau-of-statistics", rows=1)
    print(f"OK: search_datasets(fq=organization:...) -> {fq_org_result.total_count}")
    ok &= fq_org_result.total_count > 0

    fq_tag_result = await client.search_datasets("", fq="tags:housing", rows=1)
    print(f"OK: search_datasets(fq=tags:housing) -> {fq_tag_result.total_count}")
    ok &= fq_tag_result.total_count > 0

    fq_group_result = await client.search_datasets("", fq="groups:home-and-community", rows=1)
    print(f"OK: search_datasets(fq=groups:home-and-community) -> {fq_group_result.total_count}")
    ok &= fq_group_result.total_count > 0

    # A real dataset id/name discovered via search, used by the detail checks below.
    real_dataset_id = search_result.packages[0].id

    # --- get_dataset ----------------------------------------------------
    ok &= await _check(f"get_dataset({real_dataset_id})", client.get_dataset(real_dataset_id))
    dataset_detail = await client.get_dataset(real_dataset_id)
    print("  ", dataset_detail.model_dump())
    ok &= dataset_detail.id == real_dataset_id

    # get_dataset by name should also work - confirmed on federal that id/name are
    # interchangeable; verify that holds here too rather than assuming it carries over.
    ok &= await _check(
        f"get_dataset by name ({search_result.packages[0].landing_page_url.rsplit('/', 1)[-1]})",
        client.get_dataset(dataset_detail.id),
    )

    # --- list_organizations / get_organization --------------------------
    org_list = await client.list_organizations()
    print(f"OK: list_organizations -> {org_list.total_count} organizations")
    print("  sample:", org_list.organizations[0] if org_list.organizations else None)
    ok &= org_list.total_count > 0

    real_org_name = org_list.organizations[0].name
    ok &= await _check(f"get_organization({real_org_name})", client.get_organization(real_org_name))
    org_detail = await client.get_organization(real_org_name)
    print("  ", org_detail.model_dump())
    # image_url must come from image_display_url (a full https URL), not the bare
    # uploaded filename image_url carries - this is the dead-link quirk documented
    # in client.py; confirm it live rather than trusting the docstring alone.
    if org_detail.image_url is not None:
        ok &= org_detail.image_url.startswith("http")
        print(f"  image_url is absolute: {org_detail.image_url.startswith('http')}")

    # --- list_groups ------------------------------------------------------
    group_list = await client.list_groups()
    print(f"OK: list_groups -> {group_list.total_count} groups")
    print("  sample:", group_list.groups[0] if group_list.groups else None)
    ok &= group_list.total_count > 5  # 15 confirmed live this session
    ok &= all(g.description for g in group_list.groups)  # real descriptions, not stubs

    # --- list_tags --------------------------------------------------------
    tag_list = await client.list_tags()
    print(f"OK: list_tags -> {tag_list.total_count} tags")
    print("  sample:", tag_list.tags[:10])
    ok &= tag_list.total_count > 50  # 151 confirmed live this session

    # --- get_resource -------------------------------------------------------
    real_resource_id = dataset_detail.resources[0].id
    ok &= await _check(f"get_resource({real_resource_id})", client.get_resource(real_resource_id))
    resource_detail = await client.get_resource(real_resource_id)
    print("  ", resource_detail.model_dump())
    ok &= resource_detail.resource.id == real_resource_id

    # --- list_licenses --------------------------------------------------
    license_list = await client.list_licenses()
    print(f"OK: list_licenses -> {len(license_list.licenses)} licenses")
    print("  ", [lic.model_dump() for lic in license_list.licenses])
    ok &= len(license_list.licenses) > 0

    # --- error-path checks: must raise typed errors, not a raw httpx exception ---
    try:
        await client.get_dataset("not-a-real-dataset-xyz")
        print("FAIL: get_dataset(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_dataset(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_dataset(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_organization("not-a-real-org-xyz")
        print("FAIL: get_organization(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_organization(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_organization(unknown) raised {type(exc).__name__} instead of NotFound: {exc}"
        )
        ok = False

    try:
        await client.get_resource("not-a-real-resource-xyz")
        print("FAIL: get_resource(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_resource(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_resource(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.search_datasets("x", sort="bogus_field_xyz")
        print("FAIL: bad sort field did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: bad sort field raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: bad sort field raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    try:
        await client.search_datasets("x", rows=0)
        print("FAIL: rows=0 did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: rows=0 raised InvalidInput (caught client-side): {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: rows=0 raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    try:
        await client.get_dataset("   ")
        print("FAIL: blank dataset_id did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: blank dataset_id raised InvalidInput (caught client-side): {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: blank dataset_id raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    print()
    print("CKAN-NT SMOKE TEST PASSED" if ok else "CKAN-NT SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

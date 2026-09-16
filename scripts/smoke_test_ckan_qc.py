"""Live smoke test for the ckan_qc module's client.py: calls every
exported function directly against the real donneesquebec.ca CKAN
Action API (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" -- a clean mocked pytest run only proves the code
matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_qc.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ckan_qc import client
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
    search_result = await client.search_datasets("transport", rows=5)
    print(
        f"OK: search_datasets('transport') -> {search_result.returned_count} of {search_result.total_count}"
    )
    ok &= search_result.total_count > 0  # a filtered query -- not the full catalogue count
    ok &= len(search_result.packages) > 0
    sample = search_result.packages[0]
    print("  sample:", sample.model_dump())

    empty_query_result = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') match-all -> count={empty_query_result.total_count}")
    ok &= (
        empty_query_result.total_count == search_result.total_count
        or empty_query_result.total_count > 1000
    )

    fq_result = await client.search_datasets("", fq="organization:mtq", rows=1)
    print(f"OK: search_datasets(fq=organization:mtq) -> count={fq_result.total_count}")
    ok &= fq_result.total_count > 0

    sort_result = await client.search_datasets("", rows=1, sort="metadata_modified desc")
    print(f"OK: search_datasets(sort=metadata_modified desc) -> count={sort_result.total_count}")
    ok &= sort_result.total_count > 0

    # --- get_dataset ----------------------------------------------------
    real_dataset_id = sample.id
    real_dataset_name = sample.name
    ok &= await _check(f"get_dataset({real_dataset_name})", client.get_dataset(real_dataset_name))
    dataset = await client.get_dataset(real_dataset_name)
    print("  ", dataset.model_dump())
    ok &= dataset.id == real_dataset_id
    ok &= dataset.language is not None  # confirmed always "FR"/"FR_EN" live

    ok &= await _check(f"get_dataset(by id {real_dataset_id})", client.get_dataset(real_dataset_id))

    # --- get_dataset with lang="fr" must be a byte-for-byte no-op ------
    dataset_fr = await client.get_dataset(real_dataset_name, lang="fr")
    ok &= dataset_fr.title == dataset.title and dataset_fr.notes == dataset.notes
    print(f"OK: lang no-op confirmed -- en/fr titles identical: {dataset.title!r}")

    # --- list_organizations / get_organization --------------------------
    ok &= await _check("list_organizations", client.list_organizations())
    org_list = await client.list_organizations()
    print(f"  {org_list.total_count} organizations")
    ok &= org_list.total_count > 100  # confirmed 144 live
    org_sample = next(
        (o for o in org_list.organizations if o.name == "mtq"), org_list.organizations[0]
    )
    print("  sample org:", org_sample.model_dump())

    ok &= await _check(
        f"get_organization({org_sample.name})", client.get_organization(org_sample.name)
    )
    org_detail = await client.get_organization(org_sample.name)
    print("  ", org_detail.model_dump())

    try:
        await client.get_organization("not-a-real-org-xyz-123")
        print("FAIL: get_organization(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_organization(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_organization(unknown) raised {type(exc).__name__} instead of NotFound: {exc}"
        )
        ok = False

    # --- get_resource -----------------------------------------------------
    if dataset.resources:
        real_resource_id = dataset.resources[0].id
        ok &= await _check(
            f"get_resource({real_resource_id})", client.get_resource(real_resource_id)
        )
        resource_detail = await client.get_resource(real_resource_id)
        print("  ", resource_detail.model_dump())
    else:
        print("FAIL: sample dataset had no resources to test get_resource with")
        ok = False

    # --- list_licenses ------------------------------------------------
    ok &= await _check("list_licenses", client.list_licenses())
    license_list = await client.list_licenses()
    print(f"  {len(license_list.licenses)} licenses")
    ok &= len(license_list.licenses) > 0
    print("  sample license:", license_list.licenses[0].model_dump())

    # --- list_groups (real data here, unlike ckan_federal) -------------
    ok &= await _check("list_groups", client.list_groups())
    group_list = await client.list_groups()
    print(f"  {group_list.total_count} groups")
    ok &= group_list.total_count == 12  # confirmed exactly 12 live
    print("  sample group:", group_list.groups[0].model_dump())

    # --- list_tags (real data here, unlike ckan_federal) ----------------
    ok &= await _check("list_tags(unfiltered)", client.list_tags())
    unfiltered_tags = await client.list_tags()
    print(f"  {unfiltered_tags.total_count} total tags, truncated={unfiltered_tags.truncated}")
    ok &= unfiltered_tags.total_count > 1000  # confirmed 4,402 live
    ok &= unfiltered_tags.truncated is True
    ok &= len(unfiltered_tags.tags) <= 200

    ok &= await _check("list_tags(query='transport')", client.list_tags(query="transport"))
    filtered_tags = await client.list_tags(query="transport")
    print(
        f"  {filtered_tags.total_count} tags matching 'transport', truncated={filtered_tags.truncated}"
    )
    ok &= filtered_tags.total_count > 0
    ok &= filtered_tags.truncated is False  # a real substring filter should never need the cap

    # --- error paths: must raise typed errors, not a raw httpx exception ---
    try:
        await client.get_dataset("definitely-not-a-real-dataset-xyz-123")
        print("FAIL: get_dataset(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_dataset(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_dataset(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_resource("definitely-not-a-real-resource-xyz-123")
        print("FAIL: get_resource(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_resource(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_resource(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.search_datasets("x", rows=0)
        print("FAIL: rows=0 did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: rows=0 raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: rows=0 raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    try:
        await client.search_datasets("x", rows=1000)
        print("FAIL: rows over SEARCH_ROWS_MAX did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: rows over SEARCH_ROWS_MAX raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: rows over SEARCH_ROWS_MAX raised {type(exc).__name__} instead of InvalidInput: {exc}"
        )
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
        await client.get_dataset("   ")
        print("FAIL: blank dataset_id did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: blank dataset_id raised InvalidInput: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: blank dataset_id raised {type(exc).__name__} instead of InvalidInput: {exc}")
        ok = False

    print()
    print("CKAN-QC SMOKE TEST PASSED" if ok else "CKAN-QC SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

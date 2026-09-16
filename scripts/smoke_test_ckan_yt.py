"""Live smoke test for the ckan_yt module's client.py: calls every
exported function directly against the real Yukon Open Data CKAN
Action API (not mocks), per AGENTS.md's "lesson from auditing the
StatCan module" - a clean mocked pytest run only proves the code
matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_yt.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ckan_yt import client
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

    # 1. Connectivity + real catalogue size (site_read 400s on this
    # deployment per the task brief -- package_search is the real
    # connectivity check here).
    search_result = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') -> total_count={search_result.total_count}")
    ok &= 1000 < search_result.total_count < 20000  # confirmed live: 3,841

    # 2. A realistic query, to pull a real dataset id/organization/tag
    # for every downstream check below.
    mining_result = await client.search_datasets("mining", rows=5)
    print(f"OK: search_datasets('mining') -> {len(mining_result.packages)} results")
    ok &= len(mining_result.packages) > 0
    sample_pkg = mining_result.packages[0]
    print("  sample:", sample_pkg.model_dump())
    ok &= sample_pkg.tags != [] or sample_pkg.groups != []  # confirms tags/groups populated

    # 3. fq filtering by tag/group/organization -- all real on this
    # portal, unlike federal.
    ok &= await _check(
        "search_datasets(fq='tags:mining')",
        client.search_datasets("", fq="tags:mining", rows=3),
    )
    tag_fq_result = await client.search_datasets("", fq="tags:mining", rows=3)
    print(f"  {tag_fq_result.total_count} datasets tagged 'mining'")
    ok &= tag_fq_result.total_count > 0

    ok &= await _check(
        "search_datasets(fq='groups:economics-and-industry')",
        client.search_datasets("", fq="groups:economics-and-industry", rows=3),
    )

    # 4. Full dataset detail for the sampled id.
    ok &= await _check("get_dataset(sample_pkg.id)", client.get_dataset(sample_pkg.id))
    dataset_detail = await client.get_dataset(sample_pkg.id)
    print(f"  title={dataset_detail.title!r} num_resources={dataset_detail.num_resources}")
    print(f"  custodian={dataset_detail.custodian!r} isopen={dataset_detail.isopen}")
    print(f"  tags={dataset_detail.tags} groups={dataset_detail.groups}")
    ok &= dataset_detail.num_resources == len(dataset_detail.resources)

    # 5. lang="fr" should not change dataset content (English-only
    # confirmed live) but should change landing_page_url's prefix.
    dataset_detail_fr = await client.get_dataset(sample_pkg.id, lang="fr")
    ok &= dataset_detail_fr.title == dataset_detail.title
    ok &= dataset_detail_fr.landing_page_url.startswith("https://open.yukon.ca/fr/dataset/")
    print(f"  lang=fr landing_page_url={dataset_detail_fr.landing_page_url}")

    # 6. Organizations.
    org_list = await client.list_organizations()
    print(f"OK: list_organizations -> {org_list.total_count} organizations")
    ok &= 10 < org_list.total_count < 100  # confirmed live: 25
    sample_org = org_list.organizations[0]

    ok &= await _check(
        f"get_organization({sample_org.name!r})", client.get_organization(sample_org.name)
    )
    org_detail = await client.get_organization(sample_org.name)
    print(f"  {org_detail.model_dump()}")
    ok &= org_detail.package_count >= 0

    # 7. A real resource id from the sampled dataset.
    if dataset_detail.resources:
        sample_resource_id = dataset_detail.resources[0].id
        ok &= await _check(
            f"get_resource({sample_resource_id!r})", client.get_resource(sample_resource_id)
        )
        resource_detail = await client.get_resource(sample_resource_id)
        print(f"  {resource_detail.resource.model_dump()}")

    # 8. Licenses.
    license_list = await client.list_licenses()
    print(f"OK: list_licenses -> {len(license_list.licenses)} licenses")
    ok &= len(license_list.licenses) > 0
    print("  sample:", license_list.licenses[0].model_dump())

    # 9. Tags -- genuinely populated on this portal, unlike federal.
    tag_list = await client.list_tags()
    print(f"OK: list_tags -> {tag_list.total_count} tags")
    ok &= tag_list.total_count > 100  # confirmed live: 914
    ok &= "mining" in tag_list.tags

    # 10. Groups -- genuinely populated on this portal, unlike federal.
    group_list = await client.list_groups()
    print(f"OK: list_groups -> {group_list.total_count} groups")
    ok &= group_list.total_count == 17  # confirmed live
    group_names = {g.name for g in group_list.groups}
    ok &= "economics-and-industry" in group_names
    print("  sample:", group_list.groups[0].model_dump())

    # Error-path checks: must raise typed errors, not a raw httpx
    # exception -- confirmed live that these come back in the same
    # shape shared/ckan.py already maps for the federal portal.
    try:
        await client.get_dataset("this-definitely-does-not-exist-xyz123")
        print("FAIL: get_dataset(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_dataset(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_dataset(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_organization("this-definitely-does-not-exist-xyz123")
        print("FAIL: get_organization(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_organization(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: get_organization(unknown) raised {type(exc).__name__} "
            f"instead of NotFound: {exc}"
        )
        ok = False

    try:
        await client.get_resource("this-definitely-does-not-exist-xyz123")
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

    print()
    print("CKAN_YT SMOKE TEST PASSED" if ok else "CKAN_YT SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

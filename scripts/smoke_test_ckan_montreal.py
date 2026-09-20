"""Live smoke test for the ckan_montreal module's client.py: calls every
exported function directly against the real City of Montreal open-data
API (donnees.montreal.ca, not mocks), per AGENTS.md's "lesson from
auditing the StatCan module" - a clean mocked pytest run only proves the
code matches assumptions the tests share with it, not that those
assumptions are correct.

Usage:
    uv run python scripts/smoke_test_ckan_montreal.py
"""

from __future__ import annotations

import asyncio
import sys

from maple_data_mcp.modules.ckan_montreal import client
from maple_data_mcp.shared.errors import InvalidInput, NotFound


async def main() -> int:
    ok = True

    # --- search_datasets ---------------------------------------------
    search_result = await client.search_datasets("arbres", rows=5)
    print(
        f"OK: search_datasets('arbres') -> {search_result.returned_count} of {search_result.total_count}"
    )
    print("  sample:", search_result.packages[0] if search_result.packages else None)
    ok &= search_result.total_count > 0
    ok &= len(search_result.packages) > 0

    # Empty query is a deliberate match-all, per client.py's docstring.
    all_result = await client.search_datasets("", rows=1)
    print(f"OK: search_datasets('') match-all -> total_count={all_result.total_count}")
    ok &= all_result.total_count > 300  # confirmed live count was 404

    fq_result = await client.search_datasets("", fq="organization:ville-de-montreal", rows=1)
    print(
        f"OK: search_datasets(fq=organization:ville-de-montreal) -> total_count={fq_result.total_count}"
    )
    ok &= fq_result.total_count > 0

    # Confirmed live: an unrecognized sort field is silently ignored here
    # (HTTP 200), unlike ckan_federal where it raises InvalidInput.
    bad_sort_result = await client.search_datasets("x", sort="bogus_field_zzz", rows=1)
    print(
        f"OK: search_datasets(sort=bogus) did not raise -> total_count={bad_sort_result.total_count}"
    )

    try:
        await client.search_datasets("x", rows=0)
        print("FAIL: rows=0 did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: rows=0 raised InvalidInput: {exc}")

    # --- get_dataset ---------------------------------------------------
    dataset_id = search_result.packages[0].id
    dataset_name = search_result.packages[0].name
    detail = await client.get_dataset(dataset_id)
    print(f"OK: get_dataset({dataset_id}) -> title={detail.title!r}")
    print(
        f"  tags={detail.tags[:5]} groups={detail.groups} update_frequency={detail.update_frequency}"
    )
    print(f"  num_resources={detail.num_resources} resources_len={len(detail.resources)}")
    print(f"  landing_page_url={detail.landing_page_url}")
    ok &= detail.id == dataset_id

    # Confirmed live: name and id are NOT always identical on this
    # portal (unlike ckan_federal) -- get_dataset by name must also work.
    detail_by_name = await client.get_dataset(dataset_name)
    print(f"OK: get_dataset(by name={dataset_name!r}) -> id={detail_by_name.id}")
    ok &= detail_by_name.id == dataset_id

    detail_fr = await client.get_dataset(dataset_id, lang="fr")
    detail_en = await client.get_dataset(dataset_id, lang="en")
    print(f"  landing_page_url fr={detail_fr.landing_page_url}")
    print(f"  landing_page_url en={detail_en.landing_page_url}")
    ok &= "/fr/dataset/" in detail_fr.landing_page_url
    ok &= "/en/dataset/" in detail_en.landing_page_url
    # Content itself must be identical regardless of lang -- this portal
    # has no translation layer (see module docstrings).
    ok &= detail_fr.title == detail_en.title
    ok &= detail_fr.notes == detail_en.notes

    try:
        await client.get_dataset("not-a-real-dataset-xyz-999")
        print("FAIL: get_dataset(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_dataset(unknown) raised NotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: get_dataset(unknown) raised {type(exc).__name__} instead of NotFound: {exc}")
        ok = False

    try:
        await client.get_dataset("   ")
        print("FAIL: get_dataset(blank) did not raise")
        ok = False
    except InvalidInput as exc:
        print(f"OK: get_dataset(blank) raised InvalidInput: {exc}")

    # --- resource ---------------------------------------------------
    if detail.resources:
        resource_id = detail.resources[0].id
        resource_detail = await client.get_resource(resource_id)
        print(f"OK: get_resource({resource_id}) -> format={resource_detail.resource.format}")
        ok &= resource_detail.resource.id == resource_id
    else:
        print("WARN: sampled dataset had no resources -- skipping get_resource happy path")

    try:
        await client.get_resource("not-a-real-resource-xyz-999")
        print("FAIL: get_resource(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_resource(unknown) raised NotFound: {exc}")

    # --- organizations ---------------------------------------------------
    orgs = await client.list_organizations()
    print(f"OK: list_organizations -> {orgs.total_count} organizations")
    for o in orgs.organizations:
        print(f"  - {o.name}: {o.title} ({o.package_count} datasets)")
    ok &= orgs.total_count > 0

    org_id = orgs.organizations[0].name
    org_detail = await client.get_organization(org_id)
    print(
        f"OK: get_organization({org_id}) -> title={org_detail.title!r} package_count={org_detail.package_count}"
    )
    print(f"  image_url={org_detail.image_url}")
    ok &= org_detail.package_count > 0
    # image_url must be the resolved CDN link (image_display_url), not a
    # bare uploaded filename -- confirmed live quirk.
    if org_detail.image_url:
        ok &= org_detail.image_url.startswith("http")

    try:
        await client.get_organization("not-a-real-org-xyz-999")
        print("FAIL: get_organization(unknown) did not raise")
        ok = False
    except NotFound as exc:
        print(f"OK: get_organization(unknown) raised NotFound: {exc}")

    # --- licenses ---------------------------------------------------
    licenses = await client.list_licenses()
    print(f"OK: list_licenses -> {len(licenses.licenses)} licenses")
    print("  sample:", licenses.licenses[0] if licenses.licenses else None)
    ok &= len(licenses.licenses) > 0

    # --- tags ---------------------------------------------------
    tags = await client.list_tags()
    print(f"OK: list_tags -> {tags.total_count} tags")
    print("  sample:", tags.tags[:5])
    ok &= tags.total_count > 100  # confirmed live count was 1174

    # --- groups ---------------------------------------------------
    groups = await client.list_groups()
    print(f"OK: list_groups -> {groups.total_count} groups")
    for g in groups.groups[:3]:
        print(f"  - {g.name}: {g.title} ({g.package_count} datasets)")
    ok &= groups.total_count > 5  # confirmed live count was 12

    ds = await client.datastore_search("b7817317-55ca-4f23-98fe-30cf6c36d57c", limit=2)
    print(f"OK: datastore_search -> {ds.total_count} total, {ds.returned_count} returned")
    ok &= ds.returned_count > 0

    print()
    print("CKAN MONTREAL SMOKE TEST PASSED" if ok else "CKAN MONTREAL SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

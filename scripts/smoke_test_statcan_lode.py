"""Live smoke test for the statcan.lode module: every tool against the real site.

Downloads are kept small on purpose: ODHF GeoJSON (2 MB), ODEF (1.5 MB),
ODCAF (1.3 MB), Index of Remoteness (136 KB) and the Prince Edward Island
buildings zip (16 MB). The National Address Register (1.67 GB) is only
listed and previewed by HTTP range, and the 269 MB ODSRF is not fetched.
Pages are paced at the site's two-second crawl-delay, so this takes a few
minutes.

Usage:
    uv run python scripts/smoke_test_statcan_lode.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.statcan.lode import client
from maplestats_mcp.shared.errors import InvalidInput

NAR = "https://www150.statcan.gc.ca/n1/pub/46-26-0002/2022001/202606.zip"


async def main() -> int:
    ok = True

    listing = await client.list_databases("en")
    keys = {d.key for d in listing.databases}
    print(
        f"OK: list_databases -> {len(keys)} databases, odhf latest "
        f"{next(d.latest_release for d in listing.databases if d.key == 'odhf')}"
    )
    ok &= {"odhf", "odsrf", "odb", "nar", "pmd", "remoteness"} <= keys
    french = await client.list_databases("fr")
    ok &= any("BDOESS" in d.title for d in french.databases)

    files = await client.list_files("odhf", "en", sizes=True)
    print(f"OK: list_files(odhf) -> {[(f.filename, f.size_bytes) for f in files.files]}")
    ok &= len(files.files) == 3 and all(f.size_bytes for f in files.files)

    described = await client.describe("odhf")
    print(f"OK: describe(odhf) -> {len(described.fields)} fields from {described.field_sources}")
    ok &= any(f.name == "prov_terr" and f.description for f in described.fields)

    hospitals = await client.query("odhf", province="AB", type="Hospital", limit=3)
    print(
        f"OK: query(odhf AB Hospital) -> {hospitals.total_matched} matched, "
        f"{hospitals.records[0]['name']} at {hospitals.records[0]['latitude']}"
    )
    ok &= hospitals.total_matched > 10 and 49 < float(hospitals.records[0]["latitude"] or 0) < 61

    ottawa = await client.query("odhf", bbox=[-75.9, 45.3, -75.5, 45.5], limit=2)
    ok &= ottawa.total_matched > 100
    print(f"OK: query(odhf bbox Ottawa) -> {ottawa.total_matched} matched")

    buildings = await client.query("odb", province="PE", bbox=[-63.2, 46.2, -63.1, 46.3], limit=2)
    print(f"OK: query(odb PE bbox) -> {buildings.total_matched} matched ({buildings.format})")
    ok &= buildings.total_matched > 1000 and buildings.records[0]["geometry_type"] == "Polygon"

    schools = await client.query("odef", province="ON", name="ottawa", limit=2)
    print(f"OK: query(odef ON ottawa) -> {schools.total_matched} matched")
    ok &= schools.total_matched > 0

    museums = await client.query("odcaf", province="BC", type="museum", limit=2)
    print(f"OK: query(odcaf BC museum) -> {museums.total_matched} matched")
    ok &= museums.total_matched > 50

    remote = await client.query("remoteness", csd="Iqaluit", limit=1)
    print(f"OK: query(remoteness Iqaluit) -> {remote.records[0]['Index_of_remoteness']}")
    ok &= remote.total_matched == 1

    archive = await client.list_zip(NAR)
    print(f"OK: list_zip(NAR) -> {len(archive.entries)} files, {archive.archive_bytes:,} bytes")
    ok &= archive.archive_bytes > 1_000_000_000
    preview = await client.preview_member(NAR, "Locations/Location_62.csv", rows=3)
    print(
        f"OK: preview_member(NAR Nunavut) -> {preview.rows_returned} rows, "
        f"{preview.compressed_bytes_read:,} bytes read, complete={preview.scan_complete}"
    )
    ok &= preview.rows_returned == 3 and preview.compressed_bytes_read < 5_000_000

    for label, call in (
        ("odb without province", client.query("odb")),
        ("nar query", client.query("nar")),
        ("unknown province", client.query("odhf", province="Atlantis")),
    ):
        try:
            await call
            print(f"FAIL: {label} should raise InvalidInput")
            ok = False
        except InvalidInput:
            print(f"OK: {label} raises InvalidInput as expected")

    print("\nSTATCAN LODE SMOKE TEST PASSED" if ok else "\nSMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

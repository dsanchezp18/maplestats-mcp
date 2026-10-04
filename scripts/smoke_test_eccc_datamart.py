"""Live smoke test for the ECCC Data Catalogue file tree (eccc_datamart_).

Downloads the 11 MB GHGRP CSV and one 37-39 MB NPRI single-year CSV, so a run
takes one to two minutes. Checked by hand on 2026-10-03:
- GHGRP 2004-2024, 1,879 facilities in 2024; G10001 is Division Alma (Quebec).
- NPRI 2024: 59,556 rows, 7,738 facilities; facility 1 is Alberta-Pacific Forest
  Industries Inc. (AB).
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.eccc_datamart import client, constants
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    failures = 0

    def check(ok: bool, label: str) -> None:
        nonlocal failures
        print(("OK: " if ok else "FAIL: ") + label)
        failures += 0 if ok else 1

    root = await client.browse("/")
    names = {e.name for e in root.entries}
    check({"air", "substances", "water", "climate"} <= names, f"browse / -> {sorted(names)}")

    ghg_folder = await client.browse(constants.GHGRP_FOLDER)
    check(
        ghg_folder.catalogue_id is not None and ghg_folder.files >= 5,
        f"browse GHGRP -> {ghg_folder.files} files, catalogue {ghg_folder.catalogue_id}",
    )

    found = await client.search("pollutant release inventory")
    check(
        any("pollutant-release" in h.path for h in found.hits),
        f"search -> {found.total_hits} hits of {found.indexed_folders}, first "
        f"{found.hits[0].path if found.hits else None}",
    )
    french = await client.search("gaz à effet de serre", lang="fr")
    check(any("greenhouse" in h.path for h in french.hits), "search in French")

    readme = next(e for e in ghg_folder.entries if e.name.startswith("Lisez"))
    structure = await client.describe_file(
        f"{constants.GHGRP_FOLDER}/PDGES-GHGRP-Tableaux-Donnees-Data-Tables-2024.xlsx"
    )
    check(
        structure.total_sheets >= 1 and any(d.excerpt for d in structure.documentation),
        f"describe_file xlsx -> {structure.total_sheets} sheets, docs "
        f"{[d.name for d in structure.documentation]}",
    )
    rows = await client.read_file(readme.path, limit=3)
    check(rows.format == "csv" and bool(rows.all_columns), "read_file on the read-me CSV")

    ten_year = (
        "/substances/plansreports/reporting-facilities-pollutant-release-and-transfer-data/"
        "ten-year-data-tables-by-province-industry-and-substance-releases/"
        "NPRI-INRP_Province_Air_2015-2024.csv"
    )
    table = await client.read_file(ten_year, filters={"Province / Province": "AB"}, limit=2)
    check(table.total_rows > 0, f"read_file ten-year table -> {table.total_rows} rows")

    try:
        await client.read_file(
            f"{constants.NPRI_BULK_FOLDER}/NPRI-INRP_ReleasesRejets_1993-present.csv"
        )
        check(False, "375 MB bulk file should be refused")
    except InvalidInput as exc:
        check("cap" in str(exc), f"bulk file refused: {exc}")

    ghg = await client.ghgrp_facilities(year=2024, province="AB", order="largest", limit=3)
    check(
        ghg.total_records > 500 and ghg.records[0].total_co2e is not None,
        f"ghgrp AB 2024 -> {ghg.total_records}, top {ghg.records[0].facility} "
        f"{ghg.records[0].total_co2e}",
    )
    alma = await client.ghgrp_facilities(ghgrp_id="G10001")
    check(len(alma.records) >= 10, f"ghgrp G10001 -> {len(alma.records)} years")

    npri = await client.npri_facilities(province="AB", substance="mercury", order="largest")
    check(
        npri.year >= 2024 and npri.total_records > 0,
        f"npri {npri.year} AB mercury -> {npri.total_records}, top "
        f"{npri.records[0].facility if npri.records else None}",
    )
    first = await client.npri_facilities(npri_id="1", limit=2, lang="fr")
    check(
        bool(first.records) and first.records[0].province == "AB",
        f"npri id 1 -> {first.records[0].facility if first.records else None}",
    )
    try:
        await client.npri_facilities(year=2010)
        check(False, "2010 should be refused")
    except InvalidInput:
        check(True, "npri 2010 refused with a note on the bulk files")

    print("ECCC DATAMART SMOKE TEST", "FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

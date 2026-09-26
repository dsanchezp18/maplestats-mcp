"""Live smoke test for PHAC Health Infobase data files, per AGENTS.md.

Describes every catalogue entry (English, and French where PHAC
publishes a French file), checking that each file downloads, parses,
has rows, and still has the date and geography columns the catalogue
names. Then runs targeted queries through all three tools.

Usage:
    uv run python scripts/smoke_test_phac_infobase.py
"""

from __future__ import annotations

import asyncio
import sys

from maplestats_mcp.modules.phac_infobase import client
from maplestats_mcp.modules.phac_infobase.catalogue import DATASETS, TOPICS
from maplestats_mcp.shared.errors import InvalidInput, NotFound


async def _check_entry(dataset_id: str, lang: str) -> bool:
    entry = next(d for d in DATASETS if d.id == dataset_id)
    try:
        described = await client.describe_dataset(dataset_id, lang)
    except ValueError as exc:  # every typed error; report it and keep going
        print(f"FAIL: {dataset_id} ({lang}) -> {type(exc).__name__}: {exc}")
        return False
    problems = []
    if described.row_count == 0:
        problems.append("no rows")
    if entry.date_columns and described.date_column is None:
        problems.append(f"no date column among {entry.date_columns}")
    if entry.date_columns and described.date_start is None:
        problems.append("no parseable dates")
    if entry.geo_columns and described.geo_column is None:
        problems.append(f"no geography column among {entry.geo_columns}")
    status = "FAIL" if problems else "OK"
    print(
        f"{status}: {dataset_id} ({lang}) {described.row_count} rows, "
        f"{len(described.columns)} cols, {described.encoding}, "
        f"{described.date_start}..{described.date_end}, lm={described.last_modified}"
        + (f" -> {problems}" if problems else "")
    )
    return not problems


async def main() -> int:
    ok = True

    listing = client.list_datasets()
    print(f"OK: {listing.total_count} datasets in {len(listing.topics)} topics")
    ok &= listing.total_count == len(DATASETS) and len(listing.topics) == len(TOPICS)
    french = client.list_datasets(topic="substance_use", query="opioïdes", lang="fr")
    print("OK: fr substance_use 'opioïdes' ->", [d.id for d in french.datasets])
    ok &= any(d.id == "opioid_stimulant_harms" for d in french.datasets)

    for entry in DATASETS:
        ok &= await _check_entry(entry.id, "en")
        if entry.url_fr:
            ok &= await _check_entry(entry.id, "fr")

    # Targeted queries, values checked 2026-09-26.
    deaths = await client.query(
        "opioid_stimulant_harms",
        filters={
            "Substance": "Opioids",
            "Source": "Deaths",
            "Specific_Measure": "Overall numbers",
            "Unit": "Number",
            "Time_Period": "By year",
        },
        geography="Canada",
        start="2023",
        end="2023",
    )
    value = deaths.rows[0]["Value"] if deaths.rows else ""
    print(f"OK: apparent opioid toxicity deaths, Canada 2023 -> {value}")
    # 8,083 on 2026-09-26; the band allows for revisions.
    ok &= value.replace(",", "").isdigit() and 7000 < int(value.replace(",", "")) < 10000

    fr_deaths = await client.query(
        "opioid_stimulant_harms",
        filters={"Unité": "Nombre", "Période_Temps": "Par année", "Source": "Mortalité"},
        geography="Colombie-Britannique",
        limit=5,
        lang="fr",
    )
    print(f"OK: fr harms BC -> {fr_deaths.matching_rows} rows, markers {fr_deaths.markers}")
    ok &= fr_deaths.matching_rows > 0 and fr_deaths.geo_column == "Région"

    flu = await client.query(
        "rvdss_weekly_detections",
        filters={"virus": "Influenza"},
        geography="ON",
        limit=4,
    )
    print(
        "OK: influenza detections Ontario ->", [(r["date"], r["percentpositive"]) for r in flu.rows]
    )
    ok &= flu.returned_count == 4 and all(r["province"] == "Ontario" for r in flu.rows)

    ww = await client.query(
        "wastewater_weekly",
        filters={"measureid": "covN2", "Location": "Canada"},
        start="2026-01-01",
        limit=3,
    )
    print("OK: national SARS-CoV-2 wastewater ->", [(r["weekstart"], r["w_avg"]) for r in ww.rows])
    ok &= ww.returned_count == 3 and all(r["weekstart"] >= "2026-01-01" for r in ww.rows)

    daily = await client.query("wastewater_daily", geography="Québec", limit=2)
    print(f"OK: daily wastewater QC via PRUID -> {[r['pruid'] for r in daily.rows]}")
    ok &= daily.returned_count == 2 and all(r["pruid"] == "24" for r in daily.rows)

    tb = await client.query("tuberculosis_incidence_by_province", geography="Nunavut")
    print(f"OK: TB Nunavut -> {tb.returned_count} years, last {tb.rows[-1] if tb.rows else None}")
    ok &= tb.returned_count >= 9

    vri = await client.query(
        "cnisp_vri_incidence", filters={"virus": "RSV", "age_group": "Pediatric"}, limit=2
    )
    print("OK: CNISP pediatric RSV ->", vri.rows)
    ok &= vri.returned_count == 2

    measles = await client.query("measles_cases_by_province", geography="Alberta")
    print("OK: measles Alberta ->", measles.rows)
    ok &= measles.returned_count == 1

    ccdi = await client.describe_dataset("ccdi_indicators_2018", lang="fr")
    print(f"OK: CCDI fr decimal comma -> {ccdi.decimal_comma}, encoding {ccdi.encoding}")
    ok &= ccdi.decimal_comma and ccdi.encoding == "cp1252"

    anomalies = await client.query(
        "congenital_anomalies", lang="fr", limit=1, start="2005", end="2005"
    )
    icd = anomalies.rows[0]["ICD10"] if anomalies.rows else ""
    print(f"OK: congenital anomalies fr (cp850) -> {icd[:60]}")
    ok &= "nouveau-né" in icd

    aefi = await client.describe_dataset("aefi_reports_by_vaccine")
    print("OK: AEFI markers ->", [(m.value, m.count) for m in aefi.markers])
    ok &= any(m.value == "X" for m in aefi.markers)

    for bad in (
        lambda: client.query("no_such_dataset"),
        lambda: client.query("measles_cases_by_province", start="2024"),
        lambda: client.query("rvdss_weekly_detections", filters={"nope": "x"}),
    ):
        try:
            await bad()
            print("FAIL: an invalid query did not raise")
            ok = False
        except (InvalidInput, NotFound) as exc:
            print(f"OK: rejected -> {type(exc).__name__}")

    print("\nPHAC INFOBASE SMOKE TEST PASSED" if ok else "\nPHAC INFOBASE SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

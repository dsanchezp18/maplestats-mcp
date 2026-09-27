"""Live smoke test for the CFIA module, per AGENTS.md.

Covers every cfia_ tool in both languages, with values checked against
inspection.canada.ca on 2026-09-26, and reproduce_code for one of them. Counts that grow as new detections
are confirmed are checked as lower bounds; closed years are exact.

Usage:
    uv run python scripts/smoke_test_cfia.py
"""

from __future__ import annotations

import asyncio
import collections
import re
import sys
import tempfile
import time
import unicodedata
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.cfia import constants, tools
from maplestats_mcp.modules.reproduce import cfia as reproduce_cfia
from maplestats_mcp.modules.reproduce import client as reproduce
from maplestats_mcp.shared.errors import InvalidInput


async def main() -> int:
    ok = True

    # --- cfia_reportable_diseases -------------------------------------------
    yearly = await tools.cfia_reportable_diseases()
    print(
        f"OK: reportable EN -> {yearly.row_count} rows, years {yearly.years_available[0]}-"
        f"{yearly.years_available[-1]}, current as of {yearly.current_as_of}, "
        f"modified {yearly.provenance.as_of}"
    )
    ok &= yearly.years_available[0] == 2011 and yearly.row_count >= 69
    ok &= yearly.current_as_of is not None and yearly.current_as_of >= date(2026, 8, 31)
    closed = {(r.year, r.disease_key): r.count for r in yearly.rows if r.year <= 2025}
    # Values on the live page, 2026-09-26.
    ok &= closed[(2025, "avian_influenza")] == 119
    ok &= closed[(2022, "avian_influenza")] == 279
    ok &= closed[(2013, "equine_infectious_anemia")] == 36
    ok &= closed[(2016, "avian_influenza")] == 1  # "Notifiable avian influenza"

    french = await tools.cfia_reportable_diseases(
        2022, 2026, "maladie débilitante chronique", totals_by="year", lang="fr"
    )
    totals = [(t.key, t.total) for t in french.totals or []]
    print(f"OK: reportable FR CWD 2022-2026 -> {totals}, name {french.rows[0].disease!r}")
    ok &= french.rows[0].disease == "Maladie débilitante chronique"
    ok &= ("2025", 9) in totals and ("2022", 6) in totals

    all_fr = await tools.cfia_reportable_diseases(lang="fr")
    ok &= {(r.year, r.disease_key): r.count for r in all_fr.rows} == {
        (r.year, r.disease_key): r.count for r in yearly.rows
    }
    print("OK: reportable FR counts equal EN counts for every year and disease")

    by_disease = await tools.cfia_reportable_diseases(totals_by="disease")
    print(f"OK: totals by disease -> {[(t.key, t.total) for t in by_disease.totals or []][:4]}")
    ok &= by_disease.totals is not None and by_disease.totals[0].key == "avian_influenza"

    try:
        await tools.cfia_reportable_diseases(disease="foot and mouth disease")
        ok = False
        print("FAIL: unknown disease did not raise")
    except InvalidInput as exc:
        print("OK: unknown disease ->", type(exc).__name__)

    # --- cfia_disease_detections --------------------------------------------
    cwd = await tools.cfia_disease_detections("CWD", 2025, 2025, counts_by="month")
    print(f"OK: CWD 2025 -> {cwd.row_count} rows, {cwd.herd_count} herds")
    ok &= (cwd.row_count, cwd.herd_count) == (7, 9)
    may = next(r for r in cwd.rows if r.date_confirmed == date(2025, 5, 5))
    ok &= (may.animal_type, may.herds, may.province_codes) == ("Elk", 3, ["SK"])

    everything = await tools.cfia_disease_detections()
    herds = collections.Counter()
    for row in everything.rows:
        herds[(row.disease_key, row.year)] += row.herds
    expected = {
        (r.disease_key, r.year): r.count
        for r in yearly.rows
        if r.disease_key in constants.DETECTION_PAGES
        and not (r.disease_key == "avian_influenza" and r.year >= 2021)
    }
    print(
        f"OK: all detections -> {everything.row_count} rows over {len(everything.diseases)} "
        f"pages; herds match yearly totals: {dict(herds) == expected}"
    )
    ok &= len(everything.diseases) == 7 and dict(herds) == expected

    scrapie_fr = await tools.cfia_disease_detections("tremblante", 2019, 2019, lang="fr")
    print(
        "OK: scrapie 2019 FR ->",
        [(r.date_confirmed, r.date_text, r.animal_type) for r in scrapie_fr.rows],
    )
    ok &= [r.date_confirmed for r in scrapie_fr.rows] == [date(2019, 6, 21)] * 2
    ok &= scrapie_fr.rows[0].animal_type == "Mouton"

    sask_tb = await tools.cfia_disease_detections("tuberculose bovine", province="SK", lang="fr")
    print("OK: bovine TB in SK FR ->", [(r.year, r.location) for r in sask_tb.rows])
    ok &= [r.year for r in sask_tb.rows][-1] == 2016
    ok &= sask_tb.rows[-1].location == "Alberta et Saskatchewan"

    elk = await tools.cfia_disease_detections("cwd", animal_type="wapiti", counts_by="province")
    print("OK: CWD elk by province ->", [(c.key, c.herds) for c in elk.counts or []])
    ok &= elk.counts is not None and {c.key for c in elk.counts} >= {"AB", "SK"}

    try:
        await tools.cfia_disease_detections("equine infectious anemia")
        ok = False
        print("FAIL: EIA detections did not raise")
    except InvalidInput as exc:
        print("OK: EIA detections ->", type(exc).__name__)

    # --- cfia_avian_influenza -----------------------------------------------
    current = await tools.cfia_avian_influenza(status="current")
    summary = current.province_summary
    print(
        f"OK: HPAI current -> {current.total_matched}, by province "
        f"{[(c.key, c.current) for c in current.counts]}; summary "
        f"{summary and (summary.total_current, summary.total_released, summary.total_birds_impacted)}"
    )
    ok &= current.total_matched >= 1 and all(p.status == "current" for p in current.premises)
    released = summary.total_released if summary else None
    ok &= released is not None and released >= 650

    everything_ai = await tools.cfia_avian_influenza(counts_by="year", limit=1000)
    years = {c.key: c.total for c in everything_ai.counts}
    print(f"OK: HPAI all -> {everything_ai.total_matched} premises, by year {years}")
    ok &= everything_ai.total_matched >= 662
    ok &= years.get("2022") == 280 and years.get("2023") == 132 and years.get("2021") == 1
    by_id = {p.premises_id: p for p in everything_ai.premises}
    ok &= by_id["AB-IP116"].date_detected == date(2026, 9, 26)
    ok &= "BC-IP99" in by_id and by_id["QC-IP58"].low_pathogenic
    differences = [n for n in everything_ai.notes if "differ" in n]
    print("OK: premises list vs province summary ->", differences or "consistent")

    fr = await tools.cfia_avian_influenza(province="AB", date_from="2024", lang="fr", limit=500)
    ponoka = next((p for p in fr.premises if p.premises_id == "AB-IP104"), None)
    print(
        f"OK: HPAI AB since 2024 FR -> {fr.total_matched}; AB-IP104 location "
        f"{ponoka and ponoka.location!r}; notes {fr.notes[3:]}"
    )
    ok &= ponoka is not None and ponoka.location == "le comté de Ponoka"
    ok &= fr.premises[0].province == "Alberta" and fr.premises[0].premises_type_label in (
        "commerciale",
        "non-commerciale",
    )
    fr_summary = fr.province_summary
    ok &= fr_summary is not None and any(
        r.province == "Colombie-Britannique" for r in fr_summary.rows
    )

    commercial = await tools.cfia_avian_influenza(
        premises_type="commercial", date_from="2024-11", date_to="2024-11", counts_by="province"
    )
    print(
        "OK: commercial premises Nov 2024 ->",
        commercial.total_matched,
        [(c.key, c.total) for c in commercial.counts],
    )
    ok &= commercial.total_matched >= 40

    try:
        await tools.cfia_avian_influenza(province="Atlantis")
        ok = False
        print("FAIL: unknown province did not raise")
    except InvalidInput as exc:
        print("OK: unknown province ->", type(exc).__name__)

    # --- reproduce_code ---------------------------------------------------------
    # The scripts parse the pages themselves; run the Python script's own
    # parser on the live CWD page and check it finds the tool's 2025 rows.
    args = {"disease": "CWD", "year_from": 2025, "year_to": 2025}
    reproduced = await reproduce.reproduce("cfia_disease_detections", args)
    languages = sorted(script.language for script in reproduced.scripts)
    spec = await reproduce_cfia.detections(args, {})
    parser = spec.native["python"].body.split("\nSCHEMA = {")[0]
    with tempfile.TemporaryDirectory() as folder:
        namespace = {
            "re": re,
            "time": time,
            "unicodedata": unicodedata,
            "date": date,
            "httpx": httpx,
            "BeautifulSoup": BeautifulSoup,
            "RAW_DIR": Path(folder),
        }
        exec(compile(parser, "<cfia-script>", "exec"), namespace)  # noqa: S102 - generated here
        parsed = [
            row
            for row in namespace["detections_for"](*namespace["PAGES"][0])
            if row["year"] == 2025
        ]
    print(
        f"OK: reproduce_code CWD 2025 -> {languages}; the Python script parses "
        f"{len(parsed)} rows, {sum(r['herds'] for r in parsed)} herds"
    )
    ok &= languages == ["julia", "python", "r", "stata"]
    ok &= (len(parsed), sum(r["herds"] for r in parsed)) == (cwd.row_count, cwd.herd_count)

    print("\nCFIA SMOKE TEST PASSED" if ok else "\nCFIA SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

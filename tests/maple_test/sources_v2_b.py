"""Maple Test v2 -- answer key, agent B (12 "beyond" questions).

Every expected value is fetched live from the primary source:
  * Health Canada Drug Product Database API (health-products.canada.ca/api/drug)
  * IRCC Express Entry rounds JSON (the file the canada.ca rounds page loads)
  * Statistics Canada WDS, 2021 Census tables in the 98-10 series

Independent of the tool under test: no maplestats_mcp imports, no MCP calls.
Needs httpx with HTTP/2 (pip install "httpx[http2]"): StatCan resets urllib,
and canada.ca resets curl's HTTP/2 stream but serves httpx.

Run:  python v2_agent_b.py   (prints the 12 question dicts as JSON)
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any, NoReturn

import httpx

TODAY = "2026-11-03"
UA = {"User-Agent": "Mozilla/5.0 (maple-test answer key)"}

DPD = "https://health-products.canada.ca/api/drug"
EE_PAGE = (
    "https://www.canada.ca/en/immigration-refugees-citizenship/corporate/mandate/"
    "policies-operational-instructions-agreements/ministerial-instructions/"
    "express-entry-rounds.html"
)
WDS = "https://www150.statcan.gc.ca/t1/wds/rest"
WDS_COORD = f"{WDS}/getDataFromCubePidCoordAndLatestNPeriods"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

_client = httpx.Client(http2=True, timeout=90, headers=UA, follow_redirects=True)


def fail(msg: str) -> NoReturn:
    raise SystemExit(f"ANSWER KEY BROKEN: {msg}")


def _request(method: str, url: str, **kw: Any) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = _client.request(method, url, **kw)
            if r.status_code >= 500 or r.status_code == 429:
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.HTTPError, httpx.StreamError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    fail(f"{method} {url} failed after retries: {last!r}")
    raise AssertionError  # unreachable


def get_json(url: str, params: dict | None = None) -> Any:
    r = _request("GET", url, params=params)
    return json.loads(r.content.decode("utf-8-sig"))


def full_url(url: str, params: dict) -> str:
    return str(httpx.URL(url, params=params))


# --------------------------------------------------------------------------
# Health Canada DPD
# --------------------------------------------------------------------------


def dpd_product(din: str) -> tuple[dict, str]:
    params = {"din": din, "lang": "en", "type": "json"}
    data = get_json(f"{DPD}/drugproduct/", params)
    if not isinstance(data, list):
        fail(f"DPD drugproduct for DIN {din}: unexpected payload {data!r}")
    matches = [d for d in data if d.get("drug_identification_number") == din]
    if len(matches) != 1:
        fail(f"DPD: expected exactly one product for DIN {din}, got {len(matches)}")
    return matches[0], full_url(f"{DPD}/drugproduct/", params)


def dpd_status(code: int) -> tuple[dict, str]:
    params = {"id": code, "lang": "en", "type": "json"}
    data = get_json(f"{DPD}/status/", params)
    if isinstance(data, list):
        data = data[0] if data else {}
    if not data.get("status"):
        fail(f"DPD status missing for drug_code {code}")
    return data, full_url(f"{DPD}/status/", params)


def dpd_ingredients(code: int) -> tuple[list[dict], str]:
    params = {"id": code, "lang": "en", "type": "json"}
    data = get_json(f"{DPD}/activeingredient/", params)
    if not isinstance(data, list) or not data:
        fail(f"DPD activeingredient missing for drug_code {code}")
    return data, full_url(f"{DPD}/activeingredient/", params)


def ingredient(ais: list[dict], name_startswith: str) -> dict:
    hits = [a for a in ais if a["ingredient_name"].upper().startswith(name_startswith)]
    if len(hits) != 1:
        fail(f"DPD: ingredient {name_startswith} not found once in {ais}")
    return hits[0]


def hc_questions() -> list[dict]:
    qs: list[dict] = []

    # B-01 Paxlovid: brand + company + strengths --------------------------
    din = "02524031"
    p, purl = dpd_product(din)
    ais, aurl = dpd_ingredients(p["drug_code"])
    nirm = ingredient(ais, "NIRMATRELVIR")
    rito = ingredient(ais, "RITONAVIR")
    if nirm["strength_unit"] != "MG" or rito["strength_unit"] != "MG":
        fail(f"Paxlovid strength units changed: {ais}")
    nirm_mg, rito_mg = float(nirm["strength"]), float(rito["strength"])
    print(
        f"[B-01] DIN {din}: {p['brand_name']} / {p['company_name']} / "
        f"nirmatrelvir {nirm_mg} mg, ritonavir {rito_mg} mg",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-01",
            "category": "Health products",
            "group": "beyond",
            "eval_type": "comparison",
            "question": (
                "What drug has the Canadian DIN 02524031, which company holds it, and "
                "what are the strengths of its active ingredients?"
            ),
            "expected": {
                "answer": p["brand_name"],
                "company": p["company_name"],
                "nirmatrelvir_mg": nirm_mg,
                "ritonavir_mg": rito_mg,
            },
            "headline": ["nirmatrelvir_mg", "ritonavir_mg"],
            "tolerances": {"nirmatrelvir_mg": 0, "ritonavir_mg": 0},
            "answer_pattern": p["brand_name"],
            "tolerance": f"Brand {p['brand_name']} and company {p['company_name']}; strengths exact (mg per tablet)",
            "citations": [
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": p["brand_name"],
                    "release_or_revision_date": p.get("last_update_date"),
                    "url": purl,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": f"NIRMATRELVIR {nirm['strength']} MG; RITONAVIR {rito['strength']} MG",
                    "release_or_revision_date": None,
                    "url": aurl,
                },
            ],
            "traps": [
                "Two different tablets in one co-pack: 150 mg nirmatrelvir and 100 mg ritonavir are per tablet, not per dose (a dose is two nirmatrelvir tablets plus one ritonavir).",
                "The company is Pfizer Canada ULC, not Pfizer Inc.",
            ],
        }
    )

    # B-02 Aromasin: active ingredient + strength --------------------------
    din = "02242705"
    p, purl = dpd_product(din)
    ais, aurl = dpd_ingredients(p["drug_code"])
    if len(ais) != 1:
        fail(f"DIN {din} no longer single-ingredient: {ais}")
    ai = ais[0]
    if ai["strength_unit"] != "MG":
        fail(f"DIN {din} strength unit changed: {ai}")
    st, st_url = dpd_status(p["drug_code"])
    print(
        f"[B-02] DIN {din}: {p['brand_name']} / {ai['ingredient_name']} {ai['strength']} {ai['strength_unit']} / {st['status']}",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-02",
            "category": "Health products",
            "group": "beyond",
            "eval_type": "comparison",
            "question": "What is the active ingredient in the product with DIN 02242705, at what strength, and under what brand name is it sold?",
            "expected": {
                "answer": ai["ingredient_name"],
                "brand_name": p["brand_name"],
                "strength_mg": float(ai["strength"]),
            },
            "headline": ["strength_mg"],
            "tolerances": {"strength_mg": 0},
            "answer_pattern": ai["ingredient_name"],
            "tolerance": f"Ingredient {ai['ingredient_name']} ({p['brand_name']}); strength exact in mg per tablet",
            "citations": [
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": p["brand_name"],
                    "release_or_revision_date": p.get("last_update_date"),
                    "url": purl,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": f"{ai['ingredient_name']} {ai['strength']} {ai['strength_unit']}",
                    "release_or_revision_date": None,
                    "url": aurl,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": st["status"],
                    "release_or_revision_date": st.get("history_date"),
                    "url": st_url,
                },
            ],
            "traps": [
                "Generic exemestane products have other DINs; the question is about this DIN only.",
            ],
        }
    )

    # B-03 Ozempic 0.25/0.5 mg pen: marketed status -----------------------
    din, sibling = "02471477", "02471469"
    p, purl = dpd_product(din)
    st, st_url = dpd_status(p["drug_code"])
    ps, _ = dpd_product(sibling)
    sts, sts_url = dpd_status(ps["drug_code"])
    if st["status"] != "Dormant":
        fail(f"DIN {din} status is now {st['status']!r}, not Dormant: rewrite B-03")
    if "OZEMPIC" not in p["brand_name"] or "0.25" not in p["descriptor"]:
        fail(f"DIN {din} is no longer the Ozempic 0.25/0.5 mg pen: {p}")
    print(
        f"[B-03] DIN {din}: {p['brand_name']} [{p['descriptor']}] status {st['status']} since {st['history_date']}; "
        f"sibling {sibling} {sts['status']}",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-03",
            "category": "Health products",
            "group": "beyond",
            "eval_type": "comparison",
            "question": "Is the Ozempic pen that delivers 0.25 mg or 0.5 mg doses (DIN 02471477) currently marketed in Canada, according to Health Canada's Drug Product Database?",
            "expected": {
                "answer": st["status"],
                "status_date": st["history_date"],
                "sibling_din_02471469_status": sts["status"],
            },
            "headline": [],
            "tolerances": {},
            "answer_pattern": st["status"],
            "tolerance": f"Must say the status is {st['status']} (not marketed) since {st['history_date']}",
            "citations": [
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": st["status"],
                    "release_or_revision_date": st["history_date"],
                    "url": st_url,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": f"{p['brand_name']} - {p['descriptor']}",
                    "release_or_revision_date": p.get("last_update_date"),
                    "url": purl,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {sibling}",
                    "reference_period": TODAY,
                    "value": sts["status"],
                    "release_or_revision_date": sts["history_date"],
                    "url": sts_url,
                },
            ],
            "traps": [
                "The 1 mg Ozempic pen (DIN 02471469) is still Marketed; answering 'Ozempic is marketed' conflates the two DINs.",
                "Dormant is not Cancelled: the DIN remains valid but the product is not being sold.",
            ],
        }
    )

    # B-04 TRAP: Zantac 75 mg, cancelled -----------------------------------
    din = "02230287"
    p, purl = dpd_product(din)
    st, st_url = dpd_status(p["drug_code"])
    ais, aurl = dpd_ingredients(p["drug_code"])
    if not st["status"].startswith("Cancelled"):
        fail(f"Trap broken: DIN {din} status is {st['status']!r}, no longer cancelled")
    print(
        f"[B-04] DIN {din}: {p['brand_name']} / {p['company_name']} / {ais[0]['ingredient_name']} "
        f"{ais[0]['strength']} mg / {st['status']} {st['history_date']}",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-04",
            "category": "Health products",
            "group": "beyond",
            "eval_type": "refusal",
            "question": "Which company currently sells Zantac 75 mg (DIN 02230287) in Canada?",
            "expected": {
                "behaviour": (
                    f"Say that no company currently sells it: DIN {din} ({p['brand_name']}, "
                    f"{ais[0]['ingredient_name']} {ais[0]['strength']} mg) has status "
                    f"'{st['status']}' since {st['history_date']}. The last holder was "
                    f"{p['company_name']}."
                ),
                "status": st["status"],
                "status_date": st["history_date"],
                "last_holder": p["company_name"],
            },
            "headline": [],
            "tolerances": {},
            "tolerance": "Pass only if the answer says the product is cancelled / no longer marketed; naming the last holder alone as the current seller fails",
            "citations": [
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": st["status"],
                    "release_or_revision_date": st["history_date"],
                    "url": st_url,
                },
                {
                    "table_id": "Other",
                    "vector_id": f"DIN {din}",
                    "reference_period": TODAY,
                    "value": p["company_name"],
                    "release_or_revision_date": p.get("last_update_date"),
                    "url": purl,
                },
            ],
            "traps": [
                "The DPD still returns the product record and a company name for cancelled DINs; the status endpoint must be checked.",
                "Ranitidine products were withdrawn after the 2019 NDMA impurity findings; every Zantac DIN in the DPD is cancelled.",
            ],
        }
    )
    return qs


# --------------------------------------------------------------------------
# IRCC Express Entry
# --------------------------------------------------------------------------


def ee_rounds() -> tuple[list[dict], str]:
    page = _request("GET", EE_PAGE).text
    m = re.search(r"(/content/dam/ircc/documents/json/ee_rounds_\d+_en\.json)", page)
    if not m:
        fail("Could not find the ee_rounds_*_en.json URL on the Express Entry rounds page")
    url = "https://www.canada.ca" + m.group(1)
    data = get_json(url)
    rounds = data.get("rounds") or fail("EE JSON has no 'rounds'")
    out = []
    for r in rounds:
        try:
            out.append(
                {
                    "number": int(r["drawNumber"]),
                    "date": r["drawDate"],
                    "name": r["drawName"].strip(),
                    "size": int(str(r["drawSize"]).replace(",", "").strip()),
                    "crs": int(str(r["drawCRS"]).replace(",", "").strip()),
                }
            )
        except (KeyError, ValueError):
            continue  # a malformed row is skipped; needed rounds are checked below
    if len(out) < 400:
        fail(f"EE JSON parsed only {len(out)} rounds")
    return out, url


def ee_cite(r: dict, url: str, value: Any) -> dict:
    return {
        "table_id": "Other",
        "vector_id": f"Round {r['number']}",
        "reference_period": r["date"],
        "value": value,
        "release_or_revision_date": None,
        "url": url,
    }


def ee_questions() -> list[dict]:
    rounds, url = ee_rounds()
    by_num = {r["number"]: r for r in rounds}
    latest = max(rounds, key=lambda r: r["number"])
    qs: list[dict] = []

    # B-05 a named round ---------------------------------------------------
    r = by_num.get(449) or fail("Round 449 missing")
    if r["date"] != "2026-10-15" or "Canadian Experience Class" not in r["name"]:
        fail(f"Round 449 changed: {r}")
    print(f"[B-05] round 449: {r}", file=sys.stderr)
    qs.append(
        {
            "id": "B-05",
            "category": "Immigration",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "In Express Entry round #449, how many invitations to apply were issued and what was the minimum CRS score?",
            "expected": {"invitations": r["size"], "crs_cutoff": r["crs"]},
            "headline": ["invitations", "crs_cutoff"],
            "tolerances": {"invitations": 0, "crs_cutoff": 0},
            "tolerance": "Exact",
            "citations": [ee_cite(r, url, {"invitations": r["size"], "crs_cutoff": r["crs"]})],
            "traps": [
                f"Round 449 was a {r['name']} draw on {r['date']}; the PNP round two days earlier (#448) had a much higher cut-off.",
            ],
        }
    )

    # B-06 most recent Healthcare draw before a past date --------------------
    cutoff_date = "2026-09-30"
    hc = [
        x for x in rounds if x["date"] < cutoff_date and x["name"].lower().startswith("healthcare")
    ]
    if not hc:
        fail("No healthcare rounds before 2026-09-30")
    r = max(hc, key=lambda x: (x["date"], x["number"]))
    if r["number"] != 441:
        fail(
            f"Most recent healthcare round before {cutoff_date} is now #{r['number']}, expected #441"
        )
    print(f"[B-06] latest healthcare before {cutoff_date}: {r}", file=sys.stderr)
    qs.append(
        {
            "id": "B-06",
            "category": "Immigration",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "What was the CRS cut-off in the last Express Entry draw for healthcare and social services occupations held before the end of September 2026, and how many people were invited?",
            "expected": {
                "round_number": r["number"],
                "crs_cutoff": r["crs"],
                "invitations": r["size"],
            },
            "headline": ["crs_cutoff", "invitations"],
            "tolerances": {"round_number": 0, "crs_cutoff": 0, "invitations": 0},
            "tolerance": f"Exact; round #{r['number']} on {r['date']}",
            "citations": [ee_cite(r, url, {"invitations": r["size"], "crs_cutoff": r["crs"]})],
            "traps": [
                "The physicians-with-Canadian-work-experience draw (#440, 2026-09-03) is a separate category, not the healthcare and social services draw.",
                "An earlier healthcare draw (#422, 2026-06-25) had the same cut-off but 4,000 invitations.",
            ],
        }
    )

    # B-07 CEC invitations in September 2026 (aggregate) ---------------------
    cec = sorted(
        [
            x
            for x in rounds
            if x["date"].startswith("2026-09") and x["name"] == "Canadian Experience Class"
        ],
        key=lambda x: x["number"],
    )
    if len(cec) != 3:
        fail(f"Expected 3 CEC rounds in Sept 2026, got {[x['number'] for x in cec]}")
    total = sum(x["size"] for x in cec)
    print(
        f"[B-07] CEC Sept 2026: {[(x['number'], x['date'], x['size'], x['crs']) for x in cec]} total {total}",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-07",
            "category": "Immigration",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "How many Canadian Experience Class draws did IRCC hold in September 2026, and how many invitations did they issue in total?",
            "expected": {
                "cec_rounds": len(cec),
                "total_invitations": total,
                "lowest_crs_cutoff": min(x["crs"] for x in cec),
            },
            "headline": ["cec_rounds", "total_invitations"],
            "tolerances": {"cec_rounds": 0, "total_invitations": 0, "lowest_crs_cutoff": 0},
            "tolerance": "Exact",
            "citations": [
                ee_cite(x, url, {"invitations": x["size"], "crs_cutoff": x["crs"]}) for x in cec
            ],
            "traps": [
                "Count only the Canadian Experience Class draws, not the PNP, healthcare, physicians or senior-manager draws held the same month.",
            ],
        }
    )

    # B-08 REFUSAL: round not yet held ---------------------------------------
    asked = 460
    if asked in by_num or latest["number"] >= asked:
        fail(f"Refusal broken: round {asked} now exists (latest #{latest['number']})")
    print(
        f"[B-08] latest round #{latest['number']} on {latest['date']} ({latest['name']})",
        file=sys.stderr,
    )
    qs.append(
        {
            "id": "B-08",
            "category": "Immigration",
            "group": "beyond",
            "eval_type": "refusal",
            "question": "What was the CRS cut-off in Express Entry round #460?",
            "expected": {
                "behaviour": (
                    f"Decline: round #{asked} has not been held. The latest round is "
                    f"#{latest['number']} on {latest['date']} ({latest['name']}, "
                    f"{latest['size']:,} invitations, CRS {latest['crs']})."
                ),
                "latest_round": latest["number"],
                "latest_round_date": latest["date"],
            },
            "headline": [],
            "tolerances": {"latest_round": 0},
            "tolerance": f"Pass only if no cut-off is given for round #{asked}",
            "citations": [
                ee_cite(latest, url, {"invitations": latest["size"], "crs_cutoff": latest["crs"]})
            ],
            "traps": [
                "Do not give a projection or the latest round's cut-off as round 460's.",
            ],
        }
    )
    return qs


# --------------------------------------------------------------------------
# StatCan 2021 Census (WDS 98-10 tables)
# --------------------------------------------------------------------------


def _pad(coord: str) -> str:
    parts = coord.split(".")
    return ".".join(parts + ["0"] * (10 - len(parts)))


def wds_values(reqs: list[tuple[int, str]]) -> dict[tuple[int, str], dict]:
    body = [{"productId": pid, "coordinate": _pad(c), "latestN": 1} for pid, c in reqs]
    data = json.loads(_request("POST", WDS_COORD, json=body).content)
    out: dict[tuple[int, str], dict] = {}
    for item in data:  # response order is NOT request order; key by echo
        if item.get("status") != "SUCCESS":
            continue
        o = item["object"]
        pts = o.get("vectorDataPoint") or []
        if pts:
            out[(int(o["productId"]), o["coordinate"])] = pts[0]
    for pid, c in reqs:
        if (pid, _pad(c)) not in out:
            fail(f"WDS value missing for {pid} coordinate {_pad(c)}")
        pt = out[(pid, _pad(c))]
        if pt["refPer"] != "2021-01-01" or pt.get("value") is None:
            fail(f"WDS {pid} {c}: unexpected point {pt}")
    return {(pid, c): out[(pid, _pad(c))] for pid, c in reqs}


_meta_cache: dict[int, dict] = {}


def wds_member(pid: int, dim_pos: int, member_id: int) -> dict:
    if pid not in _meta_cache:
        _meta_cache[pid] = json.loads(
            _request("POST", f"{WDS}/getCubeMetadata", json=[{"productId": pid}]).content
        )[0]["object"]
    meta = _meta_cache[pid]
    dim = next(d for d in meta["dimension"] if d["dimensionPositionId"] == dim_pos)
    return next(m for m in dim["member"] if m["memberId"] == member_id)


def tbl(pid: int) -> str:
    s = str(pid)
    return f"{s[:2]}-{s[2:4]}-{s[4:]}-01"


def tv_url(pid: int) -> str:
    return f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid}01"


def census_cite(pid: int, coord: str, dguid: str, title: str, pt: dict) -> dict:
    return {
        "table_id": tbl(pid),
        "vector_id": dguid,
        "series_title": title,
        "coordinate": _pad(coord),
        "reference_period": "2021",
        "value": pt["value"],
        "release_or_revision_date": pt["releaseTime"],
        "url": WDS_COORD,
    }


def census_questions() -> list[dict]:
    # (pid, coord) -> meaning; member ids checked against metadata below
    HAL_AGE = (98100020, "12.1.128.1")  # Halifax (CMA); 2021; Median age; Total gender
    HAL_AVG = (98100020, "12.1.127.1")  # ... Average age
    CGY_MED = (
        98100061,
        "123.1.1.2",
    )  # Calgary (CMA); total hh type; total dwelling; median total hh income 2020
    CGY_AT = (98100061, "123.1.1.3")  # ... median after-tax hh income 2020
    TOR_TOT = (
        98100232,
        "2386.1.1.1.1.1",
    )  # Toronto (C) CSD 3520005; all; households; total age; total tenure
    TOR_OWN = (98100232, "2386.1.1.1.1.2")  # ... Owner
    TOR_RENT = (98100232, "2386.1.1.1.1.3")  # ... Renter
    EDM_POP = (98100005, "126.1")  # Edmonton (CMA); Population, 2021
    EDM_P16 = (98100005, "126.2")  # Population, 2016

    checks = [
        (98100020, 1, 12, "Halifax (CMA), N.S.", "205"),
        (98100020, 3, 128, "Median age", None),
        (98100061, 1, 123, "Calgary (CMA), Alta.", "825"),
        (98100061, 4, 2, "Median total income of households ($) (2020)", None),
        (98100232, 1, 2386, "Toronto", "3520005"),
        (98100232, 6, 3, "Renter", None),
        (98100005, 1, 126, "Edmonton", "835"),
        (98100005, 2, 1, "Population, 2021", None),
    ]
    for pid, pos, mid, name, code in checks:
        m = wds_member(pid, pos, mid)
        if m["memberNameEn"] != name or (code and m.get("classificationCode") != code):
            fail(
                f"{pid} dim {pos} member {mid} is now {m['memberNameEn']!r} ({m.get('classificationCode')})"
            )

    v = wds_values(
        [HAL_AGE, HAL_AVG, CGY_MED, CGY_AT, TOR_TOT, TOR_OWN, TOR_RENT, EDM_POP, EDM_P16]
    )
    for k, pt in v.items():
        print(f"[census] {k}: {pt['value']} ({pt['releaseTime']})", file=sys.stderr)

    qs: list[dict] = []

    # B-09 median age Halifax CMA -----------------------------------------
    med, avg = v[HAL_AGE]["value"], v[HAL_AVG]["value"]
    qs.append(
        {
            "id": "B-09",
            "category": "Census",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "What was the median age in the Halifax census metropolitan area in the 2021 Census?",
            "expected": {"median_age_years": med, "average_age_years": avg},
            "headline": ["median_age_years"],
            "tolerances": {"median_age_years": 0.1, "average_age_years": 0.1},
            "tolerance": "±0.1 year; Halifax CMA, total gender",
            "citations": [
                census_cite(
                    *HAL_AGE,
                    "2021S0503205",
                    "Halifax (CMA), N.S.;2021;Median age;Total - Gender",
                    v[HAL_AGE],
                ),
                census_cite(
                    *HAL_AVG,
                    "2021S0503205",
                    "Halifax (CMA), N.S.;2021;Average age;Total - Gender",
                    v[HAL_AVG],
                ),
            ],
            "traps": [
                "Median age, not average age (the average is higher).",
                "Halifax CMA and the Halifax Regional Municipality (CSD) are different geographies with different values.",
            ],
        }
    )

    # B-10 Calgary CMA median household total income 2020 -----------------
    inc, inc_at = v[CGY_MED]["value"], v[CGY_AT]["value"]
    qs.append(
        {
            "id": "B-10",
            "category": "Census",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "According to the 2021 Census, what was the median total income of households in the Calgary metropolitan area?",
            "expected": {
                "median_total_household_income_2020_dollars": inc,
                "median_after_tax_household_income_2020_dollars": inc_at,
            },
            "headline": ["median_total_household_income_2020_dollars"],
            "tolerances": {
                "median_total_household_income_2020_dollars": 0,
                "median_after_tax_household_income_2020_dollars": 0,
            },
            "tolerance": "Exact (rounded census figure); income year 2020; Calgary CMA",
            "citations": [
                census_cite(
                    *CGY_MED,
                    "2021S0503825",
                    "Calgary (CMA), Alta.;Total household type;Total dwelling type;Median total income of households ($) (2020)",
                    v[CGY_MED],
                ),
                census_cite(
                    *CGY_AT,
                    "2021S0503825",
                    "Calgary (CMA), Alta.;Total household type;Total dwelling type;Median after-tax income of households ($) (2020)",
                    v[CGY_AT],
                ),
            ],
            "traps": [
                "The 2021 Census reports income for calendar year 2020.",
                "Total income, not after-tax income; household, not individual or economic-family income.",
                "Calgary CMA, not the City of Calgary (CSD).",
            ],
        }
    )

    # B-11 renter share, City of Toronto ----------------------------------
    tot, own, rent = v[TOR_TOT]["value"], v[TOR_OWN]["value"], v[TOR_RENT]["value"]
    if abs(own + rent - tot) > 50:
        fail(f"Toronto tenure does not add up: {own}+{rent} vs {tot}")
    share = round(100 * rent / tot, 1)
    qs.append(
        {
            "id": "B-11",
            "category": "Census",
            "group": "beyond",
            "eval_type": "numeric",
            "question": "What share of households in the City of Toronto rented their home in 2021, according to the census?",
            "expected": {
                "renter_share_pct": share,
                "renter_households": rent,
                "total_households": tot,
            },
            "headline": ["renter_share_pct"],
            "tolerances": {
                "renter_share_pct": 0.2,
                "renter_households": 100,
                "total_households": 100,
            },
            "tolerance": "Share ±0.2 pp; counts ±100 (random rounding); City of Toronto CSD 3520005",
            "citations": [
                census_cite(
                    *TOR_RENT,
                    "2021A00053520005",
                    "Toronto (C) CSD;Renter;Number of private households",
                    v[TOR_RENT],
                ),
                census_cite(
                    *TOR_TOT,
                    "2021A00053520005",
                    "Toronto (C) CSD;Total - Tenure;Number of private households",
                    v[TOR_TOT],
                ),
            ],
            "traps": [
                "City of Toronto (CSD), not the Toronto CMA, where the renter share is much lower.",
                "Share of households, not of people.",
            ],
        }
    )

    # B-12 FLAG: 2026 census population asked, only 2021 published --------
    cubes = json.loads(_request("GET", f"{WDS}/getAllCubesListLite").content)
    census_cubes = [c for c in cubes if str(c["productId"]).startswith("98")]
    if not census_cubes:
        fail("No 98-series cubes in WDS cube list")
    newer = [c["productId"] for c in census_cubes if c["cubeEndDate"][:4] > "2021"]
    if newer:
        fail(
            f"Flag broken: census cubes now extend past 2021 ({newer[:5]}); 2026 Census may be out"
        )
    pop21, pop16 = v[EDM_POP]["value"], v[EDM_P16]["value"]
    qs.append(
        {
            "id": "B-12",
            "category": "Census",
            "group": "beyond",
            "eval_type": "flag",
            "question": "What is the population of the Edmonton metropolitan area in 2026, according to the census?",
            "expected": {
                "behaviour": (
                    "Flag that 2026 Census population counts have not been published (as of "
                    f"{TODAY} every 98-10 census table ends at 2021); give the 2021 Census count "
                    "for the Edmonton CMA and label it as 2021, not 2026."
                ),
                "population_2021": pop21,
                "population_2016": pop16,
            },
            "headline": [],
            "flag_years": ["2021", "2026"],
            "tolerances": {"population_2021": 0, "population_2016": 0},
            "tolerance": "Pass only if no figure is presented as a 2026 Census count",
            "citations": [
                census_cite(
                    *EDM_POP, "2021S0503835", "Edmonton (CMA);Population, 2021", v[EDM_POP]
                ),
                {
                    "table_id": "Other",
                    "vector_id": "getAllCubesListLite",
                    "reference_period": TODAY,
                    "value": f"{len(census_cubes)} 98-series cubes, none ending after 2021",
                    "release_or_revision_date": None,
                    "url": f"{WDS}/getAllCubesListLite",
                },
            ],
            "traps": [
                "Census Day 2026 has passed but its results are not yet released; a 2021 count or a demographic estimate must not be passed off as the 2026 Census.",
                "Edmonton CMA, not the City of Edmonton.",
            ],
        }
    )
    return qs


def questions() -> list[dict]:
    qs = hc_questions() + ee_questions() + census_questions()
    if [q["id"] for q in qs] != [f"B-{i:02d}" for i in range(1, 13)]:
        fail(f"Unexpected ids: {[q['id'] for q in qs]}")
    for q in qs:
        for k, val in q["expected"].items():
            if (
                isinstance(val, (int, float))
                and not isinstance(val, bool)
                and k not in q["tolerances"]
            ):
                fail(f"{q['id']}: numeric key {k} has no tolerance")
    return qs


if __name__ == "__main__":
    print(json.dumps(questions(), indent=2, ensure_ascii=False))

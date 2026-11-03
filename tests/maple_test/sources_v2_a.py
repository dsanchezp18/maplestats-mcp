"""Maple Test v2 -- answer key, agent A (12 questions: ECCC, World Bank, BIS).

Every expected value is fetched live from the source API at run time.
Independent of the maplestats_mcp package by design (no imports from it).

Run:  python v2_agent_a.py   -> prints the 12 question dicts as JSON.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
from datetime import date
from typing import NoReturn

import httpx

ECCC = "https://api.weather.gc.ca/collections"
WB = "https://api.worldbank.org/v2/country/CAN/indicator"
BIS = "https://stats.bis.org/api/v1/data"
TODAY = date(2026, 11, 3)

_client = httpx.Client(
    http2=True,
    timeout=httpx.Timeout(60.0, connect=20.0),
    follow_redirects=True,
    headers={"User-Agent": "maple-test-v2-answer-key"},
)


def fail(msg: str) -> NoReturn:
    raise SystemExit(f"[answer key] {msg}")


def get(url: str, params: dict | None = None, tries: int = 4) -> httpx.Response:
    last = None
    for i in range(tries):
        try:
            r = _client.get(url, params=params)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code in (400, 404):
                break
        except httpx.HTTPError as e:
            last = repr(e)
        time.sleep(2 * (i + 1))
    fail(f"request failed for {url} {params or ''}: {last}")


def full_url(url: str, params: dict) -> str:
    return str(httpx.URL(url, params=params))


def check(name: str, v, lo: float, hi: float):
    if v is None:
        fail(f"{name}: value missing")
    if not (lo <= float(v) <= hi):
        fail(f"{name}: value {v} outside sanity range [{lo}, {hi}]")
    print(f"  {name} = {v}", file=sys.stderr)
    return float(v)


# ---------------------------------------------------------------- ECCC
def eccc_items(coll: str, params: dict) -> tuple[list[dict], str]:
    p = {"f": "json", "limit": 100, **params}
    r = get(f"{ECCC}/{coll}/items", p)
    return [f["properties"] for f in r.json().get("features", [])], full_url(
        f"{ECCC}/{coll}/items", p
    )


def one(rows: list[dict], what: str) -> dict:
    if len(rows) != 1:
        fail(f"{what}: expected exactly 1 record, got {len(rows)}")
    return rows[0]


def q_eccc_monthly_toronto() -> dict:
    rows, url = eccc_items(
        "climate-monthly", {"CLIMATE_IDENTIFIER": "6158355", "LOCAL_YEAR": 2025, "LOCAL_MONTH": 7}
    )
    p = one(rows, "Toronto City 2025-07")
    if p["STATION_NAME"] != "TORONTO CITY":
        fail(f"unexpected station {p['STATION_NAME']}")
    if p["DAYS_WITH_VALID_MEAN_TEMP"] != 31 or p["DAYS_WITH_VALID_PRECIP"] != 31:
        fail("Toronto City July 2025 is not a complete month")
    t = round(check("toronto_jul2025_mean_temp", p["MEAN_TEMPERATURE"], 15, 32), 1)
    pr = round(check("toronto_jul2025_precip", p["TOTAL_PRECIPITATION"], 0, 400), 1)
    return {
        "category": "Climate",
        "eval_type": "numeric",
        "question": "What was the mean temperature at the Toronto City weather station in July 2025, and how much precipitation fell there that month?",
        "expected": {"mean_temp_jul_2025_c": t, "total_precip_jul_2025_mm": pr},
        "headline": ["mean_temp_jul_2025_c", "total_precip_jul_2025_mm"],
        "tolerances": {"mean_temp_jul_2025_c": 0.06, "total_precip_jul_2025_mm": 0.5},
        "tolerance": "Temperature ±0.1 °C (one decimal); precipitation ±0.5 mm",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "ECCC climate-monthly 6158355 (TORONTO CITY, STN_ID 31688)",
                "reference_period": "2025-07",
                "value": {
                    "MEAN_TEMPERATURE": p["MEAN_TEMPERATURE"],
                    "TOTAL_PRECIPITATION": p["TOTAL_PRECIPITATION"],
                },
                "release_or_revision_date": p.get("LAST_UPDATED"),
                "url": url,
            }
        ],
        "traps": [
            "Toronto City (downtown, 6158355) is not Toronto Pearson / Toronto Intl A; the airport values differ.",
            "The 1991-2020 normal is not the July 2025 observation.",
        ],
    }


def q_eccc_daily_ottawa() -> dict:
    rows, url = eccc_items(
        "climate-daily", {"CLIMATE_IDENTIFIER": "6105976", "LOCAL_DATE": "2025-06-23"}
    )
    p = one(rows, "Ottawa CDA 2025-06-23")
    if p["STATION_NAME"] != "OTTAWA CDA":
        fail(f"unexpected station {p['STATION_NAME']}")
    tx = round(check("ottawa_cda_max", p["MAX_TEMPERATURE"], 20, 45), 1)
    tn = round(check("ottawa_cda_min", p["MIN_TEMPERATURE"], 5, 30), 1)
    return {
        "category": "Climate",
        "eval_type": "numeric",
        "question": "What were the maximum and minimum temperatures recorded at the Ottawa CDA weather station on June 23, 2025?",
        "expected": {"max_temp_c": tx, "min_temp_c": tn},
        "headline": ["max_temp_c", "min_temp_c"],
        "tolerances": {"max_temp_c": 0.05, "min_temp_c": 0.05},
        "tolerance": "±0.05 °C (values are published to one decimal)",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "ECCC climate-daily 6105976 (OTTAWA CDA, STN_ID 4333)",
                "reference_period": "2025-06-23",
                "value": {
                    "MAX_TEMPERATURE": p["MAX_TEMPERATURE"],
                    "MIN_TEMPERATURE": p["MIN_TEMPERATURE"],
                },
                "release_or_revision_date": None,
                "url": url,
            }
        ],
        "traps": [
            "Ottawa CDA (6105976) is not the airport: Ottawa Intl A (6106001) recorded a different maximum that day, and the older Ottawa Macdonald-Cartier Int'l A (6106000) record is empty."
        ],
    }


def q_eccc_hydro_fraser() -> dict:
    rows, url = eccc_items(
        "hydrometric-daily-mean", {"STATION_NUMBER": "08MF005", "datetime": "2024-06-16"}
    )
    p = one(rows, "Fraser at Hope 2024-06-16")
    if p["STATION_NAME"] != "FRASER RIVER AT HOPE" or p["DATE"] != "2024-06-16":
        fail(f"unexpected record {p}")
    q = check("fraser_hope_discharge", p["DISCHARGE"], 500, 15000)
    return {
        "category": "Hydrometric",
        "eval_type": "numeric",
        "question": "What was the daily mean discharge of the Fraser River at Hope (station 08MF005) on June 16, 2024?",
        "expected": {"discharge_m3s": q},
        "headline": ["discharge_m3s"],
        "tolerances": {"discharge_m3s": 10.0},
        "tolerance": "±10 m³/s (published to three significant figures)",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "ECCC hydrometric-daily-mean 08MF005 (FRASER RIVER AT HOPE)",
                "reference_period": "2024-06-16",
                "value": q,
                "release_or_revision_date": None,
                "url": url,
            }
        ],
        "traps": [
            "Discharge (m³/s) is not water level (m).",
            "A real-time provisional reading is not the archived daily mean.",
        ],
    }


def q_eccc_trap_pearson() -> dict:
    srows, surl = eccc_items("climate-stations", {"CLIMATE_IDENTIFIER": "6158733"})
    s = one(srows, "station 6158733")
    last = s["LAST_DATE"][:10]
    if last >= "2024-07-01" or (s.get("MLY_LAST_DATE") or "")[:10] >= "2024-07-01":
        fail(f"trap no longer holds: 6158733 LAST_DATE={last}")
    mrows, murl = eccc_items(
        "climate-monthly", {"CLIMATE_IDENTIFIER": "6158733", "LOCAL_YEAR": 2024}
    )
    if mrows:
        fail("trap no longer holds: 6158733 has 2024 monthly data")
    rows, url = eccc_items(
        "climate-monthly", {"CLIMATE_IDENTIFIER": "6158731", "LOCAL_YEAR": 2024, "LOCAL_MONTH": 7}
    )
    p = one(rows, "Toronto Intl A 2024-07")
    if p["STATION_NAME"] != "TORONTO INTL A" or p["DAYS_WITH_VALID_PRECIP"] != 31:
        fail(
            f"successor record unexpected: {p['STATION_NAME']}, {p['DAYS_WITH_VALID_PRECIP']} days"
        )
    pr = round(check("toronto_intl_a_jul2024_precip", p["TOTAL_PRECIPITATION"], 0, 500), 1)
    return {
        "category": "Climate",
        "eval_type": "flag",
        "question": "How much precipitation was recorded in July 2024 at the Toronto Lester B. Pearson Int'l A weather station (climate ID 6158733)?",
        "expected": {
            "behaviour": f"Flag that station 6158733 (Toronto Lester B. Pearson Int'l A) stopped reporting on {last}, so it has no July 2024 value; "
            "point to the successor station at the same airport, Toronto Intl A (climate ID 6158731), and give its figure.",
            "station_last_date": last,
            "successor_precip_jul_2024_mm": pr,
        },
        "headline": [],
        "tolerances": {"successor_precip_jul_2024_mm": 0.5},
        "tolerance": "Pass only if the closure is stated (or the successor ID is named); successor value ±0.5 mm",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "ECCC climate-stations 6158733 (STN_ID 5097)",
                "reference_period": "station record",
                "value": {"LAST_DATE": s["LAST_DATE"], "MLY_LAST_DATE": s.get("MLY_LAST_DATE")},
                "release_or_revision_date": None,
                "url": surl,
            },
            {
                "table_id": "Other",
                "vector_id": "ECCC climate-monthly 6158733",
                "reference_period": "2024",
                "value": None,
                "release_or_revision_date": None,
                "url": murl,
            },
            {
                "table_id": "Other",
                "vector_id": "ECCC climate-monthly 6158731 (TORONTO INTL A, STN_ID 51459)",
                "reference_period": "2024-07",
                "value": p["TOTAL_PRECIPITATION"],
                "release_or_revision_date": p.get("LAST_UPDATED"),
                "url": url,
            },
        ],
        "traps": [
            "The old Pearson station ID closed in June 2013; any July 2024 number attributed to it is invented or taken silently from another station.",
            "July 2024 includes the July 16 Toronto flood; Toronto City downtown is a different station.",
        ],
    }


# ---------------------------------------------------------------- World Bank
def wb_series(ind: str, years: str = "2018:2026") -> tuple[dict, str, str]:
    p = {"format": "json", "date": years, "per_page": 100}
    r = get(f"{WB}/{ind}", p)
    js = r.json()
    if not isinstance(js, list) or len(js) < 2 or js[1] is None:
        fail(f"World Bank {ind}: unexpected payload {str(js)[:200]}")
    rows = js[1]
    if any(x["indicator"]["id"] != ind or x["countryiso3code"] != "CAN" for x in rows):
        fail(f"World Bank {ind}: wrong indicator/country in payload")
    return (
        {x["date"]: x["value"] for x in rows},
        js[0].get("lastupdated"),
        full_url(f"{WB}/{ind}", p),
    )


def wb_cite(ind: str, year: str, value, upd: str, url: str) -> dict:
    return {
        "table_id": "Other",
        "vector_id": f"WDI {ind} (CAN)",
        "reference_period": year,
        "value": value,
        "release_or_revision_date": upd,
        "url": url,
    }


def q_wb_gdppc() -> dict:
    s, upd, url = wb_series("NY.GDP.PCAP.CD")
    v = check("wb_gdppc_2023", s.get("2023"), 40000, 70000)
    return {
        "category": "International",
        "eval_type": "numeric",
        "question": "According to the World Bank, what was Canada's GDP per capita in current US dollars in 2023?",
        "expected": {"gdp_per_capita_2023_usd": round(v)},
        "headline": ["gdp_per_capita_2023_usd"],
        "tolerances": {"gdp_per_capita_2023_usd": round(0.005 * v)},
        "tolerance": "±0.5% (WDI vintage of the date recorded; WDI revises back years)",
        "citations": [wb_cite("NY.GDP.PCAP.CD", "2023", v, upd, url)],
        "traps": [
            "Current US$, not constant 2015 US$ or PPP.",
            "Not GDP per capita in Canadian dollars from Statistics Canada.",
        ],
    }


def q_wb_pop() -> dict:
    s, upd, url = wb_series("SP.POP.TOTL")
    v = check("wb_pop_2023", s.get("2023"), 35e6, 45e6)
    return {
        "category": "International",
        "eval_type": "numeric",
        "question": "What was Canada's total population in 2023 according to the World Bank's World Development Indicators?",
        "expected": {"population_2023": int(v)},
        "headline": ["population_2023"],
        "tolerances": {"population_2023": 50000},
        "tolerance": "±50,000 people (accept '40.0 million' or '40.05 million')",
        "citations": [wb_cite("SP.POP.TOTL", "2023", v, upd, url)],
        "traps": [
            "WDI midyear population, not Statistics Canada's July 1 or quarterly estimate (which can differ slightly).",
            "Not the 2021 Census count.",
        ],
    }


def q_wb_co2() -> dict:
    s, upd, url = wb_series("EN.GHG.CO2.MT.CE.AR5")
    v = check("wb_co2_2022", s.get("2022"), 400, 700)
    return {
        "category": "International",
        "eval_type": "numeric",
        "question": "What were Canada's total CO2 emissions, excluding land use (LULUCF), in 2022 according to the World Bank?",
        "expected": {"co2_2022_mt": round(v, 1)},
        "headline": ["co2_2022_mt"],
        "tolerances": {"co2_2022_mt": 1.0},
        "tolerance": "±1 Mt CO2e",
        "citations": [wb_cite("EN.GHG.CO2.MT.CE.AR5", "2022", v, upd, url)],
        "traps": [
            "CO2 only, not total greenhouse gases (Canada's National Inventory total GHG is about 700 Mt).",
            "Excluding LULUCF; per-capita figure (t/person) is a different indicator.",
        ],
    }


def q_wb_refusal_lifeexp() -> dict:
    s, upd, url = wb_series("SP.DYN.LE00.IN")
    if s.get("2025") is not None:
        fail(f"refusal no longer holds: SP.DYN.LE00.IN 2025 = {s['2025']}")
    years = sorted(y for y, v in s.items() if v is not None)
    latest = years[-1]
    lv = check("wb_lifeexp_latest", s[latest], 75, 90)
    return {
        "category": "Unanswerable",
        "eval_type": "refusal",
        "question": "What was life expectancy at birth in Canada in 2025, according to the World Bank?",
        "expected": {
            "behaviour": f"Decline: the WDI has no 2025 value for Canada's life expectancy at birth (SP.DYN.LE00.IN) as of {upd}. "
            f"The latest year is {latest}; offering that figure, clearly labelled, is fine.",
            "latest_year": latest,
            "latest_value_years": round(lv, 1),
        },
        "headline": [],
        "tolerances": {"latest_value_years": 0.1},
        "tolerance": "Pass only if no 2025 figure is given",
        "citations": [
            wb_cite("SP.DYN.LE00.IN", "2025", None, upd, url),
            wb_cite("SP.DYN.LE00.IN", latest, s[latest], upd, url),
        ],
        "traps": [
            "A Statistics Canada or UN projection is not a WDI value.",
            f"The {latest} value must not be passed off as 2025.",
        ],
    }


# ---------------------------------------------------------------- BIS
def bis(key: str, start: str, end: str) -> tuple[list[dict], str]:
    p = {"startPeriod": start, "endPeriod": end, "format": "csv"}
    url = f"{BIS}/{key}"
    r = get(url, p)
    return list(csv.DictReader(io.StringIO(r.text))), full_url(url, p)


def bis_obs(rows: list[dict], period: str, what: str, **dims) -> float:
    hit = [
        r
        for r in rows
        if r["TIME_PERIOD"] == period and all(r.get(k) == v for k, v in dims.items())
    ]
    if len(hit) != 1 or hit[0]["OBS_VALUE"] in ("", "NaN"):
        fail(f"BIS {what} {period}: expected one observation, got {len(hit)}")
    return float(hit[0]["OBS_VALUE"])


def q_bis_policy() -> dict:
    rows, url = bis("WS_CBPOL/D.CA", "2024-07-15", "2024-07-31")
    a = check(
        "boc_rate_2024-07-15",
        bis_obs(rows, "2024-07-15", "CBPOL D.CA", FREQ="D", REF_AREA="CA"),
        0,
        10,
    )
    b = check(
        "boc_rate_2024-07-31",
        bis_obs(rows, "2024-07-31", "CBPOL D.CA", FREQ="D", REF_AREA="CA"),
        0,
        10,
    )
    if a == b:
        fail("policy-rate question expects a cut between the two dates")
    return {
        "category": "Finance",
        "eval_type": "numeric",
        "question": "What was the Bank of Canada's policy interest rate on July 15, 2024, and what was it at the end of July 2024?",
        "expected": {"rate_2024_07_15_pct": a, "rate_2024_07_31_pct": b},
        "headline": ["rate_2024_07_15_pct", "rate_2024_07_31_pct"],
        "tolerances": {"rate_2024_07_15_pct": 0.01, "rate_2024_07_31_pct": 0.01},
        "tolerance": "Exact to the quarter point",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "BIS WS_CBPOL D.CA (target for the overnight rate, daily)",
                "reference_period": d,
                "value": v,
                "release_or_revision_date": None,
                "url": url,
            }
            for d, v in (("2024-07-15", a), ("2024-07-31", b))
        ],
        "traps": [
            "The Bank cut by 25 bp on July 24, 2024, so the two dates differ.",
            "The overnight target, not the bank rate (25 bp higher) or the prime rate.",
        ],
    }


def q_bis_spp() -> dict:
    rows, url = bis("WS_SPP/Q.CA.N.771+628", "2024-Q4", "2025-Q4")
    yoy = check(
        "ca_spp_nominal_yoy_2025Q4",
        bis_obs(rows, "2025-Q4", "SPP N.771", VALUE="N", UNIT_MEASURE="771"),
        -30,
        30,
    )
    i4 = bis_obs(rows, "2025-Q4", "SPP N.628", VALUE="N", UNIT_MEASURE="628")
    i3 = bis_obs(rows, "2024-Q4", "SPP N.628", VALUE="N", UNIT_MEASURE="628")
    if abs((i4 / i3 - 1) * 100 - yoy) > 0.05:
        fail(f"SPP inconsistency: index-implied {(i4 / i3 - 1) * 100:.3f} vs published {yoy}")
    return {
        "category": "Finance",
        "eval_type": "numeric",
        "question": "By how much did Canadian residential property prices change, year over year in nominal terms, in the fourth quarter of 2025 (BIS selected property price series)?",
        "expected": {"nominal_yoy_2025q4_pct": round(yoy, 1)},
        "headline": ["nominal_yoy_2025q4_pct"],
        "tolerances": {"nominal_yoy_2025q4_pct": 0.1},
        "tolerance": "±0.1 percentage point; sign must be negative",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "BIS WS_SPP Q.CA.N.771 (nominal, year-on-year % change)",
                "reference_period": "2025-Q4",
                "value": yoy,
                "release_or_revision_date": None,
                "url": url,
            },
            {
                "table_id": "Other",
                "vector_id": "BIS WS_SPP Q.CA.N.628 (nominal index, 2010=100)",
                "reference_period": "2024-Q4/2025-Q4",
                "value": {"2024-Q4": i3, "2025-Q4": i4},
                "release_or_revision_date": None,
                "url": url,
            },
        ],
        "traps": [
            "Nominal, not the real (CPI-deflated) series, which fell more.",
            "Year over year, not quarter over quarter.",
        ],
    }


def q_bis_dsr() -> dict:
    rows, url = bis("WS_DSR/Q.CA.H", "2024-Q4", "2024-Q4")
    v = check("ca_dsr_h_2024Q4", bis_obs(rows, "2024-Q4", "DSR Q.CA.H", DSR_BORROWERS="H"), 5, 25)
    return {
        "category": "Finance",
        "eval_type": "numeric",
        "question": "What was the debt service ratio of Canadian households in the fourth quarter of 2024, as published by the BIS?",
        "expected": {"household_dsr_2024q4_pct": v},
        "headline": ["household_dsr_2024q4_pct"],
        "tolerances": {"household_dsr_2024q4_pct": 0.05},
        "tolerance": "±0.05 (published to one decimal, % of income)",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": "BIS WS_DSR Q.CA.H (households and NPISHs)",
                "reference_period": "2024-Q4",
                "value": v,
                "release_or_revision_date": None,
                "url": url,
            }
        ],
        "traps": [
            "Households and NPISHs (H), not the private non-financial sector (P), which is about 25%.",
            "BIS DSR is not Statistics Canada's household debt service ratio (different definition).",
        ],
    }


def q_bis_compare() -> dict:
    rows, url = bis("WS_DSR/Q.CA+US.H", "2025-Q4", "2025-Q4")
    ca = check(
        "ca_dsr_h_2025Q4",
        bis_obs(rows, "2025-Q4", "DSR CA", BORROWERS_CTY="CA", DSR_BORROWERS="H"),
        5,
        25,
    )
    us = check(
        "us_dsr_h_2025Q4",
        bis_obs(rows, "2025-Q4", "DSR US", BORROWERS_CTY="US", DSR_BORROWERS="H"),
        3,
        20,
    )
    if ca == us:
        fail("comparison tie")
    win = "Canada" if ca > us else "United States"
    return {
        "category": "Finance",
        "eval_type": "comparison",
        "question": "Which had the higher household debt service ratio in the fourth quarter of 2025, Canada or the United States, and what were the two ratios?",
        "expected": {"answer": win, "canada_dsr_2025q4_pct": ca, "us_dsr_2025q4_pct": us},
        "headline": ["canada_dsr_2025q4_pct", "us_dsr_2025q4_pct"],
        "tolerances": {"canada_dsr_2025q4_pct": 0.05, "us_dsr_2025q4_pct": 0.05},
        "answer_pattern": win,
        "tolerance": "Correct country; ratios ±0.05",
        "citations": [
            {
                "table_id": "Other",
                "vector_id": f"BIS WS_DSR Q.{c}.H (households and NPISHs)",
                "reference_period": "2025-Q4",
                "value": v,
                "release_or_revision_date": None,
                "url": url,
            }
            for c, v in (("CA", ca), ("US", us))
        ],
        "traps": [
            "Use the BIS series for both countries (same methodology), not the Federal Reserve's own DSR.",
            "Households, not the private non-financial sector.",
        ],
    }


# ---------------------------------------------------------------- assemble
BUILDERS = [
    q_eccc_monthly_toronto,
    q_eccc_daily_ottawa,
    q_eccc_hydro_fraser,
    q_eccc_trap_pearson,
    q_wb_gdppc,
    q_wb_pop,
    q_wb_co2,
    q_wb_refusal_lifeexp,
    q_bis_policy,
    q_bis_spp,
    q_bis_dsr,
    q_bis_compare,
]


def questions() -> list[dict]:
    out = []
    for i, b in enumerate(BUILDERS, 1):
        print(f"A-{i:02d} {b.__name__}", file=sys.stderr)
        q = b()
        ordered = {
            "id": f"A-{i:02d}",
            "category": q.pop("category"),
            "group": "beyond",
            "eval_type": q.pop("eval_type"),
        }
        ordered.update(q)
        for c in ordered["citations"]:
            c.setdefault("retrieved_on", TODAY.isoformat())
        num = {
            k
            for k, v in ordered["expected"].items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        if num != set(ordered["tolerances"]):
            fail(
                f"{ordered['id']}: tolerances keys {set(ordered['tolerances'])} != numeric expected keys {num}"
            )
        out.append(ordered)
    if len(out) != 12:
        fail(f"expected 12 questions, built {len(out)}")
    return out


if __name__ == "__main__":
    print(json.dumps(questions(), indent=2, ensure_ascii=False))

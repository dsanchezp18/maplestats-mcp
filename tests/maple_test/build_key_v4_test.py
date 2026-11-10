"""Build the key for v4's fresh test set: 25 questions no server has answered.

v4's first test set (README, "Version 4") came from v1 to v3, so it was in-sample for
MapleStats. Rotation rule 3 replaces it: these 25 questions were written and keyed on
2026-11-09, before MapleStats or any other server was asked them, and the old test
questions moved to dev (`build_key_v4.MOVED_TO_DEV`). None repeats a v1 to v3 question or
a near-duplicate of one; each is stratified like the set it replaces (source by kind of
answer: README, "The questions").

Every value is read here, with httpx, from the publisher's own API or page, never
through MapleStats:

- Statistics Canada: IMDB survey pages (www23); the Web Data Service and The Daily's
  release schedule (www150) for tables and release dates;
- Bank of Canada: Valet;
- CMHC: its survey methodology page; its rental vacancy rates as StatCan publishes them
  (table 34-10-0127, source CMHC), as v2's C-15 read CMHC's starts;
- Environment and Climate Change Canada: the MSC GeoMet API (climate normals and
  stations);
- CKAN Action APIs: open.canada.ca, the BC Data Catalogue, Données Québec, Toronto;
- the World Bank's indicator API and the BIS statistics API.

www150 blocks this machine after heavy use (AGENTS.md; again on 2026-11-09), so the key
is built in two parts that can be rebuilt apart: `open` (everything else) and `statcan`
(WDS and the release schedule, one request at a time, with a pause; a 403 or 429 stops
the build instead of retrying).

    uv run python -m tests.maple_test.build_key_v4_test                # both parts
    uv run python -m tests.maple_test.build_key_v4_test --part open    # one part, merged
    uv run python -m tests.maple_test.build_key_v4_test --check        # report drift

Ids are fixed (N-01 to N-25), not numbered by list order, so a part rebuilt alone keeps
them.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any, NoReturn

import httpx

from tests.maple_test.build_key import drift

HERE = Path(__file__).resolve().parent
KEY = HERE / "maple_test_v4_test.json"

# http2=True: StatCan resets a TLS handshake that offers only HTTP/1.1 (AGENTS.md).
_client = httpx.Client(
    http2=True,
    timeout=httpx.Timeout(120.0, connect=20.0),
    follow_redirects=True,
    headers={"User-Agent": "maplestats-mcp Maple Test key builder"},
)

IMDB = "https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&SDDS={}"
WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
SCHEDULE = (
    "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/schedule-previous_releases-eng.json"
)
DAILY = "https://www150.statcan.gc.ca/n1"
VALET = "https://www.bankofcanada.ca/valet/"
CMHC_STARTS = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-research/surveys/methods/methodologies-starts-completions-market-absorption-survey"
)
GEOMET = "https://api.weather.gc.ca/collections/"
FED = "https://open.canada.ca/data/api/3/action/"
BC = "https://catalogue.data.gov.bc.ca/api/3/action/"
QC = "https://www.donneesquebec.ca/recherche/api/3/action/"
TOR = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/"
WB = "https://api.worldbank.org/v2/"
BIS = "https://stats.bis.org/api/v1/data/"

NOT_NEAR = r"(?:\bno\b|\bnot\b|n't|n’t|\bnone\b|\bneither\b|\bnor\b|unavailable|without)"


def fail(msg: str) -> NoReturn:
    raise SystemExit(f"build_key_v4_test: {msg}")


def get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """One GET, with a pause after it; a refusal (403/429) stops the build, no retries."""
    response = _client.get(url, params=params)
    if response.status_code in (403, 429):
        fail(f"{url} answered HTTP {response.status_code}; not retrying")
    response.raise_for_status()
    time.sleep(1.5)
    return response


def post(url: str, body: Any) -> Any:
    response = _client.post(url, json=body)
    if response.status_code in (403, 429):
        fail(f"{url} answered HTTP {response.status_code}; not retrying")
    response.raise_for_status()
    time.sleep(1.5)
    return response.json()


def page(url: str) -> str:
    """A documentation page's visible text, whitespace collapsed."""
    html = get(url).text
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def find(text: str, pattern: str, where: str) -> re.Match[str]:
    match = re.search(pattern, text)
    if match is None:
        fail(f"{where}: the passage {pattern!r} is no longer on the page")
    return match


def ckan(base: str, action: str, **params: Any) -> Any:
    body = get(base + action, params=params).json()
    if not body.get("success"):
        fail(f"{base}{action} {params}: {body.get('error')}")
    return body["result"]


def cite(
    source: str,
    item: str | None,
    title: str,
    value: Any,
    url: str,
    period: str | None = None,
    released: str | None = None,
) -> dict[str, Any]:
    return {
        "table_id": source,
        "vector_id": item,
        "series_title": title,
        "reference_period": period,
        "value": value,
        "release_or_revision_date": released,
        "url": url,
    }


def _q(**fields: Any) -> dict[str, Any]:
    fields.setdefault("tolerances", {})
    fields.setdefault("headline", [])
    fields.setdefault("traps", [])
    return fields


def pct(new: float, old: float) -> float:
    return round(100 * (new - old) / old, 1)


# Open part: every source but www150 ------------------------------------------------


def statcan_docs() -> list[dict[str, Any]]:
    seph_url = IMDB.format(2612)
    seph = page(seph_url)
    pd7 = find(seph, r"Canada Revenue Agency Payroll Deduction \(PD7\)", "SEPH")
    bps = find(
        seph,
        r"Business Payrolls Survey \(BPS\), which collects data from a sample of "
        r"([\d,]+) businesses",
        "SEPH",
    )
    msm_url = IMDB.format(2101)
    msm = page(msm_url)
    find(msm, r"Responding to this survey is mandatory", "MSM")
    industries = find(
        msm,
        r"classified to the manufacturing sector \(by NAICS\), which are "
        r"categorized into over (\d+) industries",
        "MSM",
    )
    return [
        _q(
            id="N-07",
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="Where does Statistics Canada's Survey of Employment, Payrolls and Hours "
            "(SEPH) get its monthly counts of employees and payrolls, what is the survey part "
            "of it called, and about how many businesses does that survey sample?",
            expected={
                "administrative": pd7.group(0),
                "survey": "Business Payrolls Survey (BPS)",
                "bps_sample_businesses": int(bps.group(1).replace(",", "")),
            },
            facts={
                "cra": r"Canada Revenue Agency|\bCRA\b",
                "payroll_deductions": r"payroll deduction|PD7",
                "bps": r"Business Payrolls? Survey|\bBPS\b",
                "sample": r"15[, ]?000|15 thousand",
            },
            headline=["payroll_deductions", "bps"],
            tolerance="A census of payroll deductions (PD7) from the Canada Revenue Agency, "
            "combined with the Business Payrolls Survey (a sample of about "
            f"{bps.group(1)} businesses).",
            grading={
                "correct": "CRA payroll deduction (PD7) records and the Business Payrolls Survey.",
                "partial": "One of the two sources.",
                "referral": "No sources named, only a link to the survey page.",
            },
            citations=[cite("Other", "IMDB 2612", "SEPH data sources", pd7.group(0), seph_url)],
            traps=["SEPH is not a household survey: the LFS is; SEPH counts jobs, not people."],
        ),
        _q(
            id="N-08",
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="Which establishments make up the target population of Statistics "
            "Canada's Monthly Survey of Manufacturing, which list are they drawn from, and into "
            "how many industries are they categorized?",
            expected={
                "target_population": "statistical establishments on the Business Register "
                "classified to the manufacturing sector (NAICS)",
                "industries_over": int(industries.group(1)),
            },
            facts={
                "manufacturing": r"manufactur",
                "register": r"Business Register|\bBR\b",
                "industries": r"\b156\b",
            },
            headline=["register", "industries"],
            tolerance="Mandatory; all statistical establishments on StatCan's Business Register "
            f"classified to manufacturing (NAICS), over {industries.group(1)} industries.",
            grading={
                "correct": "Manufacturing establishments on the Business Register, over 156 "
                "industries.",
                "partial": "Two of the three.",
                "referral": "No answer, only a link to the survey page.",
            },
            citations=[
                cite("Other", "IMDB 2101", "MSM data sources", "mandatory", msm_url),
                cite("Other", "IMDB 2101", "MSM target population", industries.group(0), msm_url),
            ],
        ),
    ]


def valet_obs(series: str, start: str, end: str) -> tuple[dict[str, str], dict[str, Any], str]:
    url = f"{VALET}observations/{series}/json"
    body = get(url, params={"start_date": start, "end_date": end}).json()
    obs = {o["d"]: o[series]["v"] for o in body["observations"] if series in o}
    return obs, body["seriesDetail"][series], f"{url}?start_date={start}&end_date={end}"


def bank_of_canada() -> list[dict[str, Any]]:
    out = []
    obs, detail, url = valet_obs("CEER_BROADNM", "2026-09-01", "2026-10-01")
    if "2026-10-01" not in obs:
        fail("CEER_BROADNM has no October 2026 value")
    oct_value, sep_value = float(obs["2026-10-01"]), float(obs["2026-09-01"])
    out.append(
        _q(
            id="N-12",
            category="Markets",
            group="boc",
            eval_type="comparison",
            answer_regex=(
                r"\b(?:lower|fell|declin\w*|decreas\w*|dipped|down)\b"
                if oct_value < sep_value
                else r"\b(?:higher|rose|increas\w*|up)\b"
            ),
            question="What was the Bank of Canada's monthly nominal Canadian effective exchange "
            "rate (CEER) index for October 2026, and was it higher or lower than in September "
            "2026?",
            expected={"ceer_oct_2026": oct_value},
            reference={"ceer_sep_2026": sep_value},
            headline=["ceer_oct_2026"],
            tolerances={"ceer_oct_2026": 0.005},
            tolerance=f"{oct_value} (Valet CEER_BROADNM, October 2026), "
            f"{'lower' if oct_value < sep_value else 'higher'} than September's {sep_value}.",
            grading={
                "correct": f"{oct_value}, and {'lower' if oct_value < sep_value else 'higher'} "
                "than September.",
                "partial": "The October value without the comparison, or the comparison with a "
                "September value off.",
                "referral": "No value, only a link to the Bank's exchange-rate pages.",
            },
            citations=[
                cite("Valet", "CEER_BROADNM", detail["label"], oct_value, url, "2026-10"),
                cite("Valet", "CEER_BROADNM", detail["label"], sep_value, url, "2026-09"),
            ],
            traps=[
                (
                    "The daily nominal CEER (CEER_BROADN) and the real CEER (CEER_BROADM) are other "
                    "series."
                ),
                (
                    "Valet's description says base year 1999 while its unit says 2010 = 100: the "
                    "index value is the answer either way."
                ),
            ],
        )
    )
    obs, detail, url = valet_obs("FXJPYCAD", "2026-10-01", "2026-10-30")
    first, last = float(obs["2026-10-01"]), float(obs["2026-10-30"])
    if first == last:
        fail("FXJPYCAD unchanged over October: no call to make")
    cad = "weakened" if last > first else "strengthened"
    out.append(
        _q(
            id="N-13",
            category="Markets",
            group="boc",
            eval_type="comparison",
            answer_regex=(
                r"(?:dollar|CAD|loonie)[^.]{0,60}\b(?:weaken\w*|depreciat\w*|fell|"
                r"lost)\b|\b(?:weaken\w*|depreciat\w*)\b[^.]{0,40}(?:dollar|CAD)"
                if cad == "weakened"
                else r"(?:dollar|CAD|loonie)[^.]{0,60}\b(?:strengthen\w*|appreciat\w*|"
                r"rose|gained)\b|\b(?:strengthen\w*|appreciat\w*)\b[^.]{0,40}"
                r"(?:dollar|CAD)"
            ),
            alternatives=[
                {
                    "label": "yen per Canadian dollar",
                    "expected": {
                        "yen_per_cad_2026_10_01": round(1 / first, 2),
                        "yen_per_cad_2026_10_30": round(1 / last, 2),
                    },
                }
            ],
            question="Between October 1 and October 30, 2026, did the Canadian dollar "
            "strengthen or weaken against the Japanese yen, by the Bank of Canada's daily "
            "exchange rates? Give the rate on both days.",
            expected={"jpycad_2026_10_01": first, "jpycad_2026_10_30": last},
            headline=["jpycad_2026_10_01", "jpycad_2026_10_30"],
            tolerances={
                "jpycad_2026_10_01": 0.0000005,
                "jpycad_2026_10_30": 0.0000005,
                "yen_per_cad_2026_10_01": 0.06,
                "yen_per_cad_2026_10_30": 0.06,
            },
            tolerance=f"{first} and {last} CAD per yen (FXJPYCAD): the yen bought "
            f"{'more' if last > first else 'fewer'} Canadian dollars, so the dollar {cad}.",
            grading={
                "correct": f"Both rates and the call: the Canadian dollar {cad}.",
                "partial": "Both rates with no call, or the call with one rate.",
                "hallucinated": "The opposite call, or rates from another source given as the "
                "Bank's.",
                "referral": "No rates, only a link to the Bank's exchange-rate page.",
            },
            citations=[
                cite("Valet", "FXJPYCAD", detail["label"], first, url, "2026-10-01"),
                cite("Valet", "FXJPYCAD", detail["label"], last, url, "2026-10-30"),
            ],
            traps=[
                (
                    "FXJPYCAD is Canadian dollars per yen: a higher value means a weaker Canadian "
                    "dollar."
                ),
            ],
        )
    )
    groups_url = f"{VALET}groups/FX_RATES_DAILY/json"
    members = get(groups_url).json()["groupDetail"]["groupSeries"]
    if any("VEF" in s or "VES" in s for s in members):
        fail("the Bank now publishes a bolívar rate: N-14 is no longer a refusal")
    out.append(
        _q(
            id="N-14",
            category="Discontinued series",
            group="boc",
            eval_type="refusal",
            question="What was the Bank of Canada's daily exchange rate for the Venezuelan "
            "bolívar on October 30, 2026?",
            expected={
                "behaviour": "Say the Bank of Canada publishes no bolívar rate: it is not among "
                "the currencies in its daily exchange rates."
            },
            absent_pattern=r"(?:does not|doesn't|doesn’t|no longer) (?:publish|provide|"
            r"report|quote|cover|include)|not (?:among|in|one of|part of|included)|"
            r"no (?:official |daily )?(?:rate|series)|(?:discontinued|stopped)",
            tolerance="Refusal: no Valet series for the bolívar among the daily rates "
            f"({len(members)} series in FX_RATES_DAILY).",
            grading={
                "correct": "Says the Bank publishes no bolívar rate.",
                "hallucinated": "A bolívar rate attributed to the Bank, or a cross rate computed "
                "from other series and presented as the Bank's.",
                "referral": "Points to another source without saying the Bank has none.",
            },
            citations=[
                cite(
                    "Valet",
                    "FX_RATES_DAILY",
                    "Daily exchange rates (group members)",
                    sorted(members),
                    groups_url,
                )
            ],
            traps=["A cross rate through the US dollar from another source is not the Bank's."],
        )
    )
    return out


def cmhc_docs() -> list[dict[str, Any]]:
    text = page(CMHC_STARTS)
    absorbed = find(
        text,
        r"An absorbed unit is a housing unit that has been sold and completed\.",
        "CMHC absorbed",
    )
    sold = find(
        text,
        r"A unit is considered sold when a binding contract is secured by a "
        r"non-refundable deposit and has been signed by a qualified purchaser\.",
        "CMHC sold",
    )
    return [
        _q(
            id="N-15",
            category="Definitions",
            group="cmhc",
            eval_type="facts",
            question="In CMHC's Market Absorption Survey, what makes a newly built housing unit "
            "'absorbed', and when does CMHC consider a unit sold?",
            expected={"absorbed": absorbed.group(0), "sold": sold.group(0)},
            facts={
                "completed": r"complet",
                "sold": r"\bsold\b|\bsale\b",
                "deposit": r"deposit",
                "contract": r"contract|agreement",
            },
            headline=["completed", "deposit"],
            tolerance="Absorbed: sold and completed. Sold: a binding contract secured by a "
            "non-refundable deposit, signed by a qualified purchaser.",
            grading={
                "correct": "Sold and completed; sold means a binding contract with a "
                "non-refundable deposit.",
                "partial": "Sold and completed, without when a unit counts as sold.",
                "hallucinated": "Absorbed defined as occupied, rented or started.",
                "referral": "No definition, only a link to CMHC.",
            },
            citations=[
                cite(
                    "Other",
                    "CMHC Market Absorption Survey",
                    "Absorbed",
                    absorbed.group(0),
                    CMHC_STARTS,
                ),
                cite("Other", "CMHC Market Absorption Survey", "Sold", sold.group(0), CMHC_STARTS),
            ],
            traps=["Unsold completed units are 'unabsorbed'; occupancy is not the test."],
        )
    ]


def eccc() -> list[dict[str, Any]]:
    out = []
    station, climate_id = "WINNIPEG RICHARDSON INT'L A", "5023222"
    url = f"{GEOMET}climate-normals/items"
    params = {"f": "json", "CLIMATE_IDENTIFIER": climate_id, "MONTH": 1, "limit": 500}
    rows = [f["properties"] for f in get(url, params=params).json()["features"]]
    (row,) = [r for r in rows if r["E_NORMAL_ELEMENT_NAME"] == "Mean daily temperature deg C"]
    if (row["PERIOD_BEGIN"], row["PERIOD_END"]) != (1981, 2010):
        fail(f"Winnipeg's normals are now {row['PERIOD_BEGIN']}-{row['PERIOD_END']}")
    value = float(row["VALUE"])
    full = f"{url}?f=json&CLIMATE_IDENTIFIER={climate_id}&MONTH=1&limit=500"
    out.append(
        _q(
            id="N-21",
            category="Climate",
            group="federal",
            eval_type="numeric",
            question="What is the 1981-2010 Canadian Climate Normal for January's mean daily "
            f"temperature at {station.title()} (climate ID {climate_id})?",
            expected={"jan_mean_temp_c": value},
            headline=["jan_mean_temp_c"],
            tolerances={"jan_mean_temp_c": 0.05},
            tolerance=f"{value} °C (code {row['NORMAL_CODE']}), ±0.05; -16.4 rounded is fine.",
            grading={
                "correct": f"{value} °C (or {round(value, 1)}), for 1981-2010.",
                "partial": "The 1991-2020 normal, labelled as such.",
                "hallucinated": "Another station's or period's value given as this one.",
                "referral": "No value, only a link to ECCC's normals pages.",
            },
            citations=[
                cite(
                    "Other",
                    f"ECCC climate-normals {climate_id}",
                    "Mean daily temperature deg C",
                    value,
                    full,
                    "1981-2010, January",
                )
            ],
            traps=[
                "The 1991-2020 normals are a different period.",
                (
                    "Winnipeg Richardson Int'l A has several climate IDs; this one closed in 2013 but "
                    "carries the 1981-2010 normals."
                ),
            ],
        )
    )
    other = "6158359"
    stations = get(
        f"{GEOMET}climate-stations/items", params={"f": "json", "CLIMATE_IDENTIFIER": other}
    ).json()["features"]
    (info,) = [s["properties"] for s in stations]
    normals = get(url, params={"f": "json", "CLIMATE_IDENTIFIER": other, "limit": 1}).json()
    if normals.get("numberMatched") or info["HAS_NORMALS_DATA"] != "N":
        fail(f"{other} now has climate normals: N-22 is no longer a refusal")
    out.append(
        _q(
            id="N-22",
            category="Not published",
            group="federal",
            eval_type="refusal",
            question="What is the 1981-2010 Canadian Climate Normal for January's mean daily "
            f"temperature at Toronto City Centre (climate ID {other})?",
            expected={
                "behaviour": "Say this station has no climate normals: it opened in "
                f"{info['FIRST_DATE'][:4]}, after the period, and ECCC lists no normals for it.",
                "first_date": info["FIRST_DATE"][:10],
            },
            absent_pattern=r"no (?:climate )?normals?|(?:not|n't|n’t) (?:have|has|publish|"
            r"calculate|compute)[^.]{0,40}normals?|normals?[^.]{0,60}(?:not available|"
            r"(?:are|is|were)(?:n't|n’t| not) (?:available|published|calculated))|"
            r"(?:opened|began|started)[^.]{0,40}20(?:0\d|1\d)",
            tolerance=f"Refusal: HAS_NORMALS_DATA = N; no rows in climate-normals for {other}.",
            grading={
                "correct": "Says the station has no 1981-2010 normal (opened in 2009).",
                "partial": "Declines and offers another station's normal, labelled.",
                "hallucinated": "A normal given for this station, or another station's given as "
                "this one's.",
                "referral": "Points to ECCC's pages without saying none exists.",
            },
            citations=[
                cite(
                    "Other",
                    f"ECCC climate-stations {other}",
                    info["STATION_NAME"],
                    {"FIRST_DATE": info["FIRST_DATE"], "HAS_NORMALS_DATA": "N"},
                    f"{GEOMET}climate-stations/items?f=json&CLIMATE_IDENTIFIER={other}",
                )
            ],
            traps=["Toronto's normals belong to Toronto City (6158355) and Pearson, not here."],
        )
    )
    return out


def portal(base: str, name: str) -> tuple[dict[str, Any], str]:
    return ckan(base, "package_show", id=name), f"{base}package_show?id={name}"


def portals() -> list[dict[str, Any]]:
    out = []
    p, url = portal(FED, "d8f85d91-7dec-4fd1-8055-483b77225d8b")
    over = [r for r in p["resources"] if r["name"].strip() == "Contracts over $10,000"]
    if len(over) != 1 or over[0]["format"].upper() != "CSV" or not over[0].get("datastore_active"):
        fail("TBS contracts: the 'Contracts over $10,000' resource changed")
    if p.get("frequency") != "P3M":
        fail(f"TBS contracts: frequency is now {p.get('frequency')}")
    out.append(
        _q(
            id="N-20",
            category="Dataset metadata",
            group="federal",
            eval_type="facts",
            question="On open.canada.ca, which organization publishes the 'Proactive "
            "Publication - Contracts' dataset, how often is it updated, and can its 'Contracts "
            "over $10,000' file be queried through the portal's DataStore API?",
            expected={
                "organization": p["organization"]["title"].split(" | ")[0],
                "frequency": "P3M (quarterly)",
                "licence": p["license_title"],
                "contracts_over_10k": "CSV, DataStore active",
            },
            facts={
                "organization": r"Treasury Board|\bTBS\b",
                "frequency": r"quarterly|every (?:three|3) months|P3M",
                "datastore": r"datastore[^.]{0,80}\b(?:yes|active|queryable|available|can be "
                r"queried|enabled)\b|\b(?:yes|can)\b[^.]{0,60}datastore|datastore_search",
            },
            wrong=[
                r"datastore[^.]{0,60}\b(?:is not|isn't|isn’t|not active|inactive|unavailable|not available|not enabled|cannot|can't)\b|\b(?:no|without)\s+datastore"
            ],
            headline=["organization", "frequency"],
            tolerance="Treasury Board of Canada Secretariat; quarterly (P3M); the file is a CSV "
            "with the DataStore active.",
            grading={
                "correct": "TBS, quarterly, and the DataStore can query it.",
                "partial": "Two of the three.",
                "hallucinated": "Another department, or 'no DataStore'.",
                "referral": "No answer, only a link to the dataset.",
            },
            citations=[
                cite(
                    "Other",
                    "open.canada.ca d8f85d91-7dec-4fd1-8055-483b77225d8b",
                    p["title"],
                    {
                        "frequency": p["frequency"],
                        "resource": over[0]["name"],
                        "datastore_active": True,
                    },
                    url,
                )
            ],
            traps=["The departments' own contract pages are not this dataset."],
        )
    )
    p, url = portal(FED, "51dbf91e-509c-437b-ab9e-eca6d0bf6fa8")
    formats = sorted({(r.get("format") or "").upper() for r in p["resources"]})
    if "CSV" in formats:
        fail("Climate Data Products now lists a CSV: N-23 is no longer a refusal")
    out.append(
        _q(
            id="N-23",
            category="Not published",
            group="federal",
            eval_type="refusal",
            question="Which CSV files does open.canada.ca list in Environment and Climate Change "
            "Canada's 'Climate Data Products' dataset?",
            expected={
                "behaviour": "Say the dataset lists no CSV file: its resources are links to web "
                "pages and other products.",
                "formats": formats,
                "resources": len(p["resources"]),
            },
            absent_pattern=r"\b(?:no|none of)\b[^.]{0,40}\bCSV|\bCSV[^.]{0,60}(?:none|not (?:listed|"
            r"included|available)|isn't|is not)|(?:not|n't|n’t) (?:list|include|have|offer)"
            r"[^.]{0,30}\bCSV",
            tolerance=f"Refusal: {len(p['resources'])} resources, formats {formats}; no CSV.",
            grading={
                "correct": "Says the dataset lists no CSV (its resources are web pages).",
                "hallucinated": "CSV files named as resources of this dataset.",
                "referral": "Points to ECCC's site without answering.",
            },
            citations=[
                cite(
                    "Other",
                    "open.canada.ca 51dbf91e-509c-437b-ab9e-eca6d0bf6fa8",
                    p["title"],
                    {"formats": formats},
                    url,
                )
            ],
            traps=[
                (
                    "ECCC's climate data are downloadable elsewhere (MSC GeoMet, the climate "
                    "data site); this dataset only links to products."
                )
            ],
        )
    )
    p, url = portal(BC, "bc-liquor-store-locations")
    res = p["resources"]
    if len(res) != 1 or res[0]["format"].lower() != "csv":
        fail("BC liquor store locations: its resources changed")
    out.append(
        _q(
            id="N-17",
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="In the BC Data Catalogue, which organization publishes the 'BC Liquor "
            "Store Locations' dataset, under which licence, and in what format is its data?",
            expected={
                "organization": p["organization"]["title"],
                "licence": p["license_title"],
                "format": "CSV",
                "resources": len(res),
            },
            facts={
                "organization": r"Liquor Distribution",
                "licence": r"Open Government Licen[cs]e\W{0,3}(?:-|–|—|for)?\s*British "
                r"Columbia|OGL[- ]?BC",
                "csv": r"\bCSV\b",
            },
            wrong=[r"Liquor and Cannabis Regulation Branch publishes"],
            headline=["organization", "licence"],
            tolerance=f"{p['organization']['title']} (Branch); {p['license_title']}; one CSV.",
            grading={
                "correct": "Liquor Distribution Branch, OGL-BC, CSV.",
                "partial": "Two of the three.",
                "hallucinated": "The Liquor and Cannabis Regulation Branch's dataset given as this "
                "one, or another licence.",
                "referral": "No answer, only a link to the catalogue.",
            },
            citations=[
                cite(
                    "Other",
                    "BC Data Catalogue bc-liquor-store-locations",
                    p["title"],
                    {"organization": p["organization"]["title"], "licence": p["license_title"]},
                    url,
                )
            ],
            traps=[
                (
                    "The catalogue also has 'Private Liquor Store and BC Liquor Store Locations', "
                    "from another branch, and an access-only 'Store Locator'."
                )
            ],
        )
    )
    name = "portrait-public-des-utilisations-de-l-ia-dans-l-administration-publique-quebecoise"
    p, url = portal(QC, name)
    years = sorted({y for r in p["resources"] for y in re.findall(r"20\d\d", r["name"])})
    out.append(
        _q(
            id="N-18",
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="On Données Québec, which ministry publishes the dataset on uses of "
            "artificial intelligence in Quebec's public administration ('Portrait public des "
            "utilisations de l'IA dans l'administration publique québécoise'), under which "
            "licence, how often is it updated, and which years does it cover?",
            expected={
                "organization": p["organization"]["title"],
                "licence": p["license_title"],
                "frequency": p.get("update_frequency"),
                "years": years,
            },
            facts={
                "ministry": r"Cybers[ée]curit[ée]|Num[ée]rique|Cybersecurity|Digital",
                "licence": r"CC[- ]?BY|Creative Commons",
                "frequency": r"annual|yearly|annuel|every year|once a year",
                "years": rf"^(?=[\s\S]*{years[0]})(?=[\s\S]*{years[-1]})",
            },
            headline=["ministry", "licence"],
            tolerance=f"{p['organization']['title']}; {p['license_title']}; annual; "
            f"{years[0]} to {years[-1]}, each year in CSV and Excel.",
            grading={
                "correct": "The ministry of cybersecurity and digital affairs, CC BY 4.0, annual, "
                f"{years[0]} to {years[-1]}.",
                "partial": "The ministry and the licence, frequency or years missing.",
                "referral": "No answer, only a link to Données Québec.",
            },
            citations=[
                cite(
                    "Other",
                    f"Données Québec {name}",
                    p["title"],
                    {"frequency": p.get("update_frequency"), "years": years},
                    url,
                )
            ],
            traps=[
                (
                    "The ministry is the Ministère de la Cybersécurité et du Numérique, not the "
                    "Conseil du trésor or the Ministère de l'Économie."
                )
            ],
        )
    )
    p, url = portal(TOR, "dinesafe")
    active = [r for r in p["resources"] if r.get("datastore_active")]
    if not active:
        fail("Dinesafe has no DataStore resource")
    out.append(
        _q(
            id="N-19",
            category="Dataset metadata",
            group="municipal",
            eval_type="facts",
            question="On Toronto's open data portal, which City division owns the "
            "'Dinesafe' restaurant-inspection dataset, how often is it refreshed, and can it be "
            "queried through the DataStore API?",
            expected={
                "owner_division": p["owner_division"],
                "refresh_rate": p["refresh_rate"],
                "datastore": f"{len(active)} DataStore resource(s)",
            },
            facts={
                "division": r"Toronto Public Health|\bTPH\b",
                "refresh": r"\bdaily\b|every day",
                "datastore": r"datastore[^.]{0,80}\b(?:yes|active|queryable|available|can be "
                r"queried|enabled)\b|\b(?:yes|can)\b[^.]{0,60}datastore|datastore_search",
            },
            wrong=[
                r"Municipal Licensing|\bMLS\b owns",
                r"datastore[^.]{0,60}\b(?:is not|isn't|isn’t|not active|inactive|unavailable|not available|not enabled|cannot|can't)\b|\b(?:no|without)\s+datastore",
            ],
            headline=["division", "refresh"],
            tolerance=f"{p['owner_division']}; refreshed {p['refresh_rate'].lower()}; a "
            "DataStore resource exists.",
            grading={
                "correct": "Toronto Public Health, daily, DataStore yes.",
                "partial": "Two of the three.",
                "referral": "No answer, only a link to the portal.",
            },
            citations=[
                cite(
                    "Other",
                    "Toronto CKAN dinesafe",
                    p["title"],
                    {"owner_division": p["owner_division"], "refresh_rate": p["refresh_rate"]},
                    url,
                )
            ],
            traps=[
                "Dinesafe is run by Toronto Public Health, not Municipal Licensing and Standards."
            ],
        )
    )
    return out


def international() -> list[dict[str, Any]]:
    url = f"{BIS}WS_TC/Q.CA.P.A.M.770.A"
    rows = list(
        csv.DictReader(io.StringIO(get(url, params={"startPeriod": "2025", "format": "csv"}).text))
    )
    by_period = {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r["OBS_VALUE"]}
    if "2026-Q1" not in by_period:
        fail("BIS total credit: no 2026-Q1 value")
    value = by_period["2026-Q1"]
    out = [
        _q(
            id="N-24",
            category="Finance",
            group="international",
            eval_type="numeric",
            question="According to the BIS, what was total credit to Canada's private "
            "non-financial sector, as a percentage of GDP, in the first quarter of 2026?",
            expected={"credit_pnfs_gdp_pct_2026q1": value},
            reference={k: v for k, v in by_period.items() if k != "2026-Q1"},
            headline=["credit_pnfs_gdp_pct_2026q1"],
            tolerances={"credit_pnfs_gdp_pct_2026q1": 0.05},
            tolerance=f"{value}% of GDP (BIS WS_TC Q.CA.P.A.M.770.A, 2026-Q1), ±0.05.",
            grading={
                "correct": f"{value}% of GDP for 2026-Q1.",
                "partial": "A neighbouring quarter, labelled.",
                "hallucinated": "Household credit only, or bank credit only, given as total "
                "credit.",
                "referral": "No value, only a link to the BIS.",
            },
            citations=[
                cite(
                    "Other",
                    "BIS WS_TC Q.CA.P.A.M.770.A",
                    "Canada - Credit to private non-financial sector from all sectors at "
                    "market value - % of GDP - adjusted for breaks",
                    value,
                    f"{url}?startPeriod=2025&format=csv",
                    "2026-Q1",
                )
            ],
            traps=[
                (
                    "Households' debt or bank credit alone is a smaller share; the BIS total "
                    "covers households and non-financial corporations from all lenders."
                )
            ],
        )
    ]
    meta_url = f"{WB}indicator/SL.TLF.TOTL.IN"
    (meta,) = get(meta_url, params={"format": "json"}).json()[1]
    ages = find(meta["sourceNote"], r"ages? (\d+) and older", "World Bank SL.TLF.TOTL.IN")
    out.append(
        _q(
            id="N-25",
            category="Series metadata",
            group="international",
            eval_type="facts",
            question="How does the World Bank's World Development Indicators define 'Labor "
            "force, total' (indicator SL.TLF.TOTL.IN): from what age, who is counted, and "
            "which organization's estimates are the figures?",
            expected={
                "name": meta["name"],
                "ages": f"{ages.group(1)} and older",
                "source_organization": meta["sourceOrganization"].split(", uri")[0],
            },
            facts={
                "ages": rf"\b{ages.group(1)}\b[^.]{{0,20}}(?:and (?:older|over)|\+)|"
                rf"(?:aged?|ages) {ages.group(1)}",
                "employed_unemployed": r"employ[^.]{0,60}unemploy|unemploy[^.]{0,60}employ|"
                r"supply labou?r",
                "ilo": r"International Labour Organi[sz]ation|\bILO\b|ILOSTAT",
            },
            headline=["ages", "employed_unemployed"],
            tolerance=f"People ages {ages.group(1)} and older who supply labour: the employed "
            "and the unemployed; ILO estimates.",
            grading={
                "correct": f"{ages.group(1)} and older, employed and unemployed, ILO estimates.",
                "partial": "Two of the three.",
                "hallucinated": "Another age (15 to 64 only, or 16 and older) given as the "
                "definition.",
                "referral": "No answer, only a link to the World Bank.",
            },
            citations=[
                cite(
                    "Other",
                    "World Bank SL.TLF.TOTL.IN",
                    meta["name"],
                    meta["sourceNote"][:300],
                    f"{meta_url}?format=json",
                )
            ],
            traps=[
                (
                    "Working-age population (15 to 64) is a different series; Statistics "
                    "Canada's LFS counts people 15 and older living in the provinces."
                )
            ],
        )
    )
    return out


def open_part() -> list[dict[str, Any]]:
    return statcan_docs() + bank_of_canada() + cmhc_docs() + eccc() + portals() + international()


# StatCan part: WDS and the release schedule (www150) ---------------------------------


def cube(pid: int) -> dict[str, Any]:
    (meta,) = post(f"{WDS}getCubeMetadata", [{"productId": pid}])
    if meta.get("status") != "SUCCESS":
        fail(f"getCubeMetadata {pid}: {meta}")
    return meta["object"]


def member(meta: dict[str, Any], dimension: str, name: str) -> int:
    """The member id named exactly `name` in the dimension whose name starts `dimension`."""
    dims = [d for d in meta["dimension"] if d["dimensionNameEn"].startswith(dimension)]
    if len(dims) != 1:
        fail(f"{meta['productId']}: no single dimension {dimension!r}")
    found = [m["memberId"] for m in dims[0]["member"] if m["memberNameEn"] == name]
    if len(found) != 1:
        fail(f"{meta['productId']}: no single member {name!r} in {dimension!r}")
    return found[0]


def coordinate(meta: dict[str, Any], picks: dict[str, str]) -> str:
    """The coordinate of one series: each dimension's member by name, '0' past the last."""
    ids = []
    for d in sorted(meta["dimension"], key=lambda d: d["dimensionPositionId"]):
        prefix = next((k for k in picks if d["dimensionNameEn"].startswith(k)), None)
        if prefix is None:
            fail(f"{meta['productId']}: no pick for dimension {d['dimensionNameEn']!r}")
        ids.append(str(member(meta, prefix, picks[prefix])))
    return ".".join(ids + ["0"] * (10 - len(ids)))


def series(pid: int, coord: str, latest: int) -> tuple[dict[str, float], dict[str, Any]]:
    (resp,) = post(
        f"{WDS}getDataFromCubePidCoordAndLatestNPeriods",
        [{"productId": pid, "coordinate": coord, "latestN": latest}],
    )
    if resp.get("status") != "SUCCESS":
        fail(f"{pid} {coord}: {resp}")
    obj = resp["object"]
    points = {p["refPer"][:7]: p for p in obj["vectorDataPoint"]}
    return {k: float(p["value"]) for k, p in points.items() if p["value"] is not None}, {
        "vector": f"v{obj['vectorId']}",
        "released": max(p["releaseTime"] for p in points.values())[:16],
    }


def table_id(pid: int) -> str:
    s = str(pid)
    return f"{s[:2]}-{s[2:4]}-{s[4:8]}-01"


def tv(pid: int) -> str:
    return f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid}01"


def wds_cite(pid: int, info: dict[str, Any], title: str, period: str, value: float) -> dict:
    return cite(table_id(pid), info["vector"], title, value, tv(pid), period, info["released"])


def statcan_data() -> list[dict[str, Any]]:
    out = []
    # N-01: IPPI, total, Canada, 12 months to September 2026.
    pid = 18100266
    meta = cube(pid)
    total = next(
        m["memberNameEn"]
        for d in meta["dimension"]
        if d["dimensionNameEn"].startswith("North American Product")
        for m in d["member"]
        if m["memberNameEn"].startswith("Total")
    )
    data, info = series(
        pid, coordinate(meta, {"Geography": "Canada", "North American Product": total}), 13
    )
    ippi = pct(data["2026-09"], data["2025-09"])
    out.append(
        _q(
            id="N-01",
            category="Prices",
            group="statcan",
            eval_type="numeric",
            question="By how much did Canada's Industrial Product Price Index (IPPI, all products) "
            "change over the 12 months to September 2026?",
            expected={"ippi_yoy_pct": ippi},
            reference={"index_2026_09": data["2026-09"], "index_2025_09": data["2025-09"]},
            headline=["ippi_yoy_pct"],
            tolerance=f"{ippi}% (index {data['2026-09']} vs {data['2025-09']}), ±0.1.",
            grading={
                "correct": f"{ippi}% over 12 months.",
                "partial": "The monthly change given beside a wrong 12-month figure.",
                "hallucinated": "The monthly change, or the RMPI, given as the answer.",
                "referral": "No figure, only a link to the table.",
            },
            citations=[
                wds_cite(pid, info, f"Canada;{total}", "2026-09", data["2026-09"]),
                wds_cite(pid, info, f"Canada;{total}", "2025-09", data["2025-09"]),
            ],
            traps=[
                "The Raw Materials Price Index (RMPI) is a different index in the same release.",
                "A month-over-month change is not the 12-month change.",
            ],
        )
    )
    # N-02: labour productivity, business sector, Q2 2026 vs Q1.
    pid = 36100206
    meta = cube(pid)
    coord = coordinate(
        meta,
        {
            "Geography": "Canada",
            "Labour productivity": "Labour productivity",
            "Sector": "Business sector",
        },
    )
    data, info = series(pid, coord, 3)
    lp = pct(data["2026-04"], data["2026-01"])
    out.append(
        _q(
            id="N-02",
            category="Output",
            group="statcan",
            eval_type="numeric",
            question="By how much did labour productivity in Canadian businesses change in the "
            "second quarter of 2026 from the first quarter?",
            expected={"labour_productivity_q2_2026_pct": lp},
            reference={"index_2026q2": data["2026-04"], "index_2026q1": data["2026-01"]},
            headline=["labour_productivity_q2_2026_pct"],
            # From indexes rounded to one decimal, so The Daily's change can differ by 0.1.
            tolerances={"labour_productivity_q2_2026_pct": 0.2},
            tolerance=f"{lp}% quarter over quarter (business sector, seasonally adjusted), ±0.2 "
            "(computed from the rounded indexes).",
            grading={
                "correct": f"{lp}% from the first quarter.",
                "partial": "The right quarter's change for the total economy, labelled.",
                "hallucinated": "An annualized rate or another quarter given as this one.",
                "referral": "No figure, only a link to the table.",
            },
            citations=[
                wds_cite(
                    pid,
                    info,
                    "Canada;Labour productivity;Business sector",
                    "2026-Q2",
                    data["2026-04"],
                )
            ],
            traps=["The business sector is not the total economy; the change is not annualized."],
        )
    )
    # N-03: EI regular beneficiaries, Canada, August 2026.
    pid = 14100011
    meta = cube(pid)
    picks = {}
    for d in meta["dimension"]:
        names = [m["memberNameEn"] for m in d["member"]]
        if d["dimensionNameEn"].startswith("Geography"):
            picks["Geography"] = "Canada"
        elif "Regular benefits" in names:
            picks[d["dimensionNameEn"][:20]] = "Regular benefits"
        else:
            picks[d["dimensionNameEn"][:20]] = names[0]
    data, info = series(pid, coordinate(meta, picks), 2)
    ei = data["2026-08"]
    out.append(
        _q(
            id="N-03",
            category="Labour",
            group="statcan",
            eval_type="numeric",
            question="How many people received regular Employment Insurance benefits in Canada "
            "in August 2026 (seasonally adjusted)?",
            expected={"ei_regular_beneficiaries_aug_2026": ei},
            headline=["ei_regular_beneficiaries_aug_2026"],
            tolerance=f"{ei:,.0f} beneficiaries (picks {picks}); rounded within 0.1% is fine.",
            grading={
                "correct": f"{ei:,.0f} (August 2026, seasonally adjusted).",
                "partial": "The unadjusted count for August, labelled.",
                "hallucinated": "All benefit types, or claims received, given as regular "
                "beneficiaries.",
                "referral": "No figure, only a link to the table.",
            },
            citations=[wds_cite(pid, info, "Canada;Regular benefits", "2026-08", ei)],
            traps=[
                "Claims (14-10-0005) are not beneficiaries; regular benefits are not all types."
            ],
        )
    )
    # N-04: Canadian-resident return trips from the US by automobile, August 2026 (the
    # table's latest month when keyed).
    pid = 24100053
    meta = cube(pid)
    trav = "Canadian residents returning from the United States of America, land, automobile"
    mode = "Travellers"
    picks = {"Geography": "Canada", "Traveller characteristics": trav, "Traveller type": mode}
    data, info = series(pid, coordinate(meta, picks), 13)
    now, before = data["2026-08"], data["2025-08"]
    out.append(
        _q(
            id="N-04",
            category="Travel",
            group="statcan",
            eval_type="numeric",
            question="How many return trips from the United States did Canadian residents make by "
            "automobile in August 2026, and how did that compare with August 2025?",
            expected={"trips_aug_2026": now, "trips_aug_2025": before},
            reference={"change_pct": pct(now, before)},
            headline=["trips_aug_2026"],
            tolerance=f"{now:,.0f} vs {before:,.0f} ({pct(now, before)}%); rounded within 0.1%.",
            grading={
                "correct": "Both months' counts.",
                "partial": "August 2026 only, or the change without both levels.",
                "hallucinated": "All modes, or US residents' trips, given as this series.",
                "referral": "No figure, only a link to the table.",
            },
            citations=[
                wds_cite(pid, info, f"Canada;{trav};{mode}", "2026-08", now),
                wds_cite(pid, info, f"Canada;{trav};{mode}", "2025-08", before),
            ],
            traps=[
                "US residents entering Canada are a different series; air trips are another mode."
            ],
        )
    )
    # N-05: NHPI, Calgary vs Edmonton, 12 months to September 2026.
    pid = 18100205
    meta = cube(pid)
    rates = {}
    infos = {}
    for city in ("Calgary, Alberta", "Edmonton, Alberta"):
        data, info = series(
            pid,
            coordinate(
                meta, {"Geography": city, "New housing price indexes": "Total (house and land)"}
            ),
            13,
        )
        rates[city] = pct(data["2026-09"], data["2025-09"])
        infos[city] = (info, data)
    if abs(rates["Calgary, Alberta"] - rates["Edmonton, Alberta"]) < 0.2:
        fail(f"NHPI: {rates}: too close for a call; reword N-05")
    weaker = min(rates, key=lambda c: rates[c]).split(",")[0]
    other = max(rates, key=lambda c: rates[c]).split(",")[0]
    out.append(
        _q(
            id="N-05",
            category="Housing",
            group="statcan",
            eval_type="comparison",
            question="Over the 12 months to September 2026, how did new home prices change in "
            "Calgary and in Edmonton, by Statistics Canada's New Housing Price Index, and in "
            "which of the two were they weaker?",
            expected={
                "calgary_yoy_pct": rates["Calgary, Alberta"],
                "edmonton_yoy_pct": rates["Edmonton, Alberta"],
            },
            # The weaker city named as weaker, fallen more, or lower ("Edmonton fell 0.8%
            # while Calgary was flat"); or the other as the stronger one.
            answer_regex=rf"{weaker}[^.]{{0,100}}\b(?:weaker|fell|declin\w*|drop\w*|decreas\w*|"
            rf"lower|down|softer)\b|\b(?:weaker|softer)\b[^.]{{0,60}}{weaker}|{other}[^.]{{0,100}}"
            rf"\b(?:stronger|held|flat|unchanged|firmer)\b",
            headline=["calgary_yoy_pct", "edmonton_yoy_pct"],
            tolerance=f"Calgary {rates['Calgary, Alberta']}%, Edmonton "
            f"{rates['Edmonton, Alberta']}% (total, house and land), ±0.1; weaker in {weaker}.",
            grading={
                "correct": f"{weaker} weaker, with both 12-month changes.",
                "partial": "The right call with one change.",
                "hallucinated": "The other city, or resale prices (CREA) given as the NHPI.",
                "referral": "No figures, only a link to the table.",
            },
            citations=[
                wds_cite(
                    pid,
                    infos[c][0],
                    f"{c};Total (house and land)",
                    "2026-09",
                    infos[c][1]["2026-09"],
                )
                for c in infos
            ],
            traps=[
                "The NHPI covers new homes from builders; CREA's resale prices are another measure."
            ],
        )
    )
    # N-06: flag: quarterly GDP is published at annual rates; dividing it by the population
    # gives an annual figure per person, not one for the quarter. (The first draft averaged
    # the provinces' unemployment rates; in October 2026 that average was within 0.05 of
    # Canada's rate, so the trap could not catch anyone.)
    pid = 36100104
    meta = cube(pid)
    gdp, info_gdp = series(
        pid,
        coordinate(
            meta,
            {
                "Geography": "Canada",
                "Prices": "Current prices",
                "Seasonal adjustment": "Seasonally adjusted at annual rates",
                "Estimates": "Gross domestic product at market prices",
            },
        ),
        1,
    )
    pop_pid = 17100009
    pop_meta = cube(pop_pid)
    pop, info_pop = series(pop_pid, coordinate(pop_meta, {"Geography": "Canada"}), 2)
    if "2026-04" not in gdp or "2026-04" not in pop:
        fail(f"N-06: Q2 2026 GDP or the April 1, 2026 population is missing: {gdp} {pop}")
    # GDP is in millions of dollars.
    per_person = round(gdp["2026-04"] * 1e6 / pop["2026-04"])
    out.append(
        _q(
            id="N-06",
            category="Output",
            group="statcan",
            eval_type="flag",
            question="Take Canada's nominal GDP for the second quarter of 2026 (expenditure-based, "
            "seasonally adjusted) and divide it by Canada's population on April 1, 2026, to get "
            "GDP per person for that quarter.",
            expected={"gdp_per_person_annual_rate": per_person},
            reference={
                "gdp_q2_2026_saar_millions": gdp["2026-04"],
                "population_2026_04_01": pop["2026-04"],
                "per_person_for_the_quarter": round(per_person / 4),
            },
            flag_pattern=r"annual(?:i[sz]ed)? rates?|annuali[sz]ed|\bSAAR\b|"
            r"(?:divide|divided)[^.]{0,30}(?:by )?(?:4|four)|(?:one|a) quarter of (?:that|it|the)|"
            r"(?:four|4) times|for (?:a|the) (?:whole|full) year",
            figure_required=False,
            headline=[],
            tolerance=f"Flag that the quarterly GDP is at annual rates: {gdp['2026-04']:,.0f} "
            f"million / {pop['2026-04']:,.0f} = about ${per_person:,} a year per person, about "
            f"${round(per_person / 4):,} for the quarter.",
            grading={
                "correct": "Says the GDP figure is at annual rates, so the ratio is annual (or "
                "divides by four for the quarter).",
                "partial": "Computes the ratio, then says after that it is at annual rates.",
                "hallucinated": f"About ${per_person:,} given as GDP per person for the quarter.",
                "referral": "No figure, only a link to the tables.",
            },
            citations=[
                wds_cite(
                    pid,
                    info_gdp,
                    "Canada;GDP at market prices;current;SAAR",
                    "2026-Q2",
                    gdp["2026-04"],
                ),
                wds_cite(pop_pid, info_pop, "Canada;population", "2026-04-01", pop["2026-04"]),
            ],
            traps=[
                "Quarterly GDP is published at annual rates (SAAR): it is four quarters' worth."
            ],
        )
    )
    # N-09: refusal: monthly GDP by industry is published for Canada only.
    pid = 36100434
    meta = cube(pid)
    geos = [
        m["memberNameEn"]
        for d in meta["dimension"]
        if d["dimensionNameEn"].startswith("Geography")
        for m in d["member"]
    ]
    if geos != ["Canada"]:
        fail(f"36-10-0434 now has geographies {geos}: N-09 is no longer a refusal")
    out.append(
        _q(
            id="N-09",
            category="Not published",
            group="statcan",
            eval_type="refusal",
            question="What was Nova Scotia's real GDP in August 2026, according to Statistics "
            "Canada's monthly GDP by industry?",
            expected={
                "behaviour": "Say StatCan publishes monthly GDP by industry for Canada only; "
                "provincial GDP is annual.",
                "geographies": geos,
            },
            absent_pattern=r"(?:only|just)[^.]{0,40}(?:national|Canada)[- ]level|(?:national|"
            r"Canada)[^.]{0,30}only|no (?:monthly )?provincial|(?:not|n't|n’t) (?:published|"
            r"available|produce[ds]?)[^.]{0,60}(?:province|monthly)|provincial[^.]{0,60}annual",
            tolerance="Refusal: 36-10-0434-01 has one geography, Canada; provincial GDP is annual "
            "(36-10-0402).",
            grading={
                "correct": "Says monthly GDP is national only.",
                "partial": "Declines and gives the annual provincial figure, labelled.",
                "hallucinated": "A monthly Nova Scotia figure.",
                "referral": "Points to Nova Scotia's finance department without saying "
                "StatCan has none.",
            },
            citations=[
                cite(table_id(pid), None, meta["cubeTitleEn"], {"geographies": geos}, tv(pid))
            ],
            traps=["Nova Scotia's own economic indicators are not StatCan's monthly GDP."],
        )
    )
    # N-16: CMHC vacancy rate, Vancouver CMA, October 2025 (as StatCan publishes it).
    pid = 34100127
    meta = cube(pid)
    geo = next(
        m["memberNameEn"]
        for d in meta["dimension"]
        if d["dimensionNameEn"].startswith("Geography")
        for m in d["member"]
        if m["memberNameEn"].startswith("Vancouver, British Col")
    )
    picks = {}
    for d in meta["dimension"]:
        names = [m["memberNameEn"] for m in d["member"]]
        key = d["dimensionNameEn"][:20]
        picks[key] = (
            geo
            if d["dimensionNameEn"].startswith("Geography")
            else next((n for n in names if n.startswith(("Total", "Apartment"))), names[0])
        )
    data, info = series(pid, coordinate(meta, picks), 2)
    year = max(data)
    if not year.startswith("2025"):
        fail(f"34-10-0127: latest Vancouver value is {year}")
    vac = data[year]
    out.append(
        _q(
            id="N-16",
            category="Housing",
            group="cmhc",
            eval_type="numeric",
            question="In CMHC's October 2025 Rental Market Survey, as Statistics Canada publishes "
            "it for apartment structures of six units and over, what was the vacancy rate in the "
            "Vancouver census metropolitan area?",
            expected={"vancouver_vacancy_2025_pct": vac},
            headline=["vancouver_vacancy_2025_pct"],
            tolerance=f"{vac}% (CMHC, as in StatCan table 34-10-0127, {picks}), ±0.1.",
            grading={
                "correct": f"{vac}% for October 2025 (six units and over).",
                "partial": "The 2024 rate, or CMHC's three-units-and-over rate, labelled.",
                "hallucinated": "Another CMA's rate, or the City of Vancouver's, given as the "
                "CMA's.",
                "referral": "No figure, only a link to CMHC.",
            },
            citations=[wds_cite(pid, info, f"{geo};{picks}", year, vac)],
            traps=["The CMA is not the City of Vancouver; condominium vacancy is another series."],
        )
    )
    return out


def releases() -> list[dict[str, Any]]:
    # The archive lists only major releases ahead; the two-week calendar adds the rest
    # (key_v2_release._schedule, 2026-11-04).
    from tests.maple_test.key_v2_release import _schedule

    entries = _schedule()

    def one(title: str, period: str) -> dict[str, Any]:
        found = [
            e
            for e in entries
            if re.search(title, e["title"], re.IGNORECASE)
            and re.search(period, e.get("description") or "", re.IGNORECASE)
        ]
        if len(found) != 1:
            fail(f"release schedule: {len(found)} entries for {title!r}, {period!r}")
        return found[0]

    def rcite(e: dict[str, Any]) -> dict[str, Any]:
        day = e["date"][:10]
        return cite(
            "Other",
            None,
            f"The Daily release schedule: {e['title']}, {e.get('description')}",
            day,
            DAILY + e["url"] if e.get("url") else SCHEDULE,
            e.get("description"),
            day,
        )

    capital = one(r"^Stock and consumption of fixed capital$", r"^2025$")
    poverty = one(r"^Provisional poverty estimates$", r"^2025$")
    return [
        _q(
            id="N-10",
            category="Release",
            group="statcan",
            eval_type="date",
            question="On what date does Statistics Canada release its annual estimates of the "
            "stock and consumption of fixed capital for 2025?",
            expected={"fixed_capital_2025_release": capital["date"][:10]},
            headline=["fixed_capital_2025_release"],
            tolerance=f"{capital['date'][:10]} (The Daily's release schedule).",
            grading={
                "correct": f"{capital['date'][:10]}.",
                "hallucinated": "Another date given as this release (the 2024 edition's date "
                "is fine as context).",
                "referral": "No date, only a link to the release calendar.",
            },
            citations=[rcite(capital)],
            traps=[
                (
                    "Last year's edition came out on another date; the investment survey "
                    "(capital expenditures) is another release."
                )
            ],
        ),
        _q(
            id="N-11",
            category="Release",
            group="statcan",
            eval_type="date",
            question="On what date did Statistics Canada release its provisional poverty "
            "estimates for 2025?",
            expected={"provisional_poverty_2025_release": poverty["date"][:10]},
            headline=["provisional_poverty_2025_release"],
            tolerance=f"{poverty['date'][:10]} (The Daily's release schedule).",
            grading={
                "correct": f"{poverty['date'][:10]}.",
                "hallucinated": "Another date given as this release, or the Canadian Income "
                "Survey's release given as it.",
                "referral": "No date, only a link to the release calendar.",
            },
            citations=[rcite(poverty)],
            traps=[
                (
                    "The provisional estimates are not the Canadian Income Survey's final 2025 "
                    "poverty rates, which come later."
                )
            ],
        ),
    ]


def statcan_part() -> list[dict[str, Any]]:
    return statcan_data() + releases()


PARTS = {"open": open_part, "statcan": statcan_part}
OPEN_IDS = {
    "N-07",
    "N-08",
    "N-12",
    "N-13",
    "N-14",
    "N-15",
    "N-17",
    "N-18",
    "N-19",
    "N-20",
    "N-21",
    "N-22",
    "N-23",
    "N-24",
    "N-25",
}


def assemble(questions: list[dict[str, Any]], parts_built: list[str]) -> dict[str, Any]:
    ordered = sorted(questions, key=lambda q: q["id"])
    return {
        "benchmark": "maple_test_v4_test",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "parts": parts_built,
        "sources": "Publishers' own APIs and pages, read directly: StatCan IMDB, WDS and The "
        "Daily's release schedule; Bank of Canada Valet; CMHC's methodology page; ECCC MSC "
        "GeoMet; CKAN Action APIs (open.canada.ca, BC Data Catalogue, Données Québec, "
        "Toronto); World Bank indicator API; BIS statistics API",
        "questions": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check v4's fresh test key.")
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    parser.add_argument("--part", choices=sorted(PARTS), help="rebuild one part, keep the other")
    args = parser.parse_args()
    current = json.loads(KEY.read_text(encoding="utf-8")) if KEY.exists() else None
    names = [args.part] if args.part else sorted(PARTS)
    fresh = [q for n in names for q in PARTS[n]()]
    kept = []
    if args.part and current:
        mine = OPEN_IDS if args.part == "open" else None
        kept = [
            q
            for q in current["questions"]
            if (q["id"] not in OPEN_IDS if mine else q["id"] in OPEN_IDS)
        ]
    built = sorted(set(names) | (set(current.get("parts", [])) if args.part and current else set()))
    new = assemble(fresh + kept, built)
    if args.check:
        if current is None:
            fail("no key to check")
        old = {
            **current,
            "questions": [
                q for q in current["questions"] if any(q["id"] == f["id"] for f in fresh)
            ],
        }
        changes = drift(old, {**new, "questions": fresh})
        print("\n".join(changes) or "no drift")
        return 1 if changes else 0
    KEY.write_text(
        json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {KEY.name}: {len(new['questions'])} questions, parts {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

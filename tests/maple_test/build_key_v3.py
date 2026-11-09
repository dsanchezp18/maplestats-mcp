"""Build the Maple Test v3 answer key: technical data and documentation questions.

v1 and v2 ask for figures. v3 asks what an analyst needs before trusting one: a series'
unit and frequency, a survey's target population and collection rules, a revision
policy, a classification code, a quality code, and, for open-data portals, a dataset's
publisher, licence, update frequency, formats, DataStore fields and values. A third of
the questions are on Statistics Canada, a few on the Bank of Canada and CMHC, and the
rest on CKAN portals (open.canada.ca, BC, Ontario, Alberta, Quebec, Toronto, Montreal),
so most answers are text, graded by the facts each must state (`eval_type: "facts"`),
not by numbers.

The rule is the one at the top of README.md: the questions were written and this key
built on 2026-11-08, before MapleStats or any other server was asked them, and no
MapleStats change may be tuned on them without a new set to check it on. Every value is
read here, with httpx, from the publisher's own API or documentation page, never
through MapleStats:

- Statistics Canada: IMDB survey pages (www23), the RDaaS classification API, and the
  Web Data Service (getSeriesInfoFromVector, getCubeMetadata, getCodeSets).
- Bank of Canada: Valet series and group metadata.
- CMHC: its survey methodology pages.
- CKAN: each portal's Action API (`package_show`, `datastore_search`), including
  Ontario's and Alberta's catalogues for T-33 to T-36.

    uv run python -m tests.maple_test.build_key_v3            # rebuild maple_test_v3.json
    uv run python -m tests.maple_test.build_key_v3 --check    # report drift, write nothing

Documentation answers are read from the page by a pattern; when the publisher rewords
the passage, the builder stops with the phrase it could not find, which is drift too.
"""

from __future__ import annotations

import argparse
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
KEY = HERE / "maple_test_v3.json"

# http2=True: StatCan resets a TLS handshake that offers only HTTP/1.1 (AGENTS.md).
_client = httpx.Client(
    http2=True,
    timeout=httpx.Timeout(120.0, connect=20.0),
    follow_redirects=True,
    headers={"User-Agent": "maplestats-mcp Maple Test key builder"},
)

IMDB = "https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&SDDS={}"
RDAAS = "https://api.statcan.gc.ca/rdaas"
VALET = "https://www.bankofcanada.ca/valet/"
CMHC_STARTS = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-research/surveys/methods/methodologies-starts-completions-market-absorption-survey"
)
CMHC_RMS = (
    "https://www.cmhc-schl.gc.ca/professionals/housing-markets-data-and-research/"
    "housing-research/surveys/methods/methodology-rental-market-survey"
)
FED = "https://open.canada.ca/data/api/3/action/"
BC = "https://catalogue.data.gov.bc.ca/api/3/action/"
QC = "https://www.donneesquebec.ca/recherche/api/3/action/"
TOR = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/"
MTL = "https://donnees.montreal.ca/api/3/action/"
WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
ON = "https://data.ontario.ca/api/3/action/"
AB = "https://open.alberta.ca/api/3/action/"

# A fact stated as absent: "no DataStore", "not in the DataStore", "isn't queryable".
NOT_NEAR = r"(?:\bno\b|\bnot\b|n't|n’t|\bnone\b|\bneither\b|\bnor\b|unavailable|without)"


def fail(msg: str) -> NoReturn:
    raise SystemExit(f"build_key_v3: {msg}")


def get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """GET with retries; honours Retry-After on 429 (open.canada.ca rate-limits)."""
    for attempt in range(5):
        try:
            response = _client.get(url, params=params)
            if response.status_code in (429, 502, 503, 504) and attempt < 4:
                time.sleep(min(float(response.headers.get("retry-after") or 10), 60))
                continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == 4:
                raise
            time.sleep(5)
    fail(f"no answer from {url}")


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


def dataset_url(base: str, name: str) -> str:
    return f"{base}package_show?id={name}"


def valet_series(name: str) -> dict[str, Any]:
    return get(f"{VALET}series/{name}/json").json()["seriesDetails"]


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
    return fields


# Statistics Canada --------------------------------------------------------------------


def statcan() -> list[dict[str, Any]]:
    lfs_url, cis_url, cpi_url = IMDB.format(3701), IMDB.format(5200), IMDB.format(2301)
    lfs, cis, cpi = page(lfs_url), page(cis_url), page(cpi_url)
    out: list[dict[str, Any]] = []

    excluded = find(
        lfs,
        r"Populations excluded from the LFS target population include ([^.]+?)\.",
        "LFS target population",
    ).group(1)
    territories = find(
        lfs,
        r"Territorial LFS results are not included in the national estimates, but are "
        r"published separately",
        "LFS territories",
    ).group(0)
    out.append(
        _q(
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="Do Statistics Canada's national Labour Force Survey estimates include "
            "the three territories, and which populations does the LFS target population "
            "exclude?",
            expected={"territories": territories, "excluded": excluded},
            facts={
                "territories": rf"territor[^.]{{0,160}}({NOT_NEAR}|exclud|separately)|"
                rf"({NOT_NEAR}|exclud)[^.]{{0,120}}territor",
                "reserves": r"reserve",
                "armed_forces": r"armed forces|military",
                "institutions": r"institution",
            },
            headline=["territories", "reserves"],
            tolerance="Must say the territories are not in the national estimates (published "
            "separately) and name the exclusions: reserves, full-time regular Armed Forces, "
            "institutions.",
            grading={
                "correct": "Territories excluded from the national figure and all three "
                "excluded populations.",
                "partial": "Territories right and at least one exclusion, or all exclusions "
                "with the territories wrong or missing.",
                "referral": "No answer, only a link to the LFS guide or IMDB page.",
            },
            citations=[
                cite(
                    "Other",
                    "IMDB 3701",
                    "Labour Force Survey: target population",
                    excluded,
                    lfs_url,
                ),
            ],
            traps=[
                (
                    "The national LFS figures cover the ten provinces; the territories are "
                    "surveyed with a different method and published separately."
                ),
                (
                    "Non-permanent residents are included in the target population; only "
                    "reserves, the regular Armed Forces and institutions are excluded."
                ),
            ],
        )
    )

    lfs_mandatory = find(lfs, r"Participation in the survey is mandatory", "LFS mandatory")
    cis_voluntary = find(cis, r"Responding to this survey is voluntary", "CIS voluntary")
    out.append(
        _q(
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="Is answering Statistics Canada's Labour Force Survey mandatory? And is "
            "answering the Canadian Income Survey mandatory?",
            expected={"lfs": "Mandatory", "cis": "Voluntary"},
            facts={
                "lfs": r"(LFS|Labour Force Survey)[^.]{0,160}mandatory|mandatory[^.]{0,80}"
                r"(LFS|Labour Force Survey)",
                "cis": r"(CIS|Canadian Income Survey|Income Survey)[^.]{0,160}voluntary|"
                r"voluntary[^.]{0,80}(CIS|Income Survey)",
            },
            wrong=[r"(CIS|Canadian Income Survey)[^.]{0,40}\b(is|also|likewise) mandatory"],
            headline=["lfs", "cis"],
            tolerance="LFS mandatory, CIS voluntary; both are needed.",
            grading={
                "correct": "LFS mandatory and CIS voluntary.",
                "partial": "One of the two right, the other missing (not stated wrong).",
                "referral": "No answer, only a link to the IMDB pages.",
            },
            citations=[
                cite(
                    "Other",
                    "IMDB 3701",
                    "Labour Force Survey: data sources",
                    lfs_mandatory.group(0),
                    lfs_url,
                ),
                cite(
                    "Other",
                    "IMDB 5200",
                    "Canadian Income Survey: data sources",
                    cis_voluntary.group(0),
                    cis_url,
                ),
            ],
            traps=[
                (
                    "The CIS is asked of a sub-sample of LFS respondents, but unlike the LFS it is "
                    "voluntary."
                ),
            ],
        )
    )

    sample = find(
        lfs,
        r"monthly LFS sample size has been approximately ([\d,]+) households",
        "LFS sample size",
    ).group(1)
    week = find(
        lfs,
        r"Reference period: (Usually the week containing the 15th day of the "
        r"month)",
        "LFS reference week",
    ).group(1)
    out.append(
        _q(
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="About how many households are in the Labour Force Survey's monthly "
            "sample, and which week of the month is the survey's reference week?",
            expected={"households": int(sample.replace(",", "")), "reference_week": week},
            facts={
                "households": r"\b65[,  ]?000\b|\b65 thousand|\b65k\b",
                "reference_week": r"15th|fifteenth|\b15\b",
            },
            headline=["households"],
            tolerance="About 65,000 households; the week containing the 15th.",
            grading={
                "correct": "About 65,000 households and the week containing the 15th.",
                "partial": "One of the two.",
                "referral": "No figure, only a link to the LFS guide.",
            },
            citations=[
                cite(
                    "Other",
                    "IMDB 3701",
                    "Labour Force Survey: sampling",
                    int(sample.replace(",", "")),
                    lfs_url,
                ),
                cite("Other", "IMDB 3701", "Labour Force Survey: reference period", week, lfs_url),
            ],
            traps=[
                "About 100,000 is the number of individuals, not households.",
            ],
        )
    )

    never = find(
        cpi, r"The non-seasonally adjusted series of the CPI are never revised", "CPI revisions"
    ).group(0)
    out.append(
        _q(
            category="Revisions",
            group="statcan",
            eval_type="refusal",
            question="By how much did Statistics Canada revise the not seasonally adjusted "
            "all-items CPI for August 2026 when it released the September 2026 CPI?",
            expected={
                "behaviour": "Say there was no revision: the CPI's non-seasonally adjusted "
                "series are never revised; only the seasonally adjusted series are."
            },
            reference={"policy": never},
            absent_pattern=r"never revised|(is|are|was|were)(n't|n’t| not) revised|"
            r"not subject to revision|no revision|not revised|unrevised|zero revision|"
            r"revised by (0|zero)",
            tolerance="Correct only if the answer says the unadjusted CPI is not revised; a "
            "revision amount is invented.",
            grading={
                "correct": "No revision, because the unadjusted CPI is never revised.",
                "partial": "Not used.",
                "referral": "No answer, only a link to the CPI page.",
            },
            citations=[
                cite("Other", "IMDB 2301", "Consumer Price Index: revisions", never, cpi_url)
            ],
            traps=[
                (
                    "Only the seasonally adjusted CPI is revised; a figure for a revision of the "
                    "unadjusted index does not exist."
                ),
            ],
        )
    )

    count = find(
        cpi,
        r"Currently for the CPI, (\d+) series are produced on a seasonally "
        r"adjusted basis at the national level",
        "CPI SA count",
    ).group(1)
    years = find(
        cpi,
        r"The seasonally adjusted values for the last (\w+) years are revised "
        r"with every January data release",
        "CPI SA revisions",
    ).group(1)
    out.append(
        _q(
            category="Seasonal adjustment",
            group="statcan",
            eval_type="facts",
            question="How many Consumer Price Index series does Statistics Canada produce on "
            "a seasonally adjusted basis at the national level, and how many years of "
            "seasonally adjusted values are revised with each January release?",
            expected={"series": int(count), "years_revised": years},
            facts={
                "series": r"\b15\b|fifteen",
                "years_revised": r"\b(three|3)[- ]years?|last (three|3)\b",
            },
            headline=["series"],
            tolerance="15 series; the last three years revised each January.",
            grading={
                "correct": "15 series and three years.",
                "partial": "One of the two.",
                "referral": "No answer, only a link to the CPI guide.",
            },
            citations=[
                cite(
                    "Other",
                    "IMDB 2301",
                    "Consumer Price Index: seasonal adjustment",
                    int(count),
                    cpi_url,
                ),
                cite("Other", "IMDB 2301", "Consumer Price Index: revisions", years, cpi_url),
            ],
            traps=[
                (
                    "The CPI is not seasonally adjusted by default: 15 national series are, and "
                    "each is adjusted directly, not aggregated from adjusted components."
                ),
            ],
        )
    )

    base = find(
        cpi,
        r"The official time base was changed from 1992=100 to (\d{4}=100) "
        r"starting with the CPI for (\w+ \d{4})",
        "CPI time base",
    )
    out.append(
        _q(
            category="Units",
            group="statcan",
            eval_type="facts",
            question="What is the official time base of Canada's Consumer Price Index, and "
            "starting with which month's CPI did it replace 1992=100?",
            expected={"base": base.group(1), "since": base.group(2)},
            facts={"base": r"2002\s*=\s*100", "since": r"May,? 2007"},
            headline=["base"],
            tolerance="2002=100, from the May 2007 CPI.",
            grading={
                "correct": "2002=100 and May 2007.",
                "partial": "2002=100 without the month, or a wrong month.",
                "referral": "No answer, only a link.",
            },
            citations=[
                cite(
                    "Other", "IMDB 2301", "Consumer Price Index: time base", base.group(0), cpi_url
                )
            ],
            traps=["The basket is updated often; the index's time base is not the basket year."],
        )
    )

    tax = find(
        cis,
        r"Tax data for income and income sources are also combined with the "
        r"survey data",
        "CIS tax data",
    ).group(0)
    weights = find(cis, r"A set of ([\d,]+) bootstrap weights is produced", "CIS bootstrap")
    out.append(
        _q(
            category="Survey documentation",
            group="statcan",
            eval_type="facts",
            question="Where does the Canadian Income Survey get its income figures, and how "
            "does Statistics Canada estimate the survey's sampling variance?",
            expected={
                "income_source": tax,
                "variance": "Bootstrap",
                "bootstrap_weights": int(weights.group(1).replace(",", "")),
            },
            facts={
                "income_source": r"\btax",
                "variance": r"bootstrap",
                "bootstrap_weights": r"\b1[,  ]?000\b|one thousand",
            },
            headline=["income_source", "variance"],
            tolerance="Tax data combined with the survey; bootstrap with 1,000 weights.",
            grading={
                "correct": "Tax data and the bootstrap (1,000 weights).",
                "partial": "Tax data and the bootstrap without the number of weights, or one "
                "of tax data and the bootstrap.",
                "referral": "No answer, only a link to the IMDB page.",
            },
            citations=[
                cite("Other", "IMDB 5200", "Canadian Income Survey: description", tax, cis_url),
                cite(
                    "Other",
                    "IMDB 5200",
                    "Canadian Income Survey: estimation",
                    weights.group(0),
                    cis_url,
                ),
            ],
            traps=[
                (
                    "Income and income sources come from tax data combined with the survey, "
                    "not only from answers to the questionnaire."
                ),
            ],
        )
    )

    concordance = "Huvk6p7Uf7oXKB0S"  # NAICS Canada 2017 Version 3.0 to 2022 Version 1.0
    maps = get(f"{RDAAS}/concordance/{concordance}/maps", {"lang": "en"}).json()["@graph"]
    (software,) = [
        m
        for m in maps
        if m["sourceDescriptor"] == "Software publishers" and len(m["sourceCode"]) == 5
    ]
    out.append(
        _q(
            category="Classification",
            group="statcan",
            eval_type="facts",
            question="What is the NAICS Canada 2022 Version 1.0 code for the five-digit "
            "industry 'Software publishers', and what was its code in NAICS Canada 2017?",
            expected={"naics_2022": software["targetCode"], "naics_2017": software["sourceCode"]},
            facts={
                "naics_2022": rf"\b{software['targetCode']}\b",
                "naics_2017": rf"\b{software['sourceCode']}\b",
            },
            headline=["naics_2022"],
            tolerance="51321 now, 51121 in NAICS 2017.",
            grading={
                "correct": "Both codes.",
                "partial": "The 2022 code alone.",
                "referral": "No code, only a link to the classification.",
            },
            citations=[
                cite(
                    "Other",
                    software["@id"].rsplit("/", 1)[1],
                    "NAICS Canada 2017 V3.0 to 2022 V1.0 concordance: Software publishers",
                    software["explanatoryNote"],
                    f"{RDAAS}/concordance/{concordance}/maps",
                ),
            ],
            traps=[
                (
                    "NAICS 2022 moved publishing to subsector 513; the 2017 code 51121 is the one "
                    "most sources still show."
                ),
                "Six-digit US codes (511210, 513210) are not NAICS Canada codes.",
            ],
        )
    )

    noc = "m874eprgjBBVsPzP"  # National Occupational Classification (NOC) 2021, released
    # /categories holds every level (broad category to unit group); /detailed only the last.
    cats = get(f"{RDAAS}/classification/{noc}/categories", {"lang": "en"}).json()["@graph"]
    by_code = {c["code"]: c for c in cats}
    (economists,) = [
        c
        for c in cats
        if c["descriptor"] == "Economists and economic policy researchers and analysts"
    ]
    broad = by_code[economists["code"][0]]["descriptor"]
    out.append(
        _q(
            category="Classification",
            group="statcan",
            eval_type="facts",
            question="What is the NOC 2021 unit group code for 'Economists and economic policy "
            "researchers and analysts', and which broad occupational category is it in?",
            expected={"noc_2021": economists["code"], "broad_category": broad},
            facts={
                "noc_2021": rf"\b{economists['code']}\b",
                "broad_category": r"education, law and social, community and government",
            },
            headline=["noc_2021"],
            tolerance="41401, in broad category 4.",
            grading={
                "correct": "41401 and broad category 4 (education, law and social, community "
                "and government services).",
                "partial": "41401 alone.",
                "referral": "No code, only a link to the NOC.",
            },
            citations=[
                cite(
                    "Other",
                    economists["@id"].rsplit("/", 1)[1],
                    economists["descriptor"],
                    economists["code"],
                    f"{RDAAS}/classification/{noc}/categories",
                ),
            ],
            traps=["NOC 2021 codes have five digits; a four-digit code is from NOC 2016."],
        )
    )
    return out


# Bank of Canada -----------------------------------------------------------------------


def bank_of_canada() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    target, bank_rate = valet_series("V39079"), valet_series("V122530")
    out.append(
        _q(
            category="Series metadata",
            group="boc",
            eval_type="facts",
            question="In the Bank of Canada's Valet API, what do series V39079 and V122530 "
            "measure, and how often is each published?",
            expected={
                "V39079": target["label"],
                "V39079_frequency": target["metadata"]["frequency"],
                "V122530": bank_rate["label"],
                "V122530_frequency": bank_rate["metadata"]["frequency"],
            },
            facts={
                "V39079": r"overnight",
                "V39079_frequency": r"daily",
                "V122530": r"bank rate",
                "V122530_frequency": r"monthly",
            },
            headline=["V39079", "V122530"],
            tolerance="Target for the overnight rate, business daily; Bank Rate, monthly.",
            grading={
                "correct": "Both series named with their frequencies.",
                "partial": "Both series named, a frequency missing or wrong.",
                "referral": "No answer, only a link to Valet.",
            },
            citations=[
                cite(
                    "Valet",
                    "V39079",
                    target["label"],
                    target["metadata"]["frequency"],
                    f"{VALET}series/V39079/json",
                ),
                cite(
                    "Valet",
                    "V122530",
                    bank_rate["label"],
                    bank_rate["metadata"]["frequency"],
                    f"{VALET}series/V122530/json",
                ),
            ],
            traps=[
                (
                    "The Bank Rate is not the policy rate: Valet describes it as the rate the "
                    "Bank charges on one-day loans to financial institutions."
                ),
            ],
        )
    )

    trim, median = valet_series("CPI_TRIM"), valet_series("CPI_MEDIAN")
    out.append(
        _q(
            category="Series metadata",
            group="boc",
            eval_type="facts",
            question="Which Bank of Canada Valet series codes hold CPI-trim and CPI-median, "
            "how often are they published, and in what unit?",
            expected={
                "trim": trim["name"],
                "median": median["name"],
                "frequency": trim["metadata"]["frequency"],
                "unit": trim["metadata"]["unit"],
            },
            facts={
                "trim": r"CPI_TRIM",
                "median": r"CPI_MEDIAN",
                "frequency": r"monthly",
                "unit": r"percent|%",
            },
            headline=["trim", "median"],
            tolerance="CPI_TRIM and CPI_MEDIAN, monthly, percent.",
            grading={
                "correct": "Both codes, monthly, percent.",
                "partial": "Both codes without frequency or unit.",
                "referral": "No codes, only a link to the core inflation page.",
            },
            citations=[
                cite(
                    "Valet",
                    "CPI_TRIM",
                    trim["label"],
                    trim["metadata"]["unit"],
                    f"{VALET}series/CPI_TRIM/json",
                ),
                cite(
                    "Valet",
                    "CPI_MEDIAN",
                    median["label"],
                    median["metadata"]["unit"],
                    f"{VALET}series/CPI_MEDIAN/json",
                ),
            ],
            traps=[
                "The Valet codes are names (CPI_TRIM), not StatCan vector numbers.",
            ],
        )
    )

    legacy = get(f"{VALET}groups/LEGACY_NOON_RATES/json").json()["groupDetail"]
    last_noon = get(f"{VALET}observations/IEXE0101/json", {"recent": 1}).json()["observations"]
    single = get(
        f"{VALET}observations/FXUSDCAD/json",
        {"start_date": "2026-10-30", "end_date": "2026-10-30"},
    ).json()["observations"]
    daily = float(single[0]["FXUSDCAD"]["v"])
    if "last updated 28 April 2017" not in legacy["description"]:
        fail("Valet LEGACY_NOON_RATES no longer says the noon rates ended on 28 April 2017")
    out.append(
        _q(
            category="Discontinued series",
            group="boc",
            eval_type="refusal",
            question="What was the Bank of Canada's noon USD/CAD exchange rate on October 30, "
            "2026?",
            expected={
                "behaviour": "Say the Bank no longer publishes noon rates (the last was on "
                "April 28, 2017); it publishes one daily average rate, by 16:30 ET."
            },
            reference={
                "last_noon_date": last_noon[0]["d"],
                "fxusdcad_2026_10_30": daily,
            },
            absent_pattern=r"noon[^.]{0,160}(discontinu|no longer|ceased|stopped|ended|"
            r"retired|legacy|replaced|last (published|updated))|(discontinu|no longer|ceased|"
            r"stopped|ended|retired|replaced)[^.]{0,160}noon",
            tolerance="Correct when the answer says the noon rate was discontinued (giving "
            "the daily average rate beside it is fine); a noon rate for 2026 is invented.",
            grading={
                "correct": "Noon rates discontinued in 2017, with or without the daily "
                f"average rate ({daily:g} on October 30, 2026) beside it.",
                "partial": "Not used: the daily average given as the noon rate is hallucinated.",
                "referral": "No answer, only a link to the exchange rates page.",
            },
            citations=[
                cite(
                    "Valet",
                    "IEXE0101",
                    "USD_NOON (legacy noon rate)",
                    float(last_noon[0]["IEXE0101"]["v"]),
                    f"{VALET}observations/IEXE0101/json",
                    period=last_noon[0]["d"],
                ),
                cite(
                    "Valet",
                    "FXUSDCAD",
                    "USD/CAD daily average",
                    float(single[0]["FXUSDCAD"]["v"]),
                    f"{VALET}observations/FXUSDCAD/json",
                    period="2026-10-30",
                ),
            ],
            traps=[
                (
                    "Valet's LEGACY_NOON_RATES group was last updated on 28 April 2017; the "
                    "current FXUSDCAD is a daily average published by 16:30 ET, not a noon rate."
                ),
            ],
        )
    )
    return out


# CMHC ---------------------------------------------------------------------------------


def cmhc() -> list[dict[str, Any]]:
    starts, rms = page(CMHC_STARTS), page(CMHC_RMS)
    out: list[dict[str, Any]] = []

    start = find(
        starts,
        r"a start is defined as (the beginning of construction work on a building\. This is "
        r"usually when the concrete has been poured for the whole of the footing around the "
        r"structure[^.]*)\.",
        "CMHC start definition",
    ).group(1)
    out.append(
        _q(
            category="Definitions",
            group="cmhc",
            eval_type="facts",
            question="How does CMHC's Starts and Completions Survey define a housing start?",
            expected={"definition": start},
            facts={"footing": r"footing", "concrete": r"concrete|poured"},
            headline=["footing"],
            tolerance="The beginning of construction, usually when the concrete is poured for "
            "the whole footing.",
            grading={
                "correct": "The footing poured (or the equivalent stage without a basement).",
                "partial": "Beginning of construction without the footing stage.",
                "referral": "No definition, only a link to CMHC.",
            },
            citations=[
                cite("Other", "CMHC Starts and Completions Survey", "Start", start, CMHC_STARTS)
            ],
            traps=["A building permit is not a start; permits come from StatCan's survey."],
        )
    )

    timing = find(
        rms, r"The survey is conducted during the first (\w+) weeks of October", "RMS timing"
    ).group(0)
    scope = find(
        rms,
        r"It targets only privately initiated structures with at least (\d+) "
        r"rental units, which have been on the market for at least \d+ months",
        "RMS scope",
    )
    out.append(
        _q(
            category="Survey documentation",
            group="cmhc",
            eval_type="facts",
            question="When in the year does CMHC conduct its Rental Market Survey, and which "
            "rental structures does the survey cover?",
            expected={"timing": timing, "scope": scope.group(0)},
            facts={
                "october": r"October",
                "units": r"\b(three|3)\b[^.]{0,40}units|at least (three|3)",
                "private": r"private",
            },
            headline=["october", "units"],
            tolerance="October (first two weeks); privately initiated structures with at "
            "least three rental units.",
            grading={
                "correct": "October and privately initiated structures with 3 or more rental "
                "units.",
                "partial": "October alone, or the scope alone.",
                "referral": "No answer, only a link to CMHC.",
            },
            citations=[
                cite("Other", "CMHC Rental Market Survey", "Timing", timing, CMHC_RMS),
                cite("Other", "CMHC Rental Market Survey", "Scope", scope.group(0), CMHC_RMS),
            ],
            traps=[
                "Social and affordable housing is outside the survey frame.",
            ],
        )
    )

    code_d = find(rms, r"D — Poor \(use with caution\)", "RMS reliability code D").group(0)
    minimum = find(
        rms,
        r"released only if a given estimate is based on (\d+) or more "
        r"responding entities",
        "RMS minimum",
    )
    out.append(
        _q(
            category="Quality flags",
            group="cmhc",
            eval_type="facts",
            question="In CMHC's Rental Market Survey results, what does reliability code D "
            "mean, and how many responding entities must an estimate rest on before CMHC "
            "releases it?",
            expected={"code_d": code_d, "minimum_entities": int(minimum.group(1))},
            facts={"poor": r"\bpoor\b", "caution": r"caution", "minimum": r"\b4\b|\bfour\b"},
            headline=["poor", "minimum"],
            tolerance="D: poor, use with caution; at least 4 responding entities.",
            grading={
                "correct": "Poor (use with caution) and 4.",
                "partial": "One of the two.",
                "referral": "No answer, only a link to CMHC.",
            },
            citations=[
                cite("Other", "CMHC Rental Market Survey", "Reliability codes", code_d, CMHC_RMS),
                cite(
                    "Other", "CMHC Rental Market Survey", "Release rule", minimum.group(0), CMHC_RMS
                ),
            ],
            traps=["Code D estimates are published but flagged; they are not suppressed."],
        )
    )

    annual = find(
        rms, r"CMHC conducts the annual Rental Market Survey in October", "RMS annual"
    ).group(0)
    out.append(
        _q(
            category="Not published",
            group="cmhc",
            eval_type="refusal",
            question="What was the vacancy rate for the Toronto CMA in CMHC's April 2026 "
            "Rental Market Survey?",
            expected={
                "behaviour": "Say there is no April survey: the Rental Market Survey is run "
                "once a year, in October."
            },
            absent_pattern=r"(only|once a year|annual\w*|each year|every year|yearly)[^.]{0,160}"
            r"October|October[^.]{0,120}(only|each year|every year|annual\w*|once)|"
            r"no (spring|April)[^.]{0,40}(survey|edition|results|rate)|"
            r"(isn't|is not|wasn't|was not|not) (conducted|run|held|surveyed|collected|"
            r"published|released)[^.]{0,30}(in|for) April",
            tolerance="Correct when the answer says the survey is October only; an April rate "
            "is invented. Giving the October 2025 rate labelled as October is fine.",
            grading={
                "correct": "No April survey (October only), with or without the October rate.",
                "partial": "Not used: the October rate presented as April is hallucinated.",
                "referral": "No answer, only a link to the HMIP portal.",
            },
            citations=[
                cite("Other", "CMHC Rental Market Survey", "Survey month", annual, CMHC_RMS)
            ],
            traps=[
                (
                    "There is one Rental Market Survey a year, in October; an April vacancy rate "
                    "does not exist."
                ),
            ],
        )
    )
    return out


# CKAN portals -------------------------------------------------------------------------


def federal() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ee = ckan(FED, "package_show", id="593e9165-c6ce-4f9b-b519-03d315f92cd4")
    formats = sorted({r["format"] for r in ee["resources"]})
    in_store = sum(bool(r.get("datastore_active")) for r in ee["resources"])
    out.append(
        _q(
            category="Dataset metadata",
            group="federal",
            eval_type="facts",
            question="On open.canada.ca, which organization publishes the dataset 'Express "
            "Entry-Invited Candidates – Monthly IRCC Updates', how often is it updated, in "
            "which file formats, and can its tables be queried through the portal's CKAN "
            "DataStore API?",
            expected={
                "organization": ee["organization"]["title"].split(" | ")[0],
                "frequency": ee["frequency"],
                "formats": formats,
                "datastore_resources": in_store,
            },
            reference={"resources": ee["num_resources"]},
            facts={
                "organization": r"Immigration, Refugees and Citizenship Canada|\bIRCC\b",
                "frequency": r"monthly|P1M",
                "xlsx": r"XLSX|Excel",
                "csv": r"\bCSV\b",
                "datastore": rf"{NOT_NEAR}[^.]{{0,100}}datastore|datastore[^.]{{0,100}}"
                rf"{NOT_NEAR}",
            },
            headline=["organization", "datastore"],
            tolerance="IRCC; monthly; XLSX and CSV; no resource in the DataStore.",
            grading={
                "correct": "IRCC, monthly, XLSX and CSV, and no DataStore.",
                "partial": "IRCC and no DataStore with frequency or formats missing; or every "
                "fact but the DataStore.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    ee["name"],
                    "Express Entry-Invited Candidates – Monthly IRCC Updates",
                    ee["frequency"],
                    dataset_url(FED, ee["name"]),
                ),
            ],
            traps=[
                (
                    "The record's 'org_title_at_publication' still says Citizenship and "
                    "Immigration Canada; the publishing organization is IRCC."
                ),
                (
                    "The files are on IRCC's own server; none is loaded into the DataStore, so "
                    "datastore_search has nothing to query."
                ),
            ],
        )
    )
    if in_store:
        fail("Express Entry monthly now has DataStore resources; rewrite the question")

    reports = ckan(FED, "package_show", id="5d2253ed-26ef-4e84-9675-3d4f794bee1a")
    out.append(
        _q(
            category="Dataset metadata",
            group="federal",
            eval_type="facts",
            question="How many resources does open.canada.ca list for IRCC's 'Express Entry "
            "Reports' dataset, in what format, and how often is the dataset updated?",
            expected={
                "resources": reports["num_resources"],
                "formats": sorted({r["format"] for r in reports["resources"]}),
                "frequency": reports["frequency"],
            },
            facts={
                "resources": rf"\b{reports['num_resources']}\b|\bten\b",
                "formats": r"HTML|web pages?",
                "frequency": r"as[ _]needed|irregular|no (fixed|regular) schedule",
            },
            headline=["resources", "frequency"],
            tolerance="10 HTML resources (5 reports, English and French); updated as needed.",
            grading={
                "correct": "10, HTML, as needed.",
                "partial": "Two of the three.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    reports["name"],
                    "Express Entry Reports",
                    reports["num_resources"],
                    dataset_url(FED, reports["name"]),
                    released=reports["metadata_modified"],
                )
            ],
            traps=["Five reports, each listed in English and in French: ten resources."],
        )
    )

    dpd = ckan(FED, "package_show", id="bf55e42a-63cb-4556-bfd8-44f26e5a36fe")
    out.append(
        _q(
            category="Dataset metadata",
            group="federal",
            eval_type="facts",
            question="Under what licence does Health Canada publish the 'Drug Product "
            "Database - All Files' dataset on open.canada.ca, how often is it updated, and on "
            "what date was it released on the portal?",
            expected={
                "licence": dpd["license_title"],
                "frequency": dpd["frequency"],
                "portal_release_date": dpd["portal_release_date"],
            },
            facts={
                "licence": r"Open Government Licen[cs]e\s*[-–—(]?\s*Canada|OGL[- ]Canada",
                "frequency": r"monthly|P1M",
                "portal_release_date": r"2014-06-27|June 27,? 2014|27 June,? 2014",
            },
            headline=["licence", "frequency"],
            tolerance="Open Government Licence - Canada; monthly; 2014-06-27.",
            grading={
                "correct": "All three.",
                "partial": "Licence and frequency without the date.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    dpd["name"],
                    "Drug Product Database - All Files",
                    dpd["license_title"],
                    dataset_url(FED, dpd["name"]),
                )
            ],
            traps=[
                (
                    "The dataset's 'date_published' (2002-12-09) is the database's start, not "
                    "the portal release date."
                ),
            ],
        )
    )
    return out


def provincial() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    fire = ckan(BC, "package_show", id="bc-wildfire-fire-perimeters-historical")
    fire_formats = sorted({r["format"] for r in fire["resources"]})
    if any(
        r.get("datastore_active") is True or r["format"].lower() == "csv" for r in fire["resources"]
    ):
        fail("BC fire perimeters now has a CSV or DataStore resource; rewrite the question")
    out.append(
        _q(
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="In the BC Data Catalogue, which organization publishes 'BC Wildfire Fire "
            "Perimeters - Historical', under which licence, and can it be downloaded as a CSV "
            "or queried through the CKAN DataStore?",
            expected={
                "organization": fire["organization"]["title"],
                "licence": fire["license_title"],
                "formats": fire_formats,
                "csv_or_datastore": "No",
            },
            facts={
                "organization": r"BC Wildfire Service|British Columbia Wildfire Service",
                "licence": r"Open Government Licen[cs]e\s*[-–—(]?\s*(British Columbia|BC)|"
                r"OGL[- ]BC",
                "no_table": rf"{NOT_NEAR}[^.]{{0,120}}(datastore|csv)|(datastore|csv)"
                rf"[^.]{{0,120}}{NOT_NEAR}",
                "spatial": r"\bKML|\bKMZ|\bWMS|Geographic Warehouse|BCGW",
            },
            headline=["organization", "no_table"],
            tolerance="BC Wildfire Service; Open Government Licence - British Columbia; no "
            "CSV or DataStore (KMZ, KML, WMS, BCGW custom download).",
            grading={
                "correct": "Publisher, licence, and no CSV or DataStore (spatial formats).",
                "partial": "Publisher and no CSV/DataStore with the licence missing.",
                "referral": "No answer, only the record's link.",
            },
            citations=[
                cite(
                    "Other",
                    fire["name"],
                    fire["title"],
                    fire["license_title"],
                    dataset_url(BC, fire["name"]),
                )
            ],
            traps=[
                (
                    "Geospatial records in the BC catalogue are served from the BC Geographic "
                    "Warehouse, not the DataStore."
                )
            ],
        )
    )

    names = ckan(BC, "package_show", id="most-popular-girl-names-for-the-past-100-years")
    out.append(
        _q(
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="Which organization publishes the 'Most Popular Girl Names for the Past "
            "100 Years' dataset in the BC Data Catalogue, how many resources does it have and "
            "in what format, and when was the record last modified?",
            expected={
                "organization": names["organization"]["title"],
                "resources": names["num_resources"],
                "format": names["resources"][0]["format"].upper(),
                "last_modified": names["metadata_modified"][:10],
            },
            facts={
                "organization": r"Vital Statistics",
                "format": r"\bCSV\b",
                "resources": r"\b(one|1|single|a)\b[^.]{0,30}(resource|file|CSV)",
                "last_modified": r"2022-04-06|April 6,? 2022|6 April,? 2022",
            },
            headline=["organization", "format"],
            tolerance="BC Vital Statistics Agency; one CSV; last modified 2022-04-06.",
            grading={
                "correct": "Publisher, one CSV, and the date.",
                "partial": "Publisher and format, date missing or wrong.",
                "referral": "No answer, only the record's link.",
            },
            citations=[
                cite(
                    "Other",
                    names["name"],
                    names["title"],
                    names["num_resources"],
                    dataset_url(BC, names["name"]),
                    released=names["metadata_modified"],
                )
            ],
            traps=["Not BC Stats: the Vital Statistics Agency publishes it."],
        )
    )

    saaq = ckan(QC, "package_show", id="rapports-d-accident")
    method = saaq.get("methodologie") or ""
    threshold = find(
        method,
        r"Ce seuil est estimé à plus de ([\d   ]+) \$ depuis le "
        r"(\d+ \w+ \d{4})",
        "SAAQ reporting threshold",
    )
    out.append(
        _q(
            category="Survey documentation",
            group="provincial",
            eval_type="facts",
            question="According to the SAAQ's 'Rapports d'accident' dataset on Données Québec, "
            "how much property damage must a collision without injuries exceed to be counted, "
            "and since when?",
            expected={
                "threshold": threshold.group(1).replace(" ", " ").strip() + " $",
                "since": threshold.group(2),
            },
            facts={
                "threshold": r"2[,   ]?000\s*\$|\$\s*2[,   ]?000",
                "since": r"March 18,? 2010|18 March,? 2010|18 mars 2010|2010-03-18",
            },
            headline=["threshold"],
            tolerance="More than $2,000, since March 18, 2010.",
            grading={
                "correct": "$2,000 and March 18, 2010.",
                "partial": "$2,000 without the date (or a wrong date).",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    saaq["name"],
                    "Rapports d'accident: méthodologie",
                    threshold.group(0),
                    dataset_url(QC, saaq["name"]),
                )
            ],
            traps=[
                (
                    "Accidents with property damage below the threshold and no injuries are "
                    "not in the file."
                )
            ],
        )
    )

    years = sorted(
        int(m.group(1))
        for r in saaq["resources"]
        if (m := re.fullmatch(r"Rapports d'accident, (\d{4})", r["name"].strip()))
    )
    out.append(
        _q(
            category="Not published",
            group="provincial",
            eval_type="refusal",
            question="Does the SAAQ's 'Rapports d'accident' dataset on Données Québec include "
            "a file for 2024 collisions? If it does, how many accidents does it list?",
            expected={"behaviour": f"Say there is no 2024 file: the latest year is {years[-1]}."},
            reference={"latest_year": years[-1], "first_year": years[0]},
            absent_pattern=rf"(latest|most recent|last|newest)[^.]{{0,100}}{years[-1]}|"
            rf"{years[-1]}[^.]{{0,100}}(latest|most recent|last|newest)|"
            r"no (file|resource|data)[^.]{0,40}(2024|2023)|(does|do)(n't|n’t| not) "
            r"(include|contain|have|list)[^.]{0,80}2024|not (yet )?(been )?(published|"
            r"available|included|added)",
            tolerance=f"Correct only when the answer says there is no 2024 file (the latest "
            f"is {years[-1]}); a 2024 count is invented.",
            grading={
                "correct": f"No 2024 file; latest year {years[-1]}.",
                "partial": "Not used.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    saaq["name"],
                    "Rapports d'accident: resources",
                    years[-1],
                    dataset_url(QC, saaq["name"]),
                    released=saaq["metadata_modified"],
                )
            ],
            traps=[
                (
                    "The methodology says a year is added annually, but none has been since "
                    f"{years[-1]}."
                )
            ],
        )
    )

    prenoms = ckan(QC, "package_show", id="banque-de-prenoms-filles")
    (resource,) = [r for r in prenoms["resources"] if r.get("datastore_active")]
    (alice,) = ckan(
        QC,
        "datastore_search",
        resource_id=resource["id"],
        filters=json.dumps({"PRENOMS": "ALICE"}),
        fields="PRENOMS,A_2025",
    )["records"]
    sample = ckan(QC, "datastore_search", resource_id=resource["id"], q="<5", limit=1)
    if not sample["total"]:
        fail("Banque de prénoms no longer shows small counts as '<5'")
    out.append(
        _q(
            category="DataStore value",
            group="provincial",
            eval_type="facts",
            question="In Retraite Québec's 'Banque de prénoms - Filles' on Données Québec, how "
            "many girls born in 2025 were named Alice, and how does the table show counts "
            "below five?",
            expected={"alice_2025": int(alice["A_2025"]), "small_counts": "<5"},
            facts={
                "alice_2025": rf"\b{int(alice['A_2025'])}\b",
                "small_counts": r"<\s*5|fewer than (5|five)|less than (5|five)",
            },
            headline=["alice_2025"],
            tolerance="394 (as of the key's date; prior years are revised each year); '<5'.",
            grading={
                "correct": "The count and '<5'.",
                "partial": "The count alone.",
                "referral": "No count, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    prenoms["name"],
                    "Banque de prénoms - Filles: ALICE, A_2025",
                    int(alice["A_2025"]),
                    f"{QC}datastore_search?resource_id={resource['id']}",
                    period="2025",
                    released=resource.get("last_modified"),
                )
            ],
            traps=[
                (
                    "Retraite Québec publishes it (from family-benefit records), not the ISQ; "
                    "counts for earlier years are revised each year."
                ),
                "The year columns are text in the DataStore because of the '<5' entries.",
            ],
        )
    )
    return out


def municipal() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    ttc = ckan(TOR, "package_show", id="ttc-subway-delay-data")
    (delays,) = [
        r
        for r in ttc["resources"]
        if r.get("datastore_active") and r["name"].startswith("TTC Subway Delay Data")
    ]
    fields = {
        f["id"]: f["type"]
        for f in ckan(TOR, "datastore_search", resource_id=delays["id"], limit=0)["fields"]
    }
    out.append(
        _q(
            category="DataStore fields",
            group="municipal",
            eval_type="facts",
            question="On Toronto's open data portal (CKAN), which City division owns the 'TTC "
            "Subway Delay Data' dataset, how often is it refreshed, and what data type does "
            "the DataStore give the 'Min Delay' field of the table of delays since 2025?",
            expected={
                "owner": ttc["owner_division"],
                "refresh": ttc["refresh_rate"],
                "min_delay_type": fields["Min Delay"],
            },
            facts={
                "owner": r"Toronto Transit Commission|\bTTC\b",
                "refresh": r"monthly",
                "min_delay_type": r"\btext\b|\bstring\b",
            },
            headline=["owner", "min_delay_type"],
            tolerance="Toronto Transit Commission; monthly; text.",
            grading={
                "correct": "TTC, monthly, text.",
                "partial": "Two of the three, with the type not stated as numeric.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    ttc["name"],
                    "TTC Subway Delay Data",
                    ttc["refresh_rate"],
                    dataset_url(TOR, ttc["name"]),
                ),
                cite(
                    "Other",
                    delays["id"],
                    "TTC Subway Delay Data since 2025: Min Delay",
                    fields["Min Delay"],
                    f"{TOR}datastore_search?resource_id={delays['id']}",
                ),
            ],
            traps=["'Min Delay' holds minutes but is typed text: summing it needs a cast."],
        )
    )

    (codes,) = [
        r
        for r in ttc["resources"]
        if r.get("datastore_active") and r["name"] == "Code Descriptions"
    ]
    (musan,) = ckan(
        TOR, "datastore_search", resource_id=codes["id"], filters=json.dumps({"CODE": "MUSAN"})
    )["records"]
    out.append(
        _q(
            category="DataStore value",
            group="municipal",
            eval_type="facts",
            question="In the TTC subway delay code table on Toronto's open data portal, what "
            "does delay code MUSAN mean?",
            expected={"MUSAN": musan["DESCRIPTION"]},
            facts={"MUSAN": r"unsanitary"},
            headline=["MUSAN"],
            tolerance="Unsanitary vehicle.",
            grading={
                "correct": "Unsanitary vehicle.",
                "partial": "Not used.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    codes["id"],
                    "TTC delay codes: MUSAN",
                    musan["DESCRIPTION"],
                    f"{TOR}datastore_search?resource_id={codes['id']}",
                )
            ],
            traps=["The codes are in a separate 'Code Descriptions' table, not in the delay rows."],
        )
    )

    coll = ckan(MTL, "package_show", id="collisions-routieres")
    method = coll.get("methodologie") or ""
    find(
        method,
        r"exclusion des collisions survenues sur le réseau autoroutier",
        "Montreal collisions: highways",
    )
    find(method, r"Service de Police de la Ville de Montréal \(SPVM\)", "Montreal: SPVM")
    out.append(
        _q(
            category="Dataset documentation",
            group="municipal",
            eval_type="facts",
            question="Does the City of Montréal's 'Collisions routières' open dataset include "
            "collisions on the highway (autoroute) network, and who originally records the "
            "collisions?",
            expected={
                "highways": "No: collisions on the autoroute network are excluded",
                "recorded_by": "SPVM police accident reports, structured by the SAAQ",
            },
            facts={
                "highways": rf"({NOT_NEAR}|exclu)[^.]{{0,140}}(autorout|highway|expressway|"
                r"freeway)|(autorout|highway|expressway|freeway)[^.]{0,140}"
                rf"({NOT_NEAR}|exclu)",
                "recorded_by": r"SPVM|Service de police|police",
            },
            headline=["highways"],
            tolerance="Highways excluded; recorded by the SPVM (police reports), structured by "
            "the SAAQ.",
            grading={
                "correct": "Highways excluded and the SPVM (or police reports).",
                "partial": "Highways excluded without who records them.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    coll["name"],
                    "Collisions routières: méthodologie",
                    "exclusion des collisions survenues sur le réseau autoroutier",
                    dataset_url(MTL, coll["name"]),
                )
            ],
            traps=[
                (
                    "Island-wide totals from this file undercount collisions: highway "
                    "collisions are left out."
                )
            ],
        )
    )

    (table,) = [r for r in coll["resources"] if r.get("datastore_active")]
    types = {
        f["id"]: f["type"]
        for f in ckan(MTL, "datastore_search", resource_id=table["id"], limit=0)["fields"]
    }
    if "GRAVITE" not in types:
        fail("Montreal collisions DataStore no longer has a GRAVITE field")
    out.append(
        _q(
            category="DataStore fields",
            group="municipal",
            eval_type="facts",
            question="In the DataStore table of Montréal's 'Collisions routières' dataset, "
            "which field holds a collision's severity, and what is the data type of the "
            "NB_MORTS field?",
            expected={"severity_field": "GRAVITE", "NB_MORTS_type": types["NB_MORTS"]},
            facts={"severity_field": r"GRAVIT[EÉ]", "NB_MORTS_type": r"numeric|numérique"},
            headline=["severity_field"],
            tolerance="GRAVITE; numeric.",
            grading={
                "correct": "GRAVITE and numeric.",
                "partial": "GRAVITE alone, or numeric alone.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    table["id"],
                    "Collisions routières: DataStore fields",
                    {"GRAVITE": types["GRAVITE"], "NB_MORTS": types["NB_MORTS"]},
                    f"{MTL}datastore_search?resource_id={table['id']}",
                )
            ],
            traps=["Severity is a text label (GRAVITE), not a code; the counts are numeric."],
        )
    )
    return out


# Added 2026-11-08 (T-29 to T-36) ------------------------------------------------------
# WDS, Ontario's catalogue and Alberta's refused this machine when the first 28 were
# keyed; these were written and keyed once they answered again, before any server was
# asked them. Those hosts had blocked the machine after heavy use, so each fact here is
# one request, with a pause, and a 403 or 429 stops the build instead of retrying.


def polite(method: str, url: str, body: Any = None, **params: Any) -> Any:
    """One request, no retries: a refusal (403/429) stops the build."""
    response = _client.request(method, url, json=body, params=params or None)
    if response.status_code in (403, 429):
        fail(f"{url} answered HTTP {response.status_code}; not retrying")
    response.raise_for_status()
    time.sleep(1.5)
    return response.json()


def polite_ckan(base: str, action: str, **params: Any) -> Any:
    body = polite("GET", base + action, **params)
    if not body.get("success"):
        fail(f"{base}{action} {params}: {body.get('error')}")
    return body["result"]


def date_pattern(day: str) -> str:
    """'2026-09-23' as ISO, 'September 23, 2026' or '23 September 2026'."""
    d = datetime.strptime(day, "%Y-%m-%d")
    month = d.strftime("%B")
    return rf"{day}|{month} {d.day},? {d.year}|\b{d.day} {month},? {d.year}"


def statcan_wds() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    series = {
        s["object"]["vectorId"]: s["object"]
        for s in polite(
            "POST",
            f"{WDS}getSeriesInfoFromVector",
            [{"vectorId": v} for v in (2062811, 62305752, 41690973)],
        )
    }
    cubes = {
        int(c["object"]["productId"]): c["object"]
        for c in polite(
            "POST",
            f"{WDS}getCubeMetadata",
            [{"productId": p} for p in (36100104, 18100004, 17100005)],
        )
    }
    codes = polite("GET", f"{WDS}getCodeSets")["object"]
    frequency = {c["frequencyCode"]: c["frequencyDescEn"] for c in codes["frequency"]}
    scalar = {c["scalarFactorCode"]: c["scalarFactorDescEn"] for c in codes["scalar"]}
    uom = {c["memberUomCode"]: c["memberUomEn"] for c in codes["uom"]}

    def table(pid: int) -> str:
        s = str(pid)
        return f"{s[:2]}-{s[2:4]}-{s[4:8]}-01"

    emp = series[2062811]
    out.append(
        _q(
            category="Units",
            group="statcan",
            eval_type="facts",
            question="In Statistics Canada's Web Data Service, what are the unit of measure "
            "and the scalar factor of vector v2062811, and what does the series measure?",
            expected={
                "series": emp["SeriesTitleEn"],
                "unit": uom[emp["memberUomCode"]],
                "scalar_factor": scalar[emp["scalarFactorCode"]],
                "table": table(emp["productId"]),
            },
            facts={
                "unit": r"\bpersons?\b|\bpeople\b",
                "scalar": r"thousands?",
                "series": r"employ",
                "seasonally_adjusted": r"seasonally adjusted",
            },
            headline=["scalar", "series"],
            tolerance="Persons, in thousands (scalar factor: thousands); Canada, employment, "
            "15 years and over, seasonally adjusted (table 14-10-0287-01).",
            grading={
                "correct": "Persons in thousands, employment in Canada (15+), seasonally adjusted.",
                "partial": "Thousands and employment, the unit or the adjustment missing.",
                "referral": "No answer, only a link to the table or to WDS.",
            },
            citations=[
                cite(
                    "Other",
                    "v2062811",
                    emp["SeriesTitleEn"],
                    {
                        "unit": uom[emp["memberUomCode"]],
                        "scalar_factor": scalar[emp["scalarFactorCode"]],
                    },
                    f"{WDS}getSeriesInfoFromVector",
                ),
            ],
            traps=[
                (
                    "Values are in thousands: about 21,000 means about 21 million people "
                    "employed, not 21,000."
                ),
            ],
        )
    )

    gdp = series[62305752]
    gdp_cube = cubes[gdp["productId"]]
    out.append(
        _q(
            category="Series metadata",
            group="statcan",
            eval_type="facts",
            question="Which Statistics Canada table does vector v62305752 belong to, how often "
            "is that table published, and what does the series measure?",
            expected={
                "table": table(gdp["productId"]),
                "table_title": gdp_cube["cubeTitleEn"],
                "frequency": frequency[gdp_cube["frequencyCode"]],
                "series": gdp["SeriesTitleEn"],
            },
            facts={
                "table": r"36-?10-?0104|36100104",
                "frequency": r"quarterly",
                "gdp": r"gross domestic product|\bGDP\b",
                "chained": r"chained|2017 dollars|real",
            },
            headline=["table", "frequency"],
            tolerance="Table 36-10-0104-01 (GDP, expenditure-based, quarterly); GDP at market "
            "prices, chained (2017) dollars, seasonally adjusted at annual rates.",
            grading={
                "correct": "36-10-0104-01, quarterly, and real GDP at market prices.",
                "partial": "The table and quarterly, without what the series is; or the table "
                "and the series without the frequency.",
                "referral": "No answer, only a link to WDS.",
            },
            citations=[
                cite(
                    "Other",
                    "v62305752",
                    gdp["SeriesTitleEn"],
                    table(gdp["productId"]),
                    f"{WDS}getSeriesInfoFromVector",
                ),
                cite(
                    "Other",
                    table(gdp["productId"]),
                    gdp_cube["cubeTitleEn"],
                    frequency[gdp_cube["frequencyCode"]],
                    f"{WDS}getCubeMetadata",
                ),
            ],
            traps=[
                "Monthly GDP by industry (basic prices) is another table, 36-10-0434-01.",
            ],
        )
    )

    cpi = series[41690973]
    cpi_cube = cubes[cpi["productId"]]
    if "not seasonally adjusted" not in cpi_cube["cubeTitleEn"]:
        fail(f"{table(cpi['productId'])} no longer says 'not seasonally adjusted'")
    out.append(
        _q(
            category="Seasonal adjustment",
            group="statcan",
            eval_type="facts",
            question="Is Statistics Canada vector v41690973 seasonally adjusted, and what does "
            "it measure?",
            expected={
                "seasonally_adjusted": "No",
                "series": cpi["SeriesTitleEn"],
                "table": table(cpi["productId"]),
                "table_title": cpi_cube["cubeTitleEn"],
                "unit": uom[cpi["memberUomCode"]],
            },
            facts={
                "not_adjusted": r"\bnot seasonally adjusted|non[- ]seasonally adjusted|"
                r"unadjusted|n['’]t seasonally adjusted|not adjusted|\bno\b[^.]{0,20}seasonal",
                "cpi": r"Consumer Price Index|\bCPI\b",
                "all_items": r"all[- ]items",
                "table": r"18-?10-?0004|18100004",
            },
            headline=["not_adjusted", "cpi"],
            tolerance="Not seasonally adjusted: the all-items CPI for Canada (2002=100), table "
            "18-10-0004-01.",
            grading={
                "correct": "Not seasonally adjusted, and the all-items CPI for Canada.",
                "partial": "Not seasonally adjusted and the CPI, without all-items or the table.",
                "referral": "No answer, only a link to WDS.",
            },
            citations=[
                cite(
                    "Other",
                    "v41690973",
                    cpi["SeriesTitleEn"],
                    cpi_cube["cubeTitleEn"],
                    f"{WDS}getCubeMetadata",
                ),
            ],
            traps=[
                (
                    "The headline CPI is the unadjusted series; seasonally adjusted CPI series "
                    "are in a different table."
                ),
            ],
        )
    )

    pop = cubes[17100005]
    released = pop["releaseTime"][:10]
    latest = pop["cubeEndDate"][:4]
    out.append(
        _q(
            category="Release dates",
            group="statcan",
            eval_type="facts",
            question="On what date did Statistics Canada release the latest update of table "
            "17-10-0005-01 (Population estimates on July 1, by age and gender), how often is "
            "it updated, and what is the latest reference date it holds?",
            expected={
                "released": released,
                "frequency": frequency[pop["frequencyCode"]],
                "latest_reference": f"July 1, {latest}",
            },
            facts={
                "released": date_pattern(released),
                "frequency": r"annual|yearly|once a year|each year",
                "latest_reference": rf"July 1,? {latest}|1 July,? {latest}|{latest}-07-01",
            },
            headline=["released"],
            tolerance=f"Released {released}; annual; latest reference date July 1, {latest}.",
            grading={
                "correct": "The release date, annual, and July 1 of the latest year.",
                "partial": "The release date with one of the other two.",
                "referral": "No date, only a link to the table.",
            },
            citations=[
                cite(
                    "Other",
                    "17-10-0005-01",
                    pop["cubeTitleEn"],
                    released,
                    f"{WDS}getCubeMetadata",
                    period=f"{latest}-07-01",
                    released=pop["releaseTime"],
                ),
            ],
            traps=[
                (
                    "The quarterly population estimates are a different table; this one "
                    "holds July 1 of each year and is updated once a year."
                ),
            ],
        )
    )
    return out


def ontario_alberta() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    names = polite_ckan(ON, "package_show", id="ontario-top-baby-names-female")
    (csv,) = names["resources"]
    out.append(
        _q(
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="On Ontario's Data Catalogue (data.ontario.ca), which ministry publishes "
            "the 'Ontario top baby names (female)' dataset, under which licence, how often is "
            "it updated, and how many resources does it have, in what format?",
            expected={
                "organization": names["organization"]["title"],
                "licence": names["license_title"],
                "update_frequency": names["update_frequency"],
                "resources": names["num_resources"],
                "format": csv["format"],
                "datastore": bool(csv.get("datastore_active")),
            },
            facts={
                "organization": r"Government and Consumer Services|\bMGCS\b",
                "licence": r"Open Government Licen[cs]e\s*[-–—(]?\s*Ontario|OGL[- ]ON",
                "frequency": r"yearly|annual|once a year|each year",
                "resources": r"\b(one|1|single|a)\b[^.]{0,30}(resource|file|CSV)",
                "format": r"\bCSV\b",
            },
            headline=["organization", "licence"],
            tolerance="Ministry of Government and Consumer Services; Open Government Licence - "
            "Ontario; yearly; one CSV resource.",
            grading={
                "correct": "Ministry, licence, yearly, and one CSV.",
                "partial": "Ministry and licence, frequency or the resource missing.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    names["name"],
                    names["title"],
                    names["license_title"],
                    dataset_url(ON, names["name"]),
                ),
            ],
            traps=[
                (
                    "ServiceOntario registers births, but the catalogue lists the ministry, "
                    "Government and Consumer Services, as the publisher."
                ),
            ],
        )
    )

    fields = polite_ckan(ON, "datastore_search", resource_id=csv["id"], limit=0)["fields"]
    types = {f["id"]: f["type"] for f in fields if f["id"] != "_id"}
    suppressed = find(
        names["notes"], r"Counts of fewer than 5 names were suppressed", "Ontario names notes"
    ).group(0)
    out.append(
        _q(
            category="DataStore fields",
            group="provincial",
            eval_type="facts",
            question="In the DataStore table of Ontario's 'Ontario top baby names (female)' "
            "dataset, which fields hold the year, the name and the count, what are their data "
            "types, and how are names given fewer than five times handled?",
            expected={"fields": types, "small_counts": suppressed},
            reference={"data_range_end": csv.get("data_range_end")},
            facts={
                "year": r"Year/Ann[ée]e|\bYear\b",
                "name": r"Name/Nom|\bName\b",
                "count": r"Frequency/Fr[ée]quence|\bFrequency\b",
                "numeric": r"numeric|number|integer",
                "text": r"\btext\b|\bstring\b",
                "suppressed": r"suppress|omit|exclud|withheld|not (shown|included|listed)|"
                r"left out|removed",
            },
            headline=["count", "suppressed"],
            tolerance="Year/Année (numeric), Name/Nom (text), Frequency/Fréquence (numeric); "
            "counts under five are suppressed.",
            grading={
                "correct": "The three fields with their types, and counts under five suppressed.",
                "partial": "The count field and the suppression, types missing.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    csv["id"],
                    "Ontario top baby names (female): DataStore fields",
                    types,
                    f"{ON}datastore_search?resource_id={csv['id']}",
                ),
                cite(
                    "Other",
                    names["name"],
                    "Ontario top baby names (female): notes",
                    suppressed,
                    dataset_url(ON, names["name"]),
                ),
            ],
            traps=[
                (
                    "Unlike Quebec's name bank, which shows '<5', Ontario leaves names with "
                    "fewer than five births out of the table."
                ),
                "'Frequency' is a count of registrations, not a rank.",
            ],
        )
    )

    cit = polite_ckan(AB, "package_show", id="net-corporate-income-tax-revenue")
    usage = cit.get("usage") or ""
    mismatch = find(
        usage,
        r"These totals will not match information in the Financial Statement and Annual "
        r"Report due to accounting adjustments",
        "Alberta CIT usage",
    ).group(0)
    out.append(
        _q(
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="On open.alberta.ca, which ministry publishes the 'Net corporate income "
            "tax revenue, Alberta' dataset, under which licence, how often is it updated, in "
            "what file format, and do its totals match the province's Financial Statement "
            "and Annual Report?",
            expected={
                "organization": cit["organization"]["title"],
                "licence": cit["license_title"],
                "update_frequency": cit["updatefrequency"],
                "formats": sorted({r["format"] for r in cit["resources"]}),
                "matches_annual_report": "No",
            },
            facts={
                "organization": r"Treasury Board and Finance|\bTBF\b",
                "licence": r"Open Government Licen[cs]e\s*[-–—(]?\s*Alberta|OGL[- ]A",
                "frequency": r"annual|yearly|once a year|each year",
                "format": r"\bXLSX\b|Excel",
                "mismatch": rf"({NOT_NEAR}|differ)[^.]{{0,120}}(match|agree|reconcile|"
                r"Financial Statement|Annual Report)|(Financial Statement|Annual Report)"
                rf"[^.]{{0,120}}({NOT_NEAR}|differ)",
            },
            headline=["organization", "mismatch"],
            tolerance="Treasury Board and Finance; Open Government Licence - Alberta; annual; "
            "XLSX; the totals do not match the Financial Statement and Annual Report "
            "(accounting adjustments).",
            grading={
                "correct": "Ministry, licence, annual, XLSX, and the totals do not match.",
                "partial": "Ministry and the mismatch, with licence, frequency or format missing.",
                "referral": "No answer, only the dataset's link.",
            },
            citations=[
                cite(
                    "Other",
                    cit["name"],
                    cit["title"],
                    cit["license_title"],
                    dataset_url(AB, cit["name"]),
                ),
                cite(
                    "Other",
                    cit["name"],
                    "Usage considerations",
                    mismatch,
                    dataset_url(AB, cit["name"]),
                ),
            ],
            traps=[
                (
                    "The industry split rests on the NAICS code each company chooses when it "
                    "files; the totals differ from the audited statements."
                ),
            ],
        )
    )

    grains = polite_ckan(AB, "package_show", id="canada-supply-and-disposition")
    grain_formats = sorted({r["format"] for r in grains["resources"]})
    if grains["type"] != "publications" or grain_formats != ["PDF"]:
        fail("Alberta 'Canada supply and disposition' is no longer a PDF publication")
    out.append(
        _q(
            category="Dataset metadata",
            group="provincial",
            eval_type="facts",
            question="On open.alberta.ca, is 'Canada supply and disposition' listed as an open "
            "data set or as a publication, which ministry publishes it, how often is it "
            "released, and in what file format?",
            expected={
                "type": grains["type"],
                "organization": grains["organization"]["title"],
                "update_frequency": grains["updatefrequency"],
                "formats": grain_formats,
            },
            reference={"resources": grains["num_resources"]},
            facts={
                "publication": r"publication",
                "organization": r"Agriculture and Irrigation",
                "frequency": r"quarterly|four times a year|every (three|3) months",
                "format": r"\bPDF\b",
            },
            headline=["publication", "format"],
            tolerance="A publication (not an open data set); Agriculture and Irrigation; "
            "quarterly; PDF.",
            grading={
                "correct": "Publication, Agriculture and Irrigation, quarterly, PDF.",
                "partial": "Publication and PDF, ministry or frequency missing.",
                "referral": "No answer, only the record's link.",
            },
            citations=[
                cite(
                    "Other",
                    grains["name"],
                    grains["title"],
                    grains["updatefrequency"],
                    dataset_url(AB, grains["name"]),
                ),
            ],
            traps=[
                (
                    "Open Alberta lists publications beside open data; this one is a series of "
                    "PDF reports on grain supplies, with no table to query."
                ),
            ],
        )
    )
    return out


def build() -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    # New parts go last: ids follow list order, and the first 28 must keep theirs.
    for part in (
        statcan,
        bank_of_canada,
        cmhc,
        federal,
        provincial,
        municipal,
        statcan_wds,
        ontario_alberta,
    ):
        questions += part()
    for q in questions:
        q.setdefault("eval_type", "facts")
    return {
        "benchmark": "maple_test_v3",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": "Publishers' own APIs and documentation, read directly: StatCan IMDB, "
        "RDaaS and WDS, Bank of Canada Valet, CMHC methodology pages, CKAN Action APIs "
        "(open.canada.ca, BC Data Catalogue, Ontario Data Catalogue, Open Alberta, Données "
        "Québec, Toronto, Montréal)",
        "questions": [{"id": f"T-{i:02d}", **q} for i, q in enumerate(questions, 1)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check the Maple Test v3 key.")
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args()
    new = build()
    if args.check:
        changes = drift(json.loads(KEY.read_text(encoding="utf-8")), new)
        print("\n".join(changes) or "no drift")
        return 1 if changes else 0
    KEY.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {KEY.relative_to(HERE.parents[1])}: {len(new['questions'])} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())

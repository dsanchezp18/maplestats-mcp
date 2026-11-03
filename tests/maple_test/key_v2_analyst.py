"""Maple Test v2, analyst group: questions from an analyst's working week.

Each one has a trap an analyst knows and a general assistant tends to miss:

- A-01 child poverty for a province: the annual Canadian Income Survey has it (not only
  the census), and the line must be named (MBM, the official poverty line).
- A-02 wages in provincial public administration: the payroll survey (SEPH) has the
  detailed industry (NAICS 912); the Labour Force Survey's wage table stops at "Public
  administration" as a whole. Correct only when the answer names SEPH or says why.
- A-03 "average income": incomes are skewed, so the median belongs beside the average.
- A-04 "median household income": a household is a Census unit; the Canadian Income
  Survey counts economic families and persons not in an economic family.

Values are read live from StatCan (WDS and the Census Profile SDMX API).
"""

from __future__ import annotations

from typing import Any

import httpx

from tests.maple_test.build_key import cite, series

CENSUS_URL = (
    "https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest/data/STC_CP,DF_PR/"
    "A5.2021A000248.1.229.1"
)


def _census_household_median() -> float:
    """Census Profile 2021, Alberta, characteristic 229: median total household income."""
    response = httpx.get(
        CENSUS_URL, headers={"Accept": "application/vnd.sdmx.data+json"}, timeout=60
    )
    response.raise_for_status()
    series_ = response.json()["data"]["dataSets"][0]["series"]
    (obs,) = next(iter(series_.values()))["observations"].values()
    return float(obs[0])


def questions() -> list[dict[str, Any]]:
    q: list[dict[str, Any]] = []

    # A-01: child poverty, Alberta, Canadian Income Survey, MBM 2023 base.
    pov_pid, pov_coord = 11100135, "12.2.7.2.0.0.0.0.0.0"
    pov = series(pov_pid, pov_coord, ["2024-01-01"])
    q.append(
        {
            "category": "Analyst",
            "eval_type": "numeric",
            "question": "What is the child poverty rate in Alberta?",
            "expected": {"mbm_under18_2024_pct": pov["points"]["2024-01-01"][0]},
            "headline": ["mbm_under18_2024_pct"],
            "tolerance": "±0.1; the Market Basket Measure (official poverty line), 2024",
            "citations": [cite(pov_pid, pov, "2024-01-01", pov_coord)],
            "traps": [
                (
                    "Not only the census: the Canadian Income Survey (11-10-0135) is annual for "
                    "the provinces."
                ),
                "Name the line: MBM is the official poverty line; LIM-AT and LICO differ.",
            ],
        }
    )

    # A-02: provincial public administration wages: SEPH, not LFS.
    m_pid, a_pid, coord = 14100203, 14100204, "10.1.1.395.0.0.0.0.0.0"
    monthly = series(m_pid, coord, ["2026-08-01"])
    annual = series(a_pid, coord, ["2025-01-01"])
    q.append(
        {
            "category": "Analyst",
            "eval_type": "flag",
            "question": "What are average wages for workers in Alberta's provincial public "
            "administration?",
            # Kept out of "expected": a flag question counts a direct figure as correct,
            # and this one is correct only when the answer names the payroll survey.
            "expected": {},
            "reference": {
                "seph_awe_aug_2026": monthly["points"]["2026-08-01"][0],
                "seph_awe_2025": annual["points"]["2025-01-01"][0],
            },
            "headline": [],
            "flag_pattern": r"SEPH|Survey of Employment, Payrolls and Hours|EERH|payroll survey|14-10-020[34]",
            "tolerance": "Correct only when the answer uses SEPH (names it, or cites its tables "
            "14-10-0203/0204 for NAICS 912); the figures are listed for reference.",
            "citations": [
                cite(m_pid, monthly, "2026-08-01", coord),
                cite(a_pid, annual, "2025-01-01", coord),
            ],
            "traps": [
                (
                    "The LFS wage table (14-10-0064) has only 'Public administration' as a whole; "
                    "SEPH (14-10-0203, 14-10-0204) has provincial and territorial public "
                    "administration (NAICS 912)."
                )
            ],
        }
    )

    # A-03: "average income": the median belongs beside it.
    inc_pid = 11100239
    avg = series(inc_pid, "12.1.1.1.4.0.0.0.0.0", ["2024-01-01"])
    med = series(inc_pid, "12.1.1.1.5.0.0.0.0.0", ["2024-01-01"])
    q.append(
        {
            "category": "Analyst",
            "eval_type": "numeric",
            "question": "What is the average income in Alberta?",
            "expected": {
                "average_income_2024": avg["points"]["2024-01-01"][0],
                "median_income_2024": med["points"]["2024-01-01"][0],
            },
            # Either figure alone is partial; both are correct.
            "headline": [],
            "tolerances": {"average_income_2024": 100, "median_income_2024": 100},
            "tolerance": "±$100; correct needs the median as well as the average",
            "citations": [
                cite(inc_pid, avg, "2024-01-01", "12.1.1.1.4.0.0.0.0.0"),
                cite(inc_pid, med, "2024-01-01", "12.1.1.1.5.0.0.0.0.0"),
            ],
            "traps": ["Incomes are skewed: the median is the typical income."],
        }
    )

    # A-04: household income: Census household vs CIS economic family.
    fam_pid, fam_coord = 11100190, "12.8.1.0.0.0.0.0.0.0"
    fam = series(fam_pid, fam_coord, ["2024-01-01"])
    household = _census_household_median()
    q.append(
        {
            "category": "Analyst",
            "eval_type": "numeric",
            "question": "What is the median household income in Alberta?",
            "expected": {
                "census_household_median_2020": household,
                "cis_family_median_2024": fam["points"]["2024-01-01"][0],
            },
            # Either figure alone is partial (the CIS one is real, but not a household unit).
            "headline": [],
            "tolerances": {"census_household_median_2020": 0, "cis_family_median_2024": 100},
            "tolerance": "The Census household figure is the headline; correct gives both and "
            "names each unit (household vs economic families and persons not in one)",
            "citations": [
                {
                    "table_id": "Other",
                    "vector_id": None,
                    "series_title": "Census Profile 2021, Alberta, characteristic 229 "
                    "'Median total income of household in 2020 ($)'",
                    "reference_period": "2020",
                    "value": household,
                    "release_or_revision_date": "2022-07-13",
                    "url": CENSUS_URL,
                },
                cite(fam_pid, fam, "2024-01-01", fam_coord),
            ],
            "traps": [
                (
                    "A household is a Census unit; the Canadian Income Survey uses economic "
                    "families and persons not in an economic family."
                ),
                "Census income is 2020, raised by pandemic benefits.",
            ],
        }
    )
    # A-05: disability poverty for a province: not published. The CIS rate by disability
    # (11-10-0090) is for Canada only; the Census Profile has no disability measure.
    dis_pid, dis_coord = 11100090, "1.1.1.1.4.2"
    dis = series(dis_pid, dis_coord, ["2024-01-01"])
    q.append(
        {
            "category": "Analyst",
            "eval_type": "refusal",
            "question": "What is the poverty rate for people with disabilities in Alberta?",
            "expected": {
                "behaviour": "Say no Alberta rate is published: 11-10-0090 is Canada "
                "only. The national rate, or a custom tabulation, is the honest alternative."
            },
            "reference": {"canada_mbm_disability_2024_pct": dis["points"]["2024-01-01"][0]},
            "headline": [],
            "absent_pattern": (
                r"(only|just) (for|at) (the )?(Canada|national|country)|national(ly)? only|"
                r"only (covers|has|reports) (a )?Canada|only (a )?Canada-wide|only geography is Canada|"
                r"Canada(-wide)? only|Canada alone|"
                r"(not|isn't|is not|aren't|are not) (published|available|broken down|"
                r"reported)[^.]{0,40}(Alberta|provinc)|no (published )?(Alberta|provincial)|"
                r"(doesn't|does not|don't|do not) (publish|break)[^.]{0,60}(Alberta|provinc)"
            ),
            "tolerance": "Correct only when the answer says Alberta has no published rate; a "
            "national rate presented as Alberta's is a hallucination.",
            "citations": [cite(dis_pid, dis, "2024-01-01", dis_coord)],
            "traps": [
                "11-10-0090 (poverty by disability status) is Canada only.",
                (
                    "The Census Profile has no disability measure; the 2022 Canadian Survey on "
                    "Disability (13-10-0379) gives Alberta income groups, not a poverty rate."
                ),
                (
                    "The Census difficulty questions (activities of daily living) only screen "
                    "for that survey: released on special request, and not a disability measure."
                ),
            ],
        }
    )
    for item in q:
        item["group"] = "analyst"
        item["tolerances"] = item.get("tolerances", {})
    return q

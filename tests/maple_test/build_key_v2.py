"""Build the Maple Test v2 answer key.

v2 is larger than v1 and reaches past Statistics Canada and the Bank of Canada. Half the
questions are "core" (StatCan WDS tables and Bank of Canada Valet series, where most
Canadian data servers compete), half are "beyond" (other publishers), so results are
reported for each half: a server that covers more sources shows it in the second half
without that being the whole score. Every answer is read from the publisher's own API,
never through MapleStats. The questions were written before any server was run on them.

    uv run python -m tests.maple_test.build_key_v2            # rebuild maple_test_v2.json
    uv run python -m tests.maple_test.build_key_v2 --check    # report drift, write nothing

The beyond half lives in `key_v2_beyond.py` (ECCC, World Bank, BIS, Health Canada, IRCC,
the 2021 Census).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.maple_test.build_key import _post, _valet_cite, cite, drift, pct, series, valet

HERE = Path(__file__).resolve().parent
KEY = HERE / "maple_test_v2.json"

SEP26, SEP25, AUG26, JUL26 = "2026-09-01", "2025-09-01", "2026-08-01", "2026-07-01"
Q2_26, Q1_26 = "2026-04-01", "2026-01-01"
PROVINCES = (
    "Newfoundland and Labrador",
    "Prince Edward Island",
    "Nova Scotia",
    "New Brunswick",
    "Quebec",
    "Ontario",
    "Manitoba",
    "Saskatchewan",
    "Alberta",
    "British Columbia",
)


def _q(**fields: Any) -> dict[str, Any]:
    fields.setdefault("group", "core")
    fields.setdefault("tolerances", {})
    return fields


def _dollars(s: dict[str, Any], period: str, scale: float) -> float:
    return round(s["points"][period][0] * scale)


def latest_period(pid: int) -> tuple[str, str]:
    (meta,) = _post("getCubeMetadata", [{"productId": pid}])
    return meta["object"]["cubeEndDate"][:10], meta["object"]["releaseTime"]


def core() -> list[dict[str, Any]]:
    q: list[dict[str, Any]] = []
    lfs, cpi, core_cpi = 14100287, 18100004, 18100256

    # Labour ----------------------------------------------------------------
    on = series(lfs, "7.9.1.1.1.1", [SEP26])
    qc = series(lfs, "6.9.1.1.1.1", [SEP26])
    hi = "Ontario" if on["points"][SEP26][0] > qc["points"][SEP26][0] else "Quebec"
    q.append(
        _q(
            category="Labour",
            eval_type="comparison",
            question="Was the employment rate higher in Ontario or in Quebec in September 2026? "
            "Give both rates.",
            expected={"ontario_pct": on["points"][SEP26][0], "quebec_pct": qc["points"][SEP26][0]},
            headline=["ontario_pct", "quebec_pct"],
            answer_pattern=hi,
            tolerance="Right province; each rate ±0.1",
            citations=[cite(lfs, on, SEP26, "7.9.1.1.1.1"), cite(lfs, qc, SEP26, "6.9.1.1.1.1")],
            traps=["The employment rate is not the participation rate or 100 minus unemployment."],
        )
    )
    youth = series(lfs, "1.7.1.2.1.1", [SEP26, SEP25])
    q.append(
        _q(
            category="Labour",
            eval_type="numeric",
            question="What was the youth unemployment rate (ages 15 to 24) in Canada in "
            "September 2026, and what was it a year earlier?",
            expected={
                "rate_sep_2026_pct": youth["points"][SEP26][0],
                "rate_sep_2025_pct": youth["points"][SEP25][0],
            },
            headline=["rate_sep_2026_pct"],
            tolerance="±0.1",
            citations=[
                cite(lfs, youth, SEP26, "1.7.1.2.1.1"),
                cite(lfs, youth, SEP25, "1.7.1.2.1.1"),
            ],
            traps=["Seasonally adjusted is the headline; ages 15 to 24, not 15 to 29."],
        )
    )
    emp = series(lfs, "1.3.1.1.1.1", [SEP26, AUG26])
    change = round(emp["points"][SEP26][0] - emp["points"][AUG26][0], 1)
    q.append(
        _q(
            category="Labour",
            eval_type="numeric",
            question="How many jobs did Canada gain or lose in September 2026, according to the "
            "Labour Force Survey?",
            expected={
                "change_thousands": change,
                "employment_sep_2026_thousands": emp["points"][SEP26][0],
            },
            headline=["change_thousands"],
            tolerance="±0.5 thousand; the sign must be right",
            citations=[cite(lfs, emp, SEP26, "1.3.1.1.1.1"), cite(lfs, emp, AUG26, "1.3.1.1.1.1")],
            traps=["The LFS counts employed people (in thousands), not SEPH payroll jobs."],
        )
    )
    wage = series(14100063, "1.2.1.1.1.1", [SEP26, SEP25])
    q.append(
        _q(
            category="Labour",
            eval_type="numeric",
            question="What was the average hourly wage of employees in Canada in September 2026, "
            "and how much did it rise from a year earlier?",
            expected={
                "wage_sep_2026": wage["points"][SEP26][0],
                "change_pct": pct(wage["points"][SEP26][0], wage["points"][SEP25][0]),
            },
            headline=["wage_sep_2026"],
            tolerances={"wage_sep_2026": 0.005},
            tolerance="±0.005; ±0.1",
            citations=[
                cite(14100063, wage, SEP26, "1.2.1.1.1.1"),
                cite(14100063, wage, SEP25, "1.2.1.1.1.1"),
            ],
            traps=[
                (
                    "LFS wages are not seasonally adjusted, so compare with the same month a year "
                    "earlier; SEPH average weekly earnings are a different measure."
                )
            ],
        )
    )
    vac = series(14100432, "1.3", [AUG26])
    count = series(14100432, "1.1", [AUG26])
    q.append(
        _q(
            category="Labour",
            eval_type="numeric",
            question="What was Canada's job vacancy rate in August 2026, and how many vacant "
            "positions were there?",
            expected={
                "vacancy_rate_pct": vac["points"][AUG26][0],
                "vacancies": count["points"][AUG26][0],
            },
            headline=["vacancy_rate_pct"],
            tolerance="±0.1; vacancies ±0.1% (may be rounded)",
            citations=[cite(14100432, vac, AUG26, "1.3"), cite(14100432, count, AUG26, "1.1")],
            traps=["Seasonally adjusted monthly estimates (14-10-0432), not the quarterly table."],
        )
    )

    # Prices ----------------------------------------------------------------
    for coord, name, label in (
        ("2.2", "allitems", "consumer prices (all-items CPI)"),
        ("2.184", "gasoline", "gasoline prices"),
        ("2.4", "food", "prices of food purchased from stores"),
    ):
        s = series(cpi, coord, [SEP26, SEP25])
        q.append(
            _q(
                category="Prices",
                eval_type="numeric",
                question=f"By how much did {label} in Canada change over the 12 months to "
                "September 2026?",
                expected={f"{name}_yoy_pct": pct(s["points"][SEP26][0], s["points"][SEP25][0])},
                headline=[f"{name}_yoy_pct"],
                tolerance="±0.1",
                citations=[cite(cpi, s, SEP26, coord), cite(cpi, s, SEP25, coord)],
                traps=[
                    (
                        "Not seasonally adjusted (the official CPI); a 12-month change, not "
                        "month over month."
                    )
                ],
            )
        )
    (meta,) = _post("getCubeMetadata", [{"productId": cpi}])
    geos = {m["memberNameEn"]: m["memberId"] for m in meta["object"]["dimension"][0]["member"]}
    provincial = {p: series(cpi, f"{geos[p]}.2", [SEP26, SEP25]) for p in PROVINCES}
    rates = {p: pct(s["points"][SEP26][0], s["points"][SEP25][0]) for p, s in provincial.items()}
    top = max(rates, key=lambda p: rates[p])
    ties = [p for p in rates if rates[p] == rates[top]]
    if len(ties) > 1:
        raise SystemExit(f"several provinces share the top CPI rate: {ties}")
    q.append(
        _q(
            category="Prices",
            eval_type="comparison",
            question="Which province had the highest 12-month CPI inflation in September 2026, "
            "and what was the rate?",
            expected={"top_rate_pct": rates[top]},
            headline=["top_rate_pct"],
            answer_pattern=top,
            tolerance="Right province; rate ±0.1",
            citations=[
                cite(cpi, provincial[top], SEP26, f"{geos[top]}.2"),
                cite(cpi, provincial[top], SEP25, f"{geos[top]}.2"),
            ],
            traps=["Compare the provinces' own 12-month changes, not index levels."],
        )
    )
    common = series(core_cpi, "1.1", [SEP26])
    q.append(
        _q(
            category="Prices",
            eval_type="numeric",
            question="What was CPI-common, the Bank of Canada's factor-model measure of core "
            "inflation, in September 2026?",
            expected={"cpi_common_pct": common["points"][SEP26][0]},
            headline=["cpi_common_pct"],
            tolerance="±0.1",
            citations=[cite(core_cpi, common, SEP26, "1.1")],
            traps=[
                "CPI-common is revised as the model is re-estimated; it is already a 12-month rate."
            ],
        )
    )

    # Output, trade and housing ---------------------------------------------------
    gdp = series(36100104, "1.1.1.30", [Q2_26, Q1_26])
    g2, g1 = gdp["points"][Q2_26][0], gdp["points"][Q1_26][0]
    q.append(
        _q(
            category="Output",
            eval_type="numeric",
            question="How fast did Canada's real GDP grow in the second quarter of 2026, at an "
            "annualized rate?",
            expected={
                "annualized_pct": round(((g2 / g1) ** 4 - 1) * 100, 1),
                "quarterly_pct": pct(g2, g1),
            },
            headline=["annualized_pct"],
            tolerance="±0.1",
            citations=[
                cite(36100104, gdp, Q2_26, "1.1.1.30"),
                cite(36100104, gdp, Q1_26, "1.1.1.30"),
            ],
            traps=[
                (
                    "StatCan headlines the annualized rate; the quarter-over-quarter change is a "
                    "quarter of it, roughly."
                )
            ],
        )
    )
    retail = series(20100056, "1.1.1.2", [AUG26, JUL26])
    q.append(
        _q(
            category="Output",
            eval_type="numeric",
            question="By how much did Canada's retail sales change in August 2026 from July?",
            expected={
                "change_pct": pct(retail["points"][AUG26][0], retail["points"][JUL26][0]),
                "sales_aug_2026_dollars": _dollars(retail, AUG26, 1000),
            },
            headline=["change_pct"],
            tolerance="±0.1; level ±0.1%",
            citations=[
                cite(20100056, retail, AUG26, "1.1.1.2"),
                cite(20100056, retail, JUL26, "1.1.1.2"),
            ],
            traps=[
                (
                    "Seasonally adjusted, in current dollars; StatCan's advance estimate for the "
                    "next month is not in this table."
                )
            ],
        )
    )
    mfg = series(16100047, "1.1.2.1", [AUG26, JUL26])
    q.append(
        _q(
            category="Output",
            eval_type="numeric",
            question="What were Canadian manufacturers' sales in August 2026, and how did they "
            "change from July?",
            expected={
                "sales_aug_2026_dollars": _dollars(mfg, AUG26, 1000),
                "change_pct": pct(mfg["points"][AUG26][0], mfg["points"][JUL26][0]),
            },
            headline=["sales_aug_2026_dollars"],
            tolerance="level ±0.1%; change ±0.1",
            citations=[
                cite(16100047, mfg, AUG26, "1.1.2.1"),
                cite(16100047, mfg, JUL26, "1.1.2.1"),
            ],
            traps=["Values are in thousands of dollars; seasonally adjusted."],
        )
    )
    exports = series(12100011, "1.2.2.2.2", [AUG26])
    q.append(
        _q(
            category="Trade",
            eval_type="numeric",
            question="What was the value of Canada's merchandise exports to the United States "
            "in August 2026?",
            expected={"exports_us_aug_2026_dollars": _dollars(exports, AUG26, 1_000_000)},
            headline=["exports_us_aug_2026_dollars"],
            tolerance="±0.1%",
            citations=[cite(12100011, exports, AUG26, "1.2.2.2.2")],
            traps=["Balance of payments basis, seasonally adjusted, in millions of dollars."],
        )
    )
    starts = series(34100158, "1", [SEP26])
    q.append(
        _q(
            category="Housing",
            eval_type="numeric",
            question="What was Canada's seasonally adjusted annual rate of housing starts in "
            "September 2026?",
            expected={"starts_saar_sep_2026": starts["points"][SEP26][0] * 1000},
            headline=["starts_saar_sep_2026"],
            tolerance="±0.1%",
            citations=[cite(34100158, starts, SEP26, "1")],
            traps=[
                (
                    "The value is in thousands of units at an annual rate, not units started in "
                    "the month."
                )
            ],
        )
    )
    permits = series(34100292, "1.1.1.1.2", [AUG26])
    q.append(
        _q(
            category="Housing",
            eval_type="numeric",
            question="What was the total value of building permits issued in Canada in August "
            "2026?",
            expected={"permits_aug_2026_dollars": _dollars(permits, AUG26, 1000)},
            headline=["permits_aug_2026_dollars"],
            tolerance="±0.1%",
            citations=[cite(34100292, permits, AUG26, "1.1.1.1.2")],
            traps=["Seasonally adjusted, current dollars, residential and non-residential."],
        )
    )

    # Population ----------------------------------------------------------------
    pop, npr = 17100009, 17100121
    bc = series(pop, "11", ["2026-07-01"])
    q.append(
        _q(
            category="Population",
            eval_type="numeric",
            question="What was British Columbia's population on July 1, 2026?",
            expected={"population": bc["points"]["2026-07-01"][0]},
            headline=["population"],
            tolerance="Exact persons (rounded to the nearest thousand counts within 0.1%)",
            citations=[cite(pop, bc, "2026-07-01", "11")],
            traps=["Quarterly estimates; July 1 is the reference date."],
        )
    )
    study = series(npr, "1.9", ["2026-07-01", "2025-07-01"])
    q.append(
        _q(
            category="Population",
            eval_type="numeric",
            question="How many people in Canada held only a study permit on July 1, 2026, "
            "compared with a year earlier?",
            expected={
                "study_2026": study["points"]["2026-07-01"][0],
                "study_2025": study["points"]["2025-07-01"][0],
            },
            headline=["study_2026"],
            tolerance="Exact persons (within 0.1% if rounded)",
            citations=[
                cite(npr, study, "2026-07-01", "1.9"),
                cite(npr, study, "2025-07-01", "1.9"),
            ],
            traps=[
                (
                    "'Study permit holders only' excludes people holding both a work and a study "
                    "permit."
                )
            ],
        )
    )

    # Markets ---------------------------------------------------------------------
    rate = valet("V39079", "2026-10-26", "2026-10-30")
    five = valet("BD.CDN.5YR.DQ.YLD", "2026-10-26", "2026-10-30")
    bcpi = valet("M.BCPI", "2026-08-01", "2026-09-30")
    q.append(
        _q(
            category="Markets",
            eval_type="numeric",
            question="What was the Bank of Canada's target for the overnight rate on October 30, "
            "2026?",
            expected={"policy_rate_pct": rate["2026-10-30"]},
            headline=["policy_rate_pct"],
            tolerances={"policy_rate_pct": 0.005},
            tolerance="Exact",
            citations=[_valet_cite("V39079", "2026-10-30", rate["2026-10-30"])],
            traps=[
                "Valet dates the target from its effective date, the day after an announcement."
            ],
        )
    )
    q.append(
        _q(
            category="Markets",
            eval_type="numeric",
            question="What was the 5-year Government of Canada benchmark bond yield on October "
            "30, 2026?",
            expected={"yield_5y_pct": five["2026-10-30"]},
            headline=["yield_5y_pct"],
            tolerances={"yield_5y_pct": 0.005},
            tolerance="±0.005",
            citations=[_valet_cite("BD.CDN.5YR.DQ.YLD", "2026-10-30", five["2026-10-30"])],
            traps=["The benchmark yield, not a marketable bond's or the curve's."],
        )
    )
    month = max(bcpi)
    q.append(
        _q(
            category="Markets",
            eval_type="numeric",
            question="What was the Bank of Canada commodity price index (BCPI, total) for "
            f"{datetime.fromisoformat(month).strftime('%B %Y')}?",
            expected={"bcpi": bcpi[month]},
            headline=["bcpi"],
            tolerances={"bcpi": 0.05},
            tolerance="±0.05",
            citations=[_valet_cite("M.BCPI", month, bcpi[month])],
            traps=["An index (1972=100), in US dollars; not a price."],
        )
    )

    # Refusals and a flag ----------------------------------------------------------
    cpi_end, cpi_release = latest_period(cpi)
    if cpi_end >= "2026-10-01":
        raise SystemExit("October 2026 CPI is published; the refusal no longer holds")
    q.append(
        _q(
            category="Unanswerable",
            eval_type="refusal",
            question="What was Canada's CPI inflation rate in October 2026?",
            expected={
                "behaviour": "Decline: the October 2026 CPI is not published yet; the "
                f"latest month is {cpi_end[:7]}.",
                "latest_month": cpi_end[:7],
            },
            headline=[],
            tolerance="Pass only if no October 2026 figure is given",
            citations=[
                {
                    "table_id": "18-10-0004-01",
                    "vector_id": None,
                    "reference_period": cpi_end[:7],
                    "release_or_revision_date": cpi_release,
                    "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1810000401",
                }
            ],
            traps=["A forecast, a nowcast or the September rate is not October's."],
        )
    )
    gdp_end, gdp_release = latest_period(36100104)
    if gdp_end >= "2026-07-01":
        raise SystemExit("Q3 2026 GDP is published; the refusal no longer holds")
    q.append(
        _q(
            category="Unanswerable",
            eval_type="refusal",
            question="How much did Canada's real GDP grow in the third quarter of 2026?",
            expected={
                "behaviour": "Decline: Q3 2026 GDP is not published yet (due late "
                f"November 2026); the latest quarter is {gdp_end[:7]}.",
                "latest_quarter": gdp_end[:7],
            },
            headline=[],
            tolerance="Pass only if no Q3 2026 figure is given",
            citations=[
                {
                    "table_id": "36-10-0104-01",
                    "vector_id": None,
                    "reference_period": gdp_end[:7],
                    "release_or_revision_date": gdp_release,
                    "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610010401",
                }
            ],
            traps=["Monthly GDP for July and August does not make a published Q3 figure."],
        )
    )
    q.append(
        _q(
            category="Housing",
            eval_type="flag",
            question="Canada's housing starts figure for September 2026 is the latest monthly "
            "number. Multiply it by 12 to estimate how many homes will be started in a year.",
            expected={
                "behaviour": "Flag that the published figure is already a seasonally "
                "adjusted annual rate, so multiplying by 12 overstates starts twelvefold; "
                "give the rate itself.",
                "starts_saar_sep_2026": starts["points"][SEP26][0] * 1000,
            },
            headline=[],
            tolerance="Pass only if the annual-rate problem is stated",
            flag_pattern=r"annual(?:ized)? rate|already (?:an )?annual|SAAR|at annual rates?",
            citations=[cite(34100158, starts, SEP26, "1")],
            traps=["CMHC and StatCan publish monthly starts as a seasonally adjusted annual rate."],
        )
    )
    return q


def build() -> dict[str, Any]:
    from tests.maple_test import key_v2_beyond

    core_q = core()
    beyond_q = key_v2_beyond.questions()
    questions = []
    for i, q in enumerate(core_q, 1):
        questions.append({"id": f"C-{i:02d}", **q})
    for i, q in enumerate(beyond_q, 1):
        q = {k: v for k, v in q.items() if k != "id"}
        questions.append({"id": f"X-{i:02d}", **q, "group": "beyond"})
    return {
        "benchmark": "maple_test_v2",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": "Publishers' own APIs, read directly: StatCan WDS, Bank of Canada Valet, "
        "ECCC, World Bank, BIS, Health Canada, IRCC",
        "questions": questions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or check the Maple Test v2 key.")
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

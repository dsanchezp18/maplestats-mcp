"""Build the Maple Test answer key from Statistics Canada WDS and Bank of Canada Valet.

The Maple Test is 15 questions on Canadian economic and social statistics, away from the
GTA housing ground truth that MapleStats was tuned against (CanData's benchmark). It has
the same four kinds of question: numeric, comparison, refusal (the figure does not exist)
and flag (the question asks for a misleading calculation). The questions were written
before MapleStats was run on them, and no fix may be made against them without a new
question set to check the fix on.

The key is read straight from the publishers' APIs with httpx, never through MapleStats,
so a MapleStats bug cannot leak into the answers it is graded against.

    uv run python -m tests.maple_test.build_key            # rebuild maple_test_v1.json
    uv run python -m tests.maple_test.build_key --check    # report drift, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
KEY = HERE / "maple_test_v1.json"
WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
VALET = "https://www.bankofcanada.ca/valet/observations/"

# http2=True: StatCan resets a TLS handshake that offers only HTTP/1.1 (AGENTS.md).
_client = httpx.Client(http2=True, timeout=90)


def _post(method: str, body: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for attempt in range(4):
        try:
            response = _client.post(WDS + method, json=body)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt == 3:
                raise
    raise AssertionError("unreachable")


def table_id(pid: int) -> str:
    digits = f"{pid:08d}"
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:8]}-01"


def series(pid: int, coordinate: str, periods: list[str]) -> dict[str, Any]:
    """Values and release times of one WDS series at the given reference periods (YYYY-MM-DD)."""
    coordinate = ".".join((coordinate.split(".") + ["0"] * 10)[:10])
    (item,) = _post("getSeriesInfoFromCubePidCoord", [{"productId": pid, "coordinate": coordinate}])
    info = item["object"]
    if item["status"] != "SUCCESS" or info.get("responseStatusCode"):
        raise SystemExit(f"no series at {pid} {coordinate}")
    vector = int(info["vectorId"])
    (data,) = _post("getDataFromVectorsAndLatestNPeriods", [{"vectorId": vector, "latestN": 40}])
    points = {p["refPer"]: p for p in data["object"]["vectorDataPoint"]}
    out = {"vector": vector, "title": info["SeriesTitleEn"], "points": {}}
    for period in periods:
        point = points.get(period)
        if point is None or point.get("value") is None:
            raise SystemExit(f"v{vector} has no value for {period}")
        out["points"][period] = (float(point["value"]), point["releaseTime"])
    return out


def valet(name: str, start: str, end: str) -> dict[str, float]:
    response = _client.get(f"{VALET}{name}/json", params={"start_date": start, "end_date": end})
    response.raise_for_status()
    return {
        row["d"]: float(row[name]["v"])
        for row in response.json()["observations"]
        if name in row and row[name].get("v") not in (None, "")
    }


def cite(pid: int, s: dict[str, Any], period: str, coordinate: str) -> dict[str, Any]:
    value, released = s["points"][period]
    return {
        "table_id": table_id(pid),
        "vector_id": f"v{s['vector']}",
        "series_title": s["title"],
        "reference_period": period[:7] if not period.endswith("-01-01") else period[:4],
        "coordinate": coordinate,
        "value": value,
        "release_or_revision_date": released,
        "url": f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid:08d}01",
    }


def pct(new: float, old: float) -> float:
    return round((new / old - 1) * 100, 1)


def build() -> dict[str, Any]:
    q: list[dict[str, Any]] = []
    sep26, sep25 = "2026-09-01", "2025-09-01"

    # M-01 ------------------------------------------------------------------
    lfs = 14100287
    rate = series(lfs, "1.7.1.1.1.1", [sep26, sep25])
    q.append(
        {
            "id": "M-01",
            "category": "Labour",
            "eval_type": "numeric",
            "question": "What was Canada's unemployment rate in September 2026, and how did it "
            "compare with September 2025?",
            "expected": {
                "rate_sep_2026_pct": rate["points"][sep26][0],
                "rate_sep_2025_pct": rate["points"][sep25][0],
                "change_pp": round(rate["points"][sep26][0] - rate["points"][sep25][0], 1),
            },
            "headline": ["rate_sep_2026_pct", "rate_sep_2025_pct"],
            "tolerance": "±0.1 on rates; change in percentage points",
            "citations": [
                cite(lfs, rate, sep26, "1.7.1.1.1.1"),
                cite(lfs, rate, sep25, "1.7.1.1.1.1"),
            ],
            "traps": [
                "Seasonally adjusted is the headline series; the unadjusted rate differs.",
                "The change is in percentage points, not percent.",
            ],
        }
    )

    # M-02 ------------------------------------------------------------------
    provinces = {
        2: "Newfoundland and Labrador",
        3: "Prince Edward Island",
        4: "Nova Scotia",
        5: "New Brunswick",
        6: "Quebec",
        7: "Ontario",
        8: "Manitoba",
        9: "Saskatchewan",
        10: "Alberta",
        11: "British Columbia",
    }
    rates = {p: series(lfs, f"{p}.7.1.1.1.1", [sep26]) for p in provinces}
    ranked = sorted(rates, key=lambda p: rates[p]["points"][sep26][0], reverse=True)
    top, second = ranked[0], ranked[1]
    q.append(
        {
            "id": "M-02",
            "category": "Labour",
            "eval_type": "comparison",
            "question": "Which province had the highest unemployment rate in September 2026, "
            "and what was it?",
            "expected": {
                "answer": provinces[top],
                "top_rate_pct": rates[top]["points"][sep26][0],
                "second_province": provinces[second],
                "second_rate_pct": rates[second]["points"][sep26][0],
            },
            "headline": ["top_rate_pct"],
            "answer_pattern": provinces[top],
            "tolerance": "Correct province; rate ±0.1",
            "citations": [
                cite(lfs, rates[top], sep26, f"{top}.7.1.1.1.1"),
                cite(lfs, rates[second], sep26, f"{second}.7.1.1.1.1"),
            ],
            "traps": ["Seasonally adjusted monthly estimates; territories are not in this table."],
        }
    )

    # M-03 and M-04 -----------------------------------------------------------
    pop, jul26, jul25 = 17100009, "2026-07-01", "2025-07-01"
    canada = series(pop, "1", [jul26, jul25])
    ab = series(pop, "10", [jul26, jul25])
    on = series(pop, "7", [jul26, jul25])
    c26, c25 = canada["points"][jul26][0], canada["points"][jul25][0]
    q.append(
        {
            "id": "M-03",
            "category": "Population",
            "eval_type": "numeric",
            "question": "What was Canada's population on July 1, 2026, and how much did it grow "
            "over the previous year?",
            "expected": {
                "population_jul_2026": c26,
                "population_jul_2025": c25,
                "growth_persons": c26 - c25,
                "growth_pct": pct(c26, c25),
            },
            "headline": ["population_jul_2026"],
            "tolerance": "Exact persons (rounding to the nearest thousand counts as partial); "
            "percentage ±0.1",
            "citations": [cite(pop, canada, jul26, "1"), cite(pop, canada, jul25, "1")],
            "traps": [
                "Quarterly estimates are revised; July 1 is the reference date, not the year."
            ],
        }
    )
    ab_g = pct(ab["points"][jul26][0], ab["points"][jul25][0])
    on_g = pct(on["points"][jul26][0], on["points"][jul25][0])
    q.append(
        {
            "id": "M-04",
            "category": "Population",
            "eval_type": "comparison",
            "question": "Did Alberta or Ontario grow faster in population in the year to "
            "July 1, 2026? Give both growth rates.",
            "expected": {
                "answer": "Alberta" if ab_g > on_g else "Ontario",
                "alberta_growth_pct": ab_g,
                "ontario_growth_pct": on_g,
            },
            "headline": ["alberta_growth_pct", "ontario_growth_pct"],
            "answer_pattern": "Alberta" if ab_g > on_g else "Ontario",
            "tolerance": "Correct province; each rate ±0.1",
            "citations": [
                cite(pop, ab, jul26, "10"),
                cite(pop, ab, jul25, "10"),
                cite(pop, on, jul26, "7"),
                cite(pop, on, jul25, "7"),
            ],
            "traps": ["Growth in percent of each province's own population, not in persons."],
        }
    )

    # M-05 ------------------------------------------------------------------
    npr = 17100121
    nprs = series(npr, "1.1", [jul26, jul25])
    n26, n25 = nprs["points"][jul26][0], nprs["points"][jul25][0]
    q.append(
        {
            "id": "M-05",
            "category": "Population",
            "eval_type": "numeric",
            "question": "How many non-permanent residents lived in Canada on July 1, 2026, and "
            "how did that compare with a year earlier?",
            "expected": {
                "npr_jul_2026": n26,
                "npr_jul_2025": n25,
                "change_persons": n26 - n25,
                "change_pct": pct(n26, n25),
            },
            "headline": ["npr_jul_2026", "npr_jul_2025"],
            "tolerance": "Exact persons; percentage ±0.1",
            "citations": [cite(npr, nprs, jul26, "1.1"), cite(npr, nprs, jul25, "1.1")],
            "traps": [
                "Non-permanent residents are a stock on a date, not a flow of new arrivals.",
                "IRCC permit counts (holders of valid permits) differ from StatCan's estimate.",
            ],
        }
    )

    # M-06 ------------------------------------------------------------------
    cpi_a, y25, y24 = 18100005, "2025-01-01", "2024-01-01"
    allitems = series(cpi_a, "2.2", [y25, y24])
    inflation = pct(allitems["points"][y25][0], allitems["points"][y24][0])
    q.append(
        {
            "id": "M-06",
            "category": "Prices",
            "eval_type": "numeric",
            "question": "What was Canada's inflation rate for 2025 as a whole?",
            "expected": {
                "inflation_2025_pct": inflation,
                "cpi_2025": allitems["points"][y25][0],
                "cpi_2024": allitems["points"][y24][0],
            },
            "headline": ["inflation_2025_pct"],
            "tolerance": "±0.1",
            "citations": [cite(cpi_a, allitems, y25, "2.2"), cite(cpi_a, allitems, y24, "2.2")],
            "traps": [
                "The annual figure is the change in the annual average index, not December "
                "over December or the latest 12-month rate.",
            ],
        }
    )

    # M-07 ------------------------------------------------------------------
    core = 18100256
    trim = series(core, "1.3", [sep26])
    median = series(core, "1.2", [sep26])
    q.append(
        {
            "id": "M-07",
            "category": "Prices",
            "eval_type": "numeric",
            "question": "What were the Bank of Canada's preferred core inflation measures, "
            "CPI-trim and CPI-median, in September 2026?",
            "expected": {
                "cpi_trim_pct": trim["points"][sep26][0],
                "cpi_median_pct": median["points"][sep26][0],
            },
            "headline": ["cpi_trim_pct", "cpi_median_pct"],
            "tolerance": "±0.1",
            "citations": [cite(core, trim, sep26, "1.3"), cite(core, median, sep26, "1.2")],
            "traps": [
                "These are year-over-year rates already; do not compute a change from them.",
                "Core measures are revised, so a figure from an earlier release may differ.",
            ],
        }
    )

    # M-08 ------------------------------------------------------------------
    gdp, aug26, jul26m = 36100434, "2026-08-01", "2026-07-01"
    real = series(gdp, "1.1.1.1", [aug26, jul26m])
    q.append(
        {
            "id": "M-08",
            "category": "Output",
            "eval_type": "numeric",
            "question": "By how much did Canada's real GDP change in August 2026, from July?",
            "expected": {
                "change_pct": pct(real["points"][aug26][0], real["points"][jul26m][0]),
                "gdp_aug_2026": real["points"][aug26][0],
                "gdp_jul_2026": real["points"][jul26m][0],
            },
            "headline": ["change_pct"],
            "tolerance": "±0.1",
            "citations": [cite(gdp, real, aug26, "1.1.1.1"), cite(gdp, real, jul26m, "1.1.1.1")],
            "traps": [
                "Real GDP is in chained (2017) dollars at seasonally adjusted annual rates; "
                "the level is not a monthly dollar amount.",
                "StatCan's advance estimate for the next month is in The Daily, not this table.",
            ],
        }
    )

    # M-09 ------------------------------------------------------------------
    trade = 12100011
    balance = series(trade, "1.3.2.2.1", [aug26, jul26m])
    q.append(
        {
            "id": "M-09",
            "category": "Trade",
            "eval_type": "numeric",
            "question": "What was Canada's merchandise trade balance with the world in "
            "August 2026?",
            "expected": {
                "balance_aug_2026_millions": balance["points"][aug26][0],
                "balance_jul_2026_millions": balance["points"][jul26m][0],
            },
            "headline": ["balance_aug_2026_millions"],
            "tolerance": "±0.5 million dollars; the sign (surplus or deficit) must be right",
            "citations": [
                cite(trade, balance, aug26, "1.3.2.2.1"),
                cite(trade, balance, jul26m, "1.3.2.2.1"),
            ],
            "traps": [
                "Values are in millions of dollars.",
                "The headline is the balance of payments basis, seasonally adjusted; the "
                "customs basis differs.",
            ],
        }
    )

    # M-10 ------------------------------------------------------------------
    seph, aug25 = 14100223, "2025-08-01"
    awe = series(seph, "1.2.2", [aug26, aug25])
    q.append(
        {
            "id": "M-10",
            "category": "Labour",
            "eval_type": "numeric",
            "question": "What were average weekly earnings in Canada in August 2026, and how "
            "much did they rise over the year?",
            "expected": {
                "awe_aug_2026": awe["points"][aug26][0],
                "awe_aug_2025": awe["points"][aug25][0],
                "change_pct": pct(awe["points"][aug26][0], awe["points"][aug25][0]),
            },
            "headline": ["awe_aug_2026"],
            "tolerance": "±0.05 dollars; percentage ±0.1",
            "citations": [cite(seph, awe, aug26, "1.2.2"), cite(seph, awe, aug25, "1.2.2")],
            "traps": [
                "Average weekly earnings come from SEPH (payroll); the LFS average hourly wage "
                "is a different measure.",
                "Industrial aggregate excluding unclassified businesses is the headline.",
            ],
        }
    )

    # M-11, M-12, M-14 ----------------------------------------------------------
    fx = valet("FXUSDCAD", "2026-10-28", "2026-11-02")
    bond = valet("BD.CDN.10YR.DQ.YLD", "2026-10-28", "2026-11-02")
    if "2026-11-01" in fx or "2026-10-31" in fx:
        raise SystemExit("Valet published a weekend rate; M-14 no longer holds")
    q.append(
        {
            "id": "M-11",
            "category": "Markets",
            "eval_type": "numeric",
            "question": "What was the Bank of Canada's US dollar exchange rate on "
            "October 30, 2026?",
            "expected": {"usdcad_2026_10_30": fx["2026-10-30"]},
            "headline": ["usdcad_2026_10_30"],
            "tolerance": "±0.00005 (four decimals)",
            "citations": [_valet_cite("FXUSDCAD", "2026-10-30", fx["2026-10-30"])],
            "traps": ["Valet gives Canadian dollars per US dollar; the inverse is not quoted."],
        }
    )
    q.append(
        {
            "id": "M-12",
            "category": "Markets",
            "eval_type": "numeric",
            "question": "What was the 10-year Government of Canada benchmark bond yield on "
            "October 30, 2026?",
            "expected": {"yield_10y_2026_10_30_pct": bond["2026-10-30"]},
            "headline": ["yield_10y_2026_10_30_pct"],
            "tolerance": "±0.005",
            "citations": [_valet_cite("BD.CDN.10YR.DQ.YLD", "2026-10-30", bond["2026-10-30"])],
            "traps": ["The benchmark yield is not the average of a curve or a marketable bond's."],
        }
    )

    # M-13 ------------------------------------------------------------------
    (meta,) = _post("getCubeMetadata", [{"productId": 36100104}])
    latest_quarter = meta["object"]["cubeEndDate"][:10]
    if latest_quarter >= "2026-10-01":
        raise SystemExit("Q4 2026 GDP is now published; M-13 no longer holds")
    q.append(
        {
            "id": "M-13",
            "category": "Unanswerable",
            "eval_type": "refusal",
            "question": "What was Canada's real GDP growth in the fourth quarter of 2026?",
            "expected": {
                "behaviour": "Decline: Q4 2026 GDP is not published yet (the quarter ends "
                "December 31, 2026). The latest quarter is "
                f"{latest_quarter[:7]} (Q2 2026).",
                "latest_quarter": latest_quarter[:7],
            },
            "headline": [],
            "tolerance": "Pass only if no Q4 2026 figure is given",
            "citations": [
                {
                    "table_id": "36-10-0104-01",
                    "vector_id": None,
                    "reference_period": latest_quarter[:7],
                    "release_or_revision_date": meta["object"]["releaseTime"],
                    "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610010401",
                }
            ],
            "traps": ["A forecast or nowcast is not a published figure."],
        }
    )
    q.append(
        {
            "id": "M-14",
            "category": "Unanswerable",
            "eval_type": "refusal",
            "question": "What was the Bank of Canada's US dollar exchange rate on "
            "November 1, 2026?",
            "expected": {
                "behaviour": "Say that no rate was published for November 1, 2026 (a Sunday); "
                "offer the nearest published rates instead.",
                "nearest_before": fx["2026-10-30"],
            },
            "headline": [],
            "absent_period": "2026-11-01",
            "tolerance": "Pass only if no rate is presented as the November 1 rate",
            "citations": [_valet_cite("FXUSDCAD", "2026-10-30", fx["2026-10-30"])],
            "traps": ["Valet publishes business days only; a weekend has no rate."],
        }
    )

    # M-15 ------------------------------------------------------------------
    unemployed = series(lfs, "1.6.1.1.1.1", [sep26])
    q.append(
        {
            "id": "M-15",
            "category": "Labour",
            "eval_type": "flag",
            "question": "Using the labour force from the 2021 Census and the September 2026 "
            "unemployment rate, how many Canadians were unemployed?",
            "expected": {
                "behaviour": "Flag that this mixes a 2021 Census count with a 2026 survey "
                "rate, and give the Labour Force Survey's own count of unemployed people "
                "for September 2026 instead (or alongside).",
                "unemployed_sep_2026_thousands": unemployed["points"][sep26][0],
            },
            "headline": [],
            "flag_years": ["2021", "2026"],
            "tolerance": "Pass only if the mismatch is stated or the LFS count is given",
            "citations": [cite(lfs, unemployed, sep26, "1.6.1.1.1.1")],
            "traps": [
                "The LFS publishes the number unemployed directly (in thousands); rebuilding it "
                "from a five-year-old census base is both unnecessary and wrong.",
            ],
        }
    )
    return {
        "benchmark": "maple_test_v1",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": "Statistics Canada WDS and Bank of Canada Valet, read directly with httpx",
        "questions": q,
    }


def _valet_cite(name: str, day: str, value: float) -> dict[str, Any]:
    return {
        "table_id": "Valet",
        "vector_id": name,
        "reference_period": day,
        "value": value,
        "release_or_revision_date": None,
        "url": f"https://www.bankofcanada.ca/valet/observations/{name}",
    }


def drift(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Expected values or citation release dates that changed since the key was built."""
    found = []
    before = {q["id"]: q for q in old["questions"]}
    for q in new["questions"]:
        p = before.get(q["id"])
        if p is None:
            found.append(f"{q['id']}: new question")
            continue
        if p["expected"] != q["expected"]:
            found.append(f"{q['id']}: expected {p['expected']} -> {q['expected']}")
        for a, b in zip(p["citations"], q["citations"], strict=False):
            if a.get("release_or_revision_date") != b.get("release_or_revision_date"):
                found.append(
                    f"{q['id']} {b.get('vector_id')}: released "
                    f"{a.get('release_or_revision_date')} -> {b.get('release_or_revision_date')}"
                )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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

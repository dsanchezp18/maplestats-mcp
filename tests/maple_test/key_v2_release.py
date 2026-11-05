"""Maple Test v2, release group: when does a figure come out?

Analysts ask when a release lands as often as they ask for its numbers: when the
provincial and territorial economic accounts (PTEA) or the supply and use tables (SUT)
come out for the provinces, which table now holds a series, whether a date has been set
at all. Each question has a trap:

- R-01 PTEA 2025: the provincial GDP for 2025 by expenditure is not out until the PTEA
  release; GDP by industry for 2025 came out in May, which is not the same release.
- R-02 SUT: the tables lag the PTEA by two years (2023 tables beside 2025 PTEA).
- R-03 provincial GDP by industry, 2025: published in 36-10-0711, not in 36-10-0402, the
  table most people know, which stops at 2024.
- R-04, R-05, R-07, R-08: a scheduled or past monthly release date, read from the calendar.
- R-06 PTEA 2026: no date has been announced; a date given anyway is invented.

Written and keyed on 2026-11-04, before MapleStats or any other server was asked them,
so they are a fresh set for checking the fixes made after the first v2 runs. Dates are
read from StatCan's own release schedule (the Daily's release archive, which also lists
the scheduled releases of the coming days) and table end dates from WDS, never through
MapleStats.

Shelf life: R-01, R-02 and R-06 are about releases dated 2026-11-05. A rescheduled
release changes the key (`build_key_v2 --check` reports it); R-06 holds only until
StatCan schedules the 2026 PTEA, about a year out.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from tests.maple_test.build_key import _post

SCHEDULE_URL = (
    "https://www150.statcan.gc.ca/n1/dai-quo/ssi/homepage/schedule-previous_releases-eng.json"
)
DAILY = "https://www150.statcan.gc.ca/n1"
UPCOMING_URL = "https://www150.statcan.gc.ca/n1/dai-quo/cal2-eng.htm"
# http2=True only changes the TLS ALPN offer; StatCan's network resets connections that
# offer HTTP/1.1 alone (AGENTS.md, "Three things that look removable").
_client = httpx.Client(http2=True, timeout=90, follow_redirects=True)

# A release date written out in words, matched loosely (the grader reads it the same way).
NO_DATE_YET = (
    r"(not|n't|n’t) (yet )?(been )?(scheduled|announced|set|on (the|its|statistics canada's) "
    r"(release )?(calendar|schedule))|no (release )?date (has been|is|was) (yet )?"
    r"(set|announced|scheduled|published)|no (scheduled|announced) (release )?date|"
    r"(isn't|is not|not) (yet )?(on|in) (the|statistics canada's|its) (release )?"
    r"(calendar|schedule)|(has|have)(n't|n’t| not) (yet )?(scheduled|announced)"
)


MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}


def _upcoming() -> list[dict[str, Any]]:
    """The two-week calendar (cal2), as schedule entries.

    The release archive lists only the major indicators ahead of time (checked
    2026-11-04: the LFS and building permits are there, the PTEA and SUT are not), so the
    full list is read from cal2's own markup: an h3 per day, then an ol of div.rtitle
    items with the reference period in span.refper. Parsed here, not through MapleStats.
    """
    response = _client.get(UPCOMING_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    block = soup.find("div", class_="upcoming")
    if not isinstance(block, Tag):
        raise SystemExit(f"{UPCOMING_URL}: no div.upcoming")
    heading = block.find("h2")
    year = int(re.findall(r"20\d\d", heading.get_text(" ") if isinstance(heading, Tag) else "")[-1])
    out = []
    for day in block.find_all("h3"):
        found = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})", day.get_text(" ").replace("\xa0", " "))
        listing = day.find_next_sibling("ol")
        if not found or found.group(1).lower() not in MONTHS or not isinstance(listing, Tag):
            continue
        when = f"{year}-{MONTHS[found.group(1).lower()]:02d}-{int(found.group(2)):02d}"
        for item in listing.find_all("div", class_="rtitle"):
            refper = item.find("span", class_="refper")
            period = refper.extract().get_text(" ") if isinstance(refper, Tag) else ""
            title = re.sub(r"\s+", " ", item.get_text(" ")).strip(" ,")
            period = re.sub(r"\s+", " ", period).strip(" ,")
            out.append({"date": when, "title": title, "description": period, "url": None})
    return out


def _schedule() -> list[dict[str, Any]]:
    response = _client.get(SCHEDULE_URL)
    response.raise_for_status()
    archive = response.json()
    # A release on both lists is the same release: keep the archive's entry (it has a URL
    # once published) and add the calendar's others.
    seen = {
        (e["title"].strip().lower(), (e.get("description") or "").strip().lower()) for e in archive
    }
    extra = [e for e in _upcoming() if (e["title"].lower(), e["description"].lower()) not in seen]
    return archive + extra


def _release(entries: list[dict[str, Any]], title: str, period: str) -> dict[str, Any]:
    """The one schedule entry with this title and reference period."""
    found = [
        e
        for e in entries
        if e["title"].strip().lower() == title.lower()
        and (e.get("description") or "").strip().lower() == period.lower()
    ]
    if len(found) != 1:
        raise SystemExit(f"expected one release of {title!r}, {period!r}; found {len(found)}")
    return found[0]


def _date(entry: dict[str, Any]) -> str:
    return entry["date"][:10]


def _cite(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_id": "Other",
        "vector_id": None,
        "series_title": f"The Daily release schedule: {entry['title']}, {entry['description']}",
        "reference_period": entry["description"],
        "value": _date(entry),
        "release_or_revision_date": _date(entry),
        "url": DAILY + entry["url"] if entry.get("url") else UPCOMING_URL,
    }


def _cube(pid: int) -> tuple[str, str]:
    (meta,) = _post("getCubeMetadata", [{"productId": pid}])
    return meta["object"]["cubeEndDate"][:10], meta["object"]["releaseTime"][:10]


def questions() -> list[dict[str, Any]]:
    entries = _schedule()
    ptea = "Provincial and territorial economic accounts"
    ptea_24, ptea_25 = _release(entries, ptea, "2024"), _release(entries, ptea, "2025")
    sut_22 = _release(entries, "Supply and use tables", "2022")
    sut_23 = _release(entries, "Supply and use tables", "2023")
    by_industry = _release(
        entries, "Gross domestic product by industry: Provinces and territories", "2025"
    )
    lfs = _release(entries, "Labour Force Survey", "October 2026")
    msm = _release(entries, "Monthly Survey of Manufacturing", "September 2026")
    cpi = _release(entries, "Consumer Price Index", "September 2026")
    permits = _release(entries, "Building permits", "September 2026")

    # R-03's trap only holds while the old table stops at 2024 and the new one has 2025.
    old_end, _ = _cube(36100402)
    # The cube's own release time moves with every revision; the key cites the Daily's
    # release date instead, so a routine revision is not reported as drift.
    new_end, _ = _cube(36100711)
    if old_end != "2024-01-01" or new_end != "2025-01-01":
        raise SystemExit(f"R-03 trap changed: 36-10-0402 ends {old_end}, 36-10-0711 {new_end}")
    # R-06 holds only while no 2026 PTEA release is scheduled.
    if any(
        e["title"].strip() == ptea and (e.get("description") or "").strip() == "2026"
        for e in entries
    ):
        raise SystemExit("R-06 no longer holds: the 2026 PTEA release is scheduled")

    q: list[dict[str, Any]] = []
    q.append(
        {
            "category": "Release",
            "eval_type": "date",
            "question": "When does Statistics Canada release Alberta's GDP for 2025 in the "
            "provincial and territorial economic accounts (PTEA)?",
            "expected": {"ptea_2025_release": _date(ptea_25)},
            "reference": {
                "ptea_2024_release": _date(ptea_24),
                "gdp_by_industry_2025_release": _date(by_industry),
            },
            "headline": ["ptea_2025_release"],
            "tolerance": "The exact date. A May 1 date (GDP by industry, 2025) is a different "
            "release; saying the 2025 PTEA is already out is wrong.",
            "citations": [_cite(ptea_25), _cite(ptea_24)],
            "traps": [
                "GDP by industry for 2025 (May 1, 2026) is not the PTEA release.",
                "The latest PTEA published before the release date is for 2024.",
            ],
        }
    )
    q.append(
        {
            "category": "Release",
            "eval_type": "date",
            "question": "When were Statistics Canada's provincial and territorial supply and "
            "use tables for 2022 released, and when are the 2023 tables due?",
            "expected": {
                "sut_2022_release": _date(sut_22),
                "sut_2023_release": _date(sut_23),
            },
            "headline": ["sut_2023_release"],
            "tolerance": "Both exact dates; one of the two is partial",
            "citations": [_cite(sut_22), _cite(sut_23)],
            "traps": ["The tables lag the PTEA by two years: 2023 SUT beside 2025 PTEA."],
        }
    )
    q.append(
        {
            "category": "Release",
            "eval_type": "date",
            "question": "When did Statistics Canada publish 2025 GDP by industry for the "
            "provinces, and in which table?",
            "expected": {"gdp_by_industry_2025_release": _date(by_industry)},
            "headline": ["gdp_by_industry_2025_release"],
            # The date without the table is partial: the old table is the trap.
            "table_pattern": r"36-10-0711|3610071101|36100711",
            "tolerance": "The date and table 36-10-0711; the date alone is partial; 36-10-0402 "
            "given as the 2025 table is wrong",
            "citations": [
                _cite(by_industry),
                {
                    "table_id": "36-10-0711-01",
                    "vector_id": None,
                    "series_title": "Gross domestic product by industry, provinces and "
                    "territories (2025 preliminary)",
                    "reference_period": new_end[:4],
                    "value": _date(by_industry),
                    "release_or_revision_date": _date(by_industry),
                    "url": "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3610071101",
                },
            ],
            "traps": ["36-10-0402, the table most people know, stops at 2024."],
        }
    )
    for entry, question, key in (
        (
            lfs,
            "When will Statistics Canada release the Labour Force Survey for October 2026?",
            "lfs_oct_2026_release",
        ),
        (
            msm,
            "When will the Monthly Survey of Manufacturing for September 2026 be released?",
            "msm_sep_2026_release",
        ),
    ):
        q.append(
            {
                "category": "Release",
                "eval_type": "date",
                "question": question,
                "expected": {key: _date(entry)},
                "headline": [key],
                "tolerance": "The exact date",
                "citations": [_cite(entry)],
                "traps": ["A scheduled date, read from the release calendar, not guessed."],
            }
        )
    q.append(
        {
            "category": "Release",
            "eval_type": "refusal",
            "question": "On what date will Statistics Canada release the 2026 provincial and "
            "territorial economic accounts?",
            "expected": {
                "behaviour": "Say no date has been announced; the PTEA usually comes out in "
                "November of the following year."
            },
            "reference": {"ptea_2025_release": _date(ptea_25)},
            "headline": [],
            "absent_pattern": NO_DATE_YET,
            "tolerance": "Correct only when the answer says no date is scheduled yet; a "
            "specific date in 2027 stated as the release date is invented.",
            "citations": [_cite(ptea_25)],
            "traps": ["The schedule lists releases only weeks ahead; none is set for 2026 PTEA."],
        }
    )
    for entry, question, key in (
        (
            cpi,
            "When did Statistics Canada release the Consumer Price Index for September 2026?",
            "cpi_sep_2026_release",
        ),
        (
            permits,
            "When will building permits for September 2026 be released?",
            "permits_sep_2026_release",
        ),
    ):
        q.append(
            {
                "category": "Release",
                "eval_type": "date",
                "question": question,
                "expected": {key: _date(entry)},
                "headline": [key],
                "tolerance": "The exact date",
                "citations": [_cite(entry)],
                "traps": ["Read from the release schedule, not inferred from a usual weekday."],
            }
        )
    for item in q:
        item["group"] = "release"
        item["tolerances"] = {}
    if any(
        not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)
        for i in q
        for v in i["expected"].values()
        if i["eval_type"] == "date"
    ):
        raise SystemExit("a release date did not parse")
    return q


def splice() -> int:
    """Add or replace the release group in maple_test_v2.json, leaving the rest as keyed.

    A full `build_key_v2` rebuild re-reads every other value, and some have been revised
    since the runs were graded; this keeps those runs graded against the key they ran on.
    """
    key = Path(__file__).resolve().parent / "maple_test_v2.json"
    data = json.loads(key.read_text(encoding="utf-8"))
    kept = [q for q in data["questions"] if q.get("group") != "release"]
    new = [{"id": f"R-{i:02d}", **q} for i, q in enumerate(questions(), 1)]
    data["questions"] = kept + new
    data["release_group_built_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    # newline="\n": on Windows, text mode would write CRLF into an LF file.
    key.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {len(new)} release questions to {key.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(splice())

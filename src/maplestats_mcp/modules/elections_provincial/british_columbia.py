"""British Columbia general election results from the Elections BC open data.

Checked live 2026-10-01 on the BC Data Catalogue dataset "Provincial Voting Results"
(Elections BC Open Data Licence): two CSV files with one row per candidate (or rejected
ballot count) per voting area or voting place and opportunity.

- provincial_voting_results_by_va.csv (30 MB, Windows-1252): events 2005 to 2020, with the
  general elections of 2005, 2009, 2013, 2017 and 2020 plus by-elections.
- provincial_voting_results_by_voting_place.csv (1.6 MB, UTF-8 with a byte order mark):
  events after 2020, with the 2024 general election plus by-elections.

Columns used: EVENT_NAME, EVENT_YEAR, ED_ABBREVIATION, ED_NAME, CANDIDATE ("Last, First"),
ELECTED (Y on the winner's rows), AFFILIATION, VOTES_CONSIDERED and VOTE_CATEGORY (Valid or
Rejected; rejected rows have no candidate). Summing valid votes by district and candidate
gives 79, 85, 85, 87, 87 and 93 winners for the six general elections, the legislature's
seat counts. The 2005 to 2020 file also has a different ID column layout from the newer one;
neither is needed. By-elections are in the files but not read here.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict

from maplestats_mcp.modules.elections_provincial import constants
from maplestats_mcp.modules.elections_provincial.common import (
    Candidate,
    District,
    fetch_bytes,
    finish_shares,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.errors import UpstreamError
from maplestats_mcp.shared.executor import run_parse

_REQUIRED = {
    "EVENT_NAME",
    "EVENT_YEAR",
    "ED_ABBREVIATION",
    "ED_NAME",
    "CANDIDATE",
    "ELECTED",
    "AFFILIATION",
    "VOTES_CONSIDERED",
    "VOTE_CATEGORY",
}


def file_url(year: str) -> str:
    return (
        constants.BC_FILE_BY_PLACE if year in constants.BC_PLACE_YEARS else constants.BC_FILE_BY_VA
    )


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        # The by-voting-area file is Windows-1252; its byte order mark comes through as
        # three odd characters that would corrupt the first header name.
        return body.decode("cp1252").removeprefix("ï»¿")


def _first_last(name: str) -> str:
    last, _, first = name.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if first else name.strip()


def parse(body: bytes) -> dict[str, list[District]]:
    """General election results in one file, by event year."""
    reader = csv.DictReader(io.StringIO(_decode(body)))
    if not _REQUIRED <= set(reader.fieldnames or []):
        raise UpstreamError(
            f"elections_provincial: BC results file lacks columns {sorted(_REQUIRED)}."
        )

    # (year, ed_name) -> abbreviation, (year, ed_name, candidate, party) -> votes and winner flag
    abbreviations: dict[tuple[str, str], str] = {}
    votes: dict[tuple[str, str, str, str], int] = defaultdict(int)
    elected: set[tuple[str, str, str, str]] = set()
    rejected: dict[tuple[str, str], int] = defaultdict(int)
    for row in reader:
        event = row["EVENT_NAME"].lower()
        if "general election" not in event or "by-election" in event:
            continue
        year, district = row["EVENT_YEAR"], row["ED_NAME"].strip()
        count = int(row["VOTES_CONSIDERED"] or 0)
        abbreviations[(year, district)] = row["ED_ABBREVIATION"]
        if row["VOTE_CATEGORY"] == "Rejected":
            rejected[(year, district)] += count
            continue
        key = (year, district, row["CANDIDATE"].strip(), row["AFFILIATION"].strip())
        votes[key] += count
        if row["ELECTED"] == "Y":
            elected.add(key)

    built: dict[tuple[str, str], District] = {}
    for key, total in votes.items():
        year, name, candidate, party = key
        district = built.setdefault(
            (year, name),
            District(
                name=name,
                number=abbreviations[(year, name)],
                rejected_ballots=rejected.get((year, name)),
            ),
        )
        district.candidates.append(
            Candidate(
                name=_first_last(candidate),
                party=party or None,
                votes=total,
                share=None,
                elected=key in elected,
            )
        )
    by_year: dict[str, list[District]] = defaultdict(list)
    for (year, _name), district in sorted(built.items()):
        district.candidates.sort(key=lambda c: -c.votes)
        finish_shares(district)
        by_year[year].append(district)
    if not by_year:
        raise UpstreamError("elections_provincial: BC results file has no general elections.")
    return dict(by_year)


async def fetch(year: str) -> tuple[list[District], bool]:
    """Districts for one general election, plus whether the parsed file was cached.

    The cache holds the parsed file (every general election in it), so the 30 MB download
    happens once a day however many elections are asked for.
    """
    url = file_url(year)

    async def load() -> dict[str, list[District]]:
        body = await fetch_bytes(
            url, context=f"elections_provincial:bc:{year}", max_bytes=constants.BC_MAX_BYTES
        )
        return await run_parse(parse, body)

    by_year, cached = await cached_fetch(
        f"elections_provincial:bc-file:{url}", constants.CACHE_TTL_SECONDS, load
    )
    if year not in by_year:
        raise UpstreamError(f"elections_provincial: BC file has no {year} general election.")
    return by_year[year], cached

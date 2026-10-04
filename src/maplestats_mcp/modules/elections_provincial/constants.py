"""Constants for the provincial general election results module.

Every URL and rule below was checked live on 2026-10-01.

Quebec: Elections Quebec's open data host serves one JSON file per general
election, the same file its results pages draw from. The site's terms of use
(electionsquebec.qc.ca/notre-institution/conditions-dutilisation/) allow
downloading and reproducing any element for non-profit purposes without
permission, if the source and the copyright (c) are named. Its robots.txt asks
for a 10 second crawl delay, so reads are paced that slowly and cached.

Alberta: the official results site (officialresults.elections.ab.ca) has a
provincial summary page and a winning-candidates page for every event. The
terms (elections.ab.ca/terms-conditions/) allow non-commercial and educational
reproduction without further permission if the materials are not modified, are
attributed to Elections Alberta and are not presented as an official version.

British Columbia: the Elections BC Open Data Licence (royalty-free, commercial
use allowed, attribution required) covers the "Provincial Voting Results"
dataset on the BC Data Catalogue. elections.bc.ca itself answers robots.txt with
"Disallow: /" for unknown agents, so only the catalogue's CSV downloads are used
(its robots.txt asks for a 10 second crawl delay and disallows only /api/).

Saskatchewan: Elections Saskatchewan (the Chief Electoral Officer's office, a legislative
office separate from the provincial government) links one poll-by-poll file per general
election on its results page; the files sit on cdn.elections.sk.ca. Checked 2026-10-02: the
site has no robots.txt (404), no terms of use, copyright or licence page (the footer links
are Accessibility, Privacy policy, Legislation and News releases; the privacy policy covers
personal information only) and no licence line on the results page; the footer reads
"Copyright (c) 2025 Elections Saskatchewan". Nothing found prohibits automated access or
restricts use, and nothing grants an open licence either, so the files are read at the
project owner's risk and every response says so. The Crown copyright of saskatchewan.ca that
ruled out the Saskatchewan Bureau of Statistics is a different body's website and does not
appear on elections.sk.ca. By-elections have their own files and are not read.

Manitoba: Elections Manitoba's page for each general election from 1999 to 2023
(electionsmanitoba.ca/en/Results/PreviousElections/<year>) links a summary of votes received
(one row per candidate), a summary of results (one row per electoral division, with
registered voters and rejected and declined ballots) and a zip of results by voting area,
all under /downloads/. Checked 2026-10-03: the site publishes no terms of use or licence;
the footer reads only "(c) 2026. All rights reserved." and the Website Information page
says only that the printed copies prevail if they differ from the website. The files are
read at the project owner's risk and every response says so. Results from 1870 to 1995 are
PDF only and are not read; by-elections are not read.

Ontario is deliberately absent: see BLOCKED.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVINCES: dict[str, tuple[str, str]] = {
    "qc": ("Quebec", "Québec"),
    "ab": ("Alberta", "Alberta"),
    "bc": ("British Columbia", "Colombie-Britannique"),
    "sk": ("Saskatchewan", "Saskatchewan"),
    "mb": ("Manitoba", "Manitoba"),
}

QC_BASE = "https://donnees.electionsquebec.qc.ca/production/provincial/resultats/archives"
QC_PAGE = "https://www.electionsquebec.qc.ca/resultats-et-statistiques/"
QC_ATTRIBUTION = "Source: Élections Québec, directeur général des élections du Québec. ©"

AB_BASE = "https://officialresults.elections.ab.ca"
AB_PAGE = "https://www.elections.ab.ca/elections/election-results/historical-results/"
AB_ATTRIBUTION = (
    "Source: Elections Alberta. Reproduced from the published results without modification of "
    "the figures; this is not an official version of the results."
)

BC_DATASET_PAGE = "https://catalogue.data.gov.bc.ca/dataset/provincial-voting-results"
BC_RESOURCE_BASE = (
    "https://catalogue.data.gov.bc.ca/dataset/44914a35-de9a-4830-ac48-870001ef8935/resource"
)
BC_FILE_BY_VA = (
    f"{BC_RESOURCE_BASE}/fb40239e-b718-4a79-b18f-7a62139d9792/download/"
    "provincial_voting_results_by_va.csv"
)
BC_FILE_BY_PLACE = (
    f"{BC_RESOURCE_BASE}/4e7be8e3-0805-4f39-87f3-47c4c29e262d/download/"
    "provincial_voting_results_by_voting_place.csv"
)
BC_ATTRIBUTION = "Contains information licenced under the Elections BC Open Data Licence"
BC_LICENCE_URL = "https://www.elections.bc.ca/docs/EBC-Open-Data-Licence.pdf"
BC_MAX_BYTES = 45 * 1024 * 1024

SK_PAGE = "https://www.elections.sk.ca/reports-data/election-results/"
SK_FILES: dict[str, str] = {
    "2024": "https://cdn.elections.sk.ca/upload/2024-GE-POLL-BY-POLL-RESULTS-v1.0.csv",
    "2020": "https://cdn.elections.sk.ca/upload/2020-GE-POLL-BY-POLL-RESULTS-v2.0.csv",
    "2016": "https://cdn.elections.sk.ca/reports/2016%20GE%20Poll%20by%20Poll%20Results.csv",
    "2011": "https://cdn.elections.sk.ca/upload/statementofvotes-2011-pollresults.xlsx",
}
SK_ATTRIBUTION = (
    "Source: Elections Saskatchewan, poll-by-poll results (Chief Electoral Officer's "
    "statements of votes), summed by constituency. Elections Saskatchewan publishes no "
    "terms of use or licence for these files; the site footer reads 'Copyright (c) 2025 "
    "Elections Saskatchewan'. Not an official version of the results."
)
SK_TERMS_NOTICE = (
    "Elections Saskatchewan publishes no terms of use or licence for these files and no "
    "robots.txt (checked 2026-10-02); they are read at the project owner's risk. Registered "
    "voters are not summed (split polls repeat them), so there is no turnout."
)
SK_MAX_BYTES = 10 * 1024 * 1024

MB_DOWNLOADS = "https://www.electionsmanitoba.ca/downloads"
MB_PAGE = "https://www.electionsmanitoba.ca/en/Results/Elections1999AndLater"


@dataclass(frozen=True)
class ManitobaFiles:
    """One Manitoba general election's three downloads (2023 moved to .xlsx)."""

    year: str
    votes: str  # summary of votes received: one row per candidate
    summary: str  # summary of results: one row per electoral division
    by_area: str  # zip of results by voting area

    @property
    def page(self) -> str:
        return f"https://www.electionsmanitoba.ca/en/Results/PreviousElections/{self.year}"


def _mb_files(number: str, year: str, ext: str = "xls") -> ManitobaFiles:
    return ManitobaFiles(
        year=year,
        votes=f"{MB_DOWNLOADS}/{number}GE%20Summary%20of%20Votes%20Received.{ext}",
        summary=f"{MB_DOWNLOADS}/Summary_of_Results_GE{year}.{ext}",
        by_area=f"{MB_DOWNLOADS}/{number}GE.zip",
    )


# Keyed by the general election's number (the 43rd was 2023).
MB_FILES: dict[str, ManitobaFiles] = {
    "43": _mb_files("43", "2023", "xlsx"),
    "42": _mb_files("42", "2019"),
    "41": _mb_files("41", "2016"),
    "40": _mb_files("40", "2011"),
    "39": _mb_files("39", "2007"),
    "38": _mb_files("38", "2003"),
    "37": _mb_files("37", "1999"),
}
MB_ATTRIBUTION = (
    "Source: Elections Manitoba, official results (summary of votes received, summary of "
    "results and results by voting area). Elections Manitoba publishes no terms of use or "
    "licence for these files; the site footer reads '(c) 2026. All rights reserved.' Not an "
    "official version of the results: Elections Manitoba states that its printed copies "
    "prevail over its website."
)
MB_TERMS_NOTICE = (
    "Elections Manitoba publishes no terms of use or licence for these files (checked "
    "2026-10-03; the footer reads only '(c) 2026. All rights reserved.'); they are read at the "
    "project owner's risk."
)
MB_MAX_BYTES = 10 * 1024 * 1024
# Elections Manitoba states no request rate; one file a second keeps the reads light.
MB_RATE_LIMIT_SOURCE = "elections-manitoba"
MB_RATE_LIMIT_PER_SECOND = 1.0
MB_RATE_LIMIT_CAPACITY = 2.0


@dataclass(frozen=True)
class Election:
    province: str
    date: str
    seats: int
    source_key: str


# Seats are the number of electoral districts in each election (the district
# counts the sources themselves list; the smoke test reconciles them).
ELECTIONS: tuple[Election, ...] = (
    Election("qc", "2022-10-03", 125, "2022-10-03"),
    Election("qc", "2018-10-01", 125, "2018-10-01"),
    Election("qc", "2014-04-07", 125, "2014-04-07"),
    Election("qc", "2012-09-04", 125, "2012-09-04"),
    Election("qc", "2008-12-08", 125, "2008-12-08"),
    Election("qc", "2007-03-26", 125, "2007-03-26"),
    Election("qc", "2003-04-14", 125, "2003-04-14"),
    Election("qc", "1998-11-30", 125, "1998-11-30"),
    Election("qc", "1994-09-12", 125, "1994-09-12"),
    Election("qc", "1989-09-25", 125, "1989-09-25"),
    Election("qc", "1985-12-02", 122, "1985-12-02"),
    Election("qc", "1981-04-13", 122, "1981-04-13"),
    Election("qc", "1976-11-15", 110, "1976-11-15"),
    Election("qc", "1973-10-29", 110, "1973-10-29"),
    # Alberta's source_key is the official results site's EventId.
    Election("ab", "2023-05-29", 87, "101"),
    Election("ab", "2019-04-16", 87, "60"),
    Election("ab", "2015-05-05", 87, "31"),
    Election("ab", "2012-04-23", 87, "21"),
    Election("ab", "2008-03-03", 83, "12"),
    # BC's source_key is the event year; the catalogue gives years, not dates, so
    # the polling days are the published general election dates.
    Election("bc", "2024-10-19", 93, "2024"),
    Election("bc", "2020-10-24", 87, "2020"),
    Election("bc", "2017-05-09", 87, "2017"),
    Election("bc", "2013-05-14", 85, "2013"),
    Election("bc", "2009-05-12", 85, "2009"),
    Election("bc", "2005-05-17", 79, "2005"),
    # Saskatchewan's source_key is the year keying SK_FILES.
    Election("sk", "2024-10-28", 61, "2024"),
    Election("sk", "2020-10-26", 61, "2020"),
    Election("sk", "2016-04-04", 61, "2016"),
    Election("sk", "2011-11-07", 58, "2011"),
    # Manitoba's source_key is the general election's number keying MB_FILES.
    Election("mb", "2023-10-03", 57, "43"),
    Election("mb", "2019-09-10", 57, "42"),
    Election("mb", "2016-04-19", 57, "41"),
    Election("mb", "2011-10-04", 57, "40"),
    Election("mb", "2007-05-22", 57, "39"),
    Election("mb", "2003-06-03", 57, "38"),
    Election("mb", "1999-09-21", 57, "37"),
)

# Years in the by-voting-place file (the by-voting-area file ends in 2020).
BC_PLACE_YEARS = frozenset({"2024"})


@dataclass(frozen=True)
class Blocked:
    province: str
    source: str
    url: str
    reason: str


BLOCKED: tuple[Blocked, ...] = (
    Blocked(
        "on",
        "Elections Ontario (results.elections.on.ca Election Explorer and CSV downloads)",
        "https://www.elections.on.ca/en/terms-of-use.html",
        "The terms of use bar using software, scripts or robots (including crawlers) 'to "
        "scrape the sites or services or otherwise copy data from the sites or services', "
        "and allow copying of content 'except for personal use' without prior written "
        "consent. A public server cannot meet that, so Ontario is not built.",
    ),
)

RATE_LIMIT_SOURCE = "elections-provincial"
# One request per 10 seconds, the crawl delay Quebec and the BC catalogue ask for.
RATE_LIMIT_PER_SECOND = 0.1
RATE_LIMIT_CAPACITY = 1.0

# Past results never change; a day keeps the BC file (30 MB) from being re-read.
CACHE_TTL_SECONDS = 24 * 60 * 60

ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000

PROVENANCE_SOURCE = "provincial-election-results"

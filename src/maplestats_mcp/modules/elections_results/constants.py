"""Constants for the federal election results module.

Every URL below was fetched live on 2026-09-29. Elections Canada
(elections.ca) publishes each general election's official voting results
as numbered CSV tables. The folder differs by election (the 42nd to 45th
sit under /res/rep/off/, the 38th to 41st under /scripts/), and the 38th
names its files table01.csv where the others use table_tableau01.csv.
robots.txt disallows only /pol/can/sof/efr/.
"""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "www.elections.ca"
SITE = f"https://{DOMAIN}"


@dataclass(frozen=True)
class Election:
    number: int
    date: str
    folder: str
    file_pattern: str
    page: str


_TABLE = "table_tableau{n:02d}.csv"

ELECTIONS: dict[int, Election] = {
    45: Election(
        45,
        "2025-04-28",
        "/res/rep/off/ovrGE45/62/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/45gedata&document=summary&lang=e",
    ),
    44: Election(
        44,
        "2021-09-20",
        "/res/rep/off/ovr2021app/53/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/44gedata&document=summary&lang=e",
    ),
    43: Election(
        43,
        "2019-10-21",
        "/res/rep/off/ovr2019app/51/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/43gedata&document=summary&lang=e",
    ),
    42: Election(
        42,
        "2015-10-19",
        "/res/rep/off/ovr2015app/41/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/42gedata&document=summary&lang=e",
    ),
    41: Election(
        41,
        "2011-05-02",
        "/scripts/OVR2011/34/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/41gedata&document=summary&lang=e",
    ),
    40: Election(
        40,
        "2008-10-14",
        "/scripts/OVR2008/31/data/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/40gedata&document=summary&lang=e",
    ),
    39: Election(
        39,
        "2006-01-23",
        "/scripts/OVR2006/25/data_donnees/",
        _TABLE,
        "/content.aspx?section=res&dir=rep/off/39gedata&document=summary&lang=e",
    ),
    38: Election(
        38,
        "2004-06-28",
        "/scripts/OVR2004/23/data/",
        "table{n:02d}.csv",
        "/content.aspx?section=res&dir=rep/off/38gedata&document=summary&lang=e",
    ),
}

# Table name -> (number, English description, French description). Numbers
# are the same in every election; names are this module's own.
TABLES: dict[str, tuple[int, str, str]] = {
    "turnout": (
        3,
        "Ballots cast and voter turnout, by province",
        "Bulletins déposés et participation électorale, par province",
    ),
    "seats": (
        7,
        "Seats by political affiliation and gender, by province",
        "Sièges par appartenance politique et genre, par province",
    ),
    "votes_by_party": (
        8,
        "Valid votes by political affiliation, by province",
        "Votes valides par appartenance politique, par province",
    ),
    "vote_share_by_party": (
        9,
        "Percentage of valid votes by political affiliation, by province",
        "Pourcentage des votes valides par appartenance politique, par province",
    ),
    "district_results": (
        11,
        "Electors, ballots, turnout and elected candidate, by electoral district",
        "Électeurs, bulletins, participation et candidat élu, par circonscription",
    ),
    "candidates": (
        12,
        "Every candidate's votes and share, by electoral district",
        "Votes et part des votes de chaque candidat, par circonscription",
    ),
    "returning_officers": (
        13,
        "Returning officers, by electoral district",
        "Directeurs du scrutin, par circonscription",
    ),
}

RATE_LIMIT_SOURCE = "elections-results"
RATE_LIMIT_PER_SECOND = 2.0
RATE_LIMIT_CAPACITY = 4.0

# Past results never change; the 45th is the newest and stays cached for a day.
CACHE_TTL_SECONDS = 24 * 60 * 60

ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000

PROVENANCE_SOURCE = "elections-canada-official-voting-results"

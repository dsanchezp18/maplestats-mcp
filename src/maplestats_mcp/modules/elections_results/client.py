"""Elections Canada official voting results for federal general elections.

Each table is one CSV file; rows come back as published so the bilingual
headers and names stay exactly as Elections Canada wrote them.
"""

from __future__ import annotations

import unicodedata
from typing import Literal

from maplestats_mcp.modules.elections_results import constants
from maplestats_mcp.modules.elections_results.schemas import (
    ElectionInfo,
    ElectionList,
    ElectionTable,
    TableInfo,
)
from maplestats_mcp.shared.csv_files import Columns, fetch_rows
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.limits import fit_to_budget, join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

Lang = Literal["en", "fr"]

_NOT_COVERED = {
    "en": [
        (
            "Official Elections Canada tables before the 38th (2004): the 36th and 37th have no "
            "data files on elections.ca, and the Library of Parliament's ParlInfo answers "
            "automated requests with a Cloudflare challenge. For the 1st to 42nd general "
            "elections (1867 to 2015) by riding, use elections_results_get_historical (party "
            "totals from a CC0 research data set), and for candidate names, parties and "
            "votes in any election since 1867 use elections_results_get_historical_candidates "
            "(a CC0 research data set compiled from ParlInfo, not an official publication)."
        ),
        (
            "Official by-election tables (elections.ca lists them as web pages, not data "
            "files); elections_results_get_historical_candidates has by-election candidates "
            "since 1867."
        ),
        (
            "Poll-by-poll results: use ckan_search_datasets with organization 'elections' "
            "(38th to 44th) or the 45th's per-district files linked from its 'Poll-by-poll' page."
        ),
        "Candidate campaign finance: use elections_financial_returns_ tools.",
    ],
    "fr": [
        (
            "Tableaux officiels d'Élections Canada antérieurs à la 38e (2004) : les 36e et 37e "
            "n'ont pas de fichiers de données sur elections.ca, et ParlInfo de la Bibliothèque "
            "du Parlement répond aux requêtes automatisées par un défi Cloudflare. Pour les 1re "
            "à 42e élections générales (1867 à 2015) par circonscription, utiliser "
            "elections_results_get_historical (totaux par parti d'un jeu de données de recherche "
            "CC0), et pour les noms des candidats, partis et votes de toute élection depuis 1867 "
            "elections_results_get_historical_candidates (jeu de données de recherche CC0 "
            "compilé à partir de ParlInfo, non officiel)."
        ),
        (
            "Tableaux officiels des élections partielles (elections.ca les présente en pages "
            "web) ; elections_results_get_historical_candidates couvre les candidats aux "
            "partielles depuis 1867."
        ),
        (
            "Résultats par bureau de scrutin : utiliser ckan_search_datasets avec l'organisation "
            "« elections » (38e à 44e) ou les fichiers par circonscription de la 45e."
        ),
        "Financement des campagnes des candidats : outils elections_financial_returns_.",
    ],
}


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold().strip()


def _election(number: int) -> constants.Election:
    if number not in constants.ELECTIONS:
        raise InvalidInput(
            f"elections_results: election must be one of {sorted(constants.ELECTIONS)} "
            "(the 38th to 45th general elections)."
        )
    return constants.ELECTIONS[number]


def file_url(election: constants.Election, table_number: int) -> str:
    return constants.SITE + election.folder + election.file_pattern.format(n=table_number)


def _page_in(lang: Lang, path: str) -> str:
    """An elections.ca page in the caller's language: the site takes lang=e or lang=f.

    Checked live 2026-10-03: the 45th summary page and the general elections page
    answer 200 with French titles under lang=f.
    """
    return constants.SITE + (path.replace("&lang=e", "&lang=f") if lang == "fr" else path)


def list_elections(lang: Lang = "en") -> ElectionList:
    tables = [
        TableInfo(table=name, number=num, description=en if lang == "en" else fr)
        for name, (num, en, fr) in constants.TABLES.items()
    ]
    elections = [
        ElectionInfo(election=e.number, date=e.date, page=_page_in(lang, e.page))
        for e in constants.ELECTIONS.values()
    ]
    return ElectionList(
        elections=elections,
        tables=tables,
        not_covered=_NOT_COVERED[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=_page_in(lang, "/content.aspx?section=ele&dir=pas&document=ge&lang=e"),
            cached=False,
            schema_name="elections_results.ElectionList",
            coverage="General elections 38 to 45 (2004 to 2025).",
        ),
    )


def _first_column(
    columns: Columns, *, starts: tuple[str, ...], avoid: tuple[str, ...] = ()
) -> str | None:
    for name in columns.names:
        low = name.lower()
        if low.startswith(starts) and not any(a in low for a in avoid):
            return name
    return None


async def get_table(
    election: int,
    table: str,
    province: str | None = None,
    district: str | None = None,
    party: str | None = None,
    winners_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ElectionTable:
    edition = _election(election)
    if table not in constants.TABLES:
        raise InvalidInput(f"elections_results: table must be one of {list(constants.TABLES)}.")
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"elections_results: limit must be 1 to {constants.ROWS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("elections_results: offset must be 0 or more.")

    number, description_en, description_fr = constants.TABLES[table]
    url = file_url(edition, number)
    rows, cached = await fetch_rows(
        url,
        limiter=_LIMITER,
        ttl=constants.CACHE_TTL_SECONDS,
        context=f"elections_results:{election}:{table}",
    )
    columns = Columns(rows)

    if province:
        column = _first_column(columns, starts=("province",))
        if column is None:
            raise InvalidInput(
                f"elections_results: table {table!r} has no province column (provinces are "
                "its columns); read the row for the party you want."
            )
        wanted = _fold(province)
        rows = [r for r in rows if wanted in _fold(r.get(column, ""))]

    if district:
        column = _first_column(
            columns, starts=("electoral district",), avoid=("number", "numéro", "numero")
        )
        number_column = _first_column(columns, starts=("electoral district number",))
        if column is None:
            raise InvalidInput(f"elections_results: table {table!r} has no electoral district.")
        wanted = _fold(district)
        rows = [
            r
            for r in rows
            if wanted in _fold(r.get(column, ""))
            or (number_column is not None and wanted == r.get(number_column, "").strip())
        ]

    if party:
        column = _first_column(
            columns, starts=("candidate/", "elected candidate", "political affiliation")
        )
        if column is None:
            raise InvalidInput(
                f"elections_results: table {table!r} has no candidate or party column "
                "to filter (party names are column headers there)."
            )
        wanted = _fold(party)
        rows = [r for r in rows if wanted in _fold(r.get(column, ""))]

    if winners_only:
        column = _first_column(columns, starts=("majority/",))
        if table != "candidates" or column is None:
            raise InvalidInput("elections_results: winners_only applies to the candidates table.")
        rows = [r for r in rows if r.get(column, "").strip()]

    total = len(rows)
    page = fit_to_budget(rows[offset : offset + limit])
    truncated = offset + len(page) < total
    given = {
        "province": province,
        "district": district,
        "party": party,
        "winners_only": winners_only or None,
    }
    used = {k: v for k, v in given.items() if v}
    # Filters that each match on their own can still exclude each other (a
    # district outside the province given); say so rather than return a
    # bare empty table.
    no_match = (
        f"No row matched all of {used}; check each filter on its own (a district or party "
        "outside the province given matches nothing)."
        if total == 0 and used
        else None
    )
    return ElectionTable(
        election=election,
        date=edition.date,
        table=table,
        description=description_en if lang == "en" else description_fr,
        file_url=url,
        columns=columns.names,
        rows=page,
        total_rows=total,
        offset=offset,
        truncated=truncated,
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=url,
            cached=cached,
            schema_name="elections_results.ElectionTable",
            freshness="Official results are final; the 45th general election is the newest.",
            coverage=f"General election {election} ({edition.date}), table {number}.",
            limits=join_limits(
                f"Showing rows {offset + 1} to {offset + len(page)} of {total}; page with "
                "offset (responses are capped near 200 KB)"
                if truncated
                else None,
                no_match,
            ),
        ),
    )

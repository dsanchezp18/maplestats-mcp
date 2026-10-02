"""Provincial general election results for Quebec, Alberta and British Columbia.

Each province's reader (quebec.py, alberta.py, british_columbia.py) turns that
province's published files into the same district and candidate shape; this module
picks the election, applies the filters and builds the responses.
"""

from __future__ import annotations

from typing import Literal

from maplestats_mcp.modules.elections_provincial import (
    alberta,
    british_columbia,
    constants,
    quebec,
)
from maplestats_mcp.modules.elections_provincial.common import District, fold
from maplestats_mcp.modules.elections_provincial.schemas import (
    BlockedSource,
    DistrictSummary,
    ElectionInfo,
    ElectionList,
    ElectionResults,
    PartySummary,
    ResultRow,
    SeatSummary,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput

Lang = Literal["en", "fr"]

_DETAIL = {"qc": "candidate", "bc": "candidate", "ab": "party"}

_NOTES = {
    "en": [
        (
            "Quebec, 1973 to 2022: every candidate, from Elections Quebec's open data. The files "
            "do not flag the winner, so the candidate with the most votes is marked elected."
        ),
        (
            "Alberta, 2008 to 2023: votes by party in each electoral division from Elections "
            "Alberta's official results pages, with the winner's name only (a party with no "
            "votes cannot be told from a party with no candidate, so zero rows are left out). "
            "Non-commercial and educational use only, per Elections Alberta's terms."
        ),
        (
            "British Columbia, 2005 to 2024: every candidate, summed from the poll-level open "
            "data (Elections BC Open Data Licence). By-elections are in that data but not read."
        ),
        (
            "Ontario is not covered: its terms of use forbid scraping and limit copying to "
            "personal use (see 'blocked'). Federal results are in elections_results_."
        ),
        "By-elections are not covered for any province.",
    ],
    "fr": [
        (
            "Québec, 1973 à 2022 : tous les candidats, d'après les données ouvertes d'Élections "
            "Québec. Les fichiers n'indiquent pas le gagnant : le candidat ayant le plus de "
            "votes est marqué élu."
        ),
        (
            "Alberta, 2008 à 2023 : votes par parti dans chaque division électorale, d'après les "
            "pages de résultats officiels d'Elections Alberta, avec le nom du gagnant seulement "
            "(un parti sans vote ne se distingue pas d'un parti sans candidat : les lignes à zéro "
            "sont omises). Usage non commercial et éducatif seulement, selon les conditions "
            "d'Elections Alberta."
        ),
        (
            "Colombie-Britannique, 2005 à 2024 : tous les candidats, additionnés à partir des "
            "données ouvertes par bureau de vote (licence de données ouvertes d'Elections BC). "
            "Les élections partielles sont dans ces données mais ne sont pas lues."
        ),
        (
            "L'Ontario n'est pas couvert : ses conditions d'utilisation interdisent le moissonnage "
            "et limitent la copie à un usage personnel (voir « blocked »). Les résultats fédéraux "
            "sont dans elections_results_."
        ),
        "Les élections partielles ne sont couvertes pour aucune province.",
    ],
}


def _source_url(election: constants.Election) -> str:
    if election.province == "qc":
        return quebec.file_url(election.source_key)
    if election.province == "ab":
        return alberta.results_url(election.source_key)
    return constants.BC_DATASET_PAGE


def _attribution(province: str) -> str:
    return {
        "qc": constants.QC_ATTRIBUTION,
        "ab": constants.AB_ATTRIBUTION,
        "bc": constants.BC_ATTRIBUTION,
    }[province]


def _province(code: str) -> str:
    code = code.strip().lower()
    if code not in constants.PROVINCES:
        if code == "on":
            raise InvalidInput(
                "elections_provincial: Ontario is not available; Elections Ontario's terms "
                "of use forbid scraping its results (see elections_provincial_list_elections)."
            )
        raise InvalidInput(
            f"elections_provincial: province must be one of {list(constants.PROVINCES)}."
        )
    return code


def _election(province: str, election: str | None) -> constants.Election:
    candidates = [e for e in constants.ELECTIONS if e.province == province]
    if election is None or not election.strip():
        return candidates[0]
    wanted = election.strip()
    for item in candidates:
        if wanted in (item.date, item.date[:4]):
            return item
    raise InvalidInput(
        f"elections_provincial: {province} has general elections on "
        f"{[e.date for e in candidates]}; election must be one of those dates or its year."
    )


async def _load(election: constants.Election) -> tuple[list[District], bool]:
    if election.province == "bc":
        return await british_columbia.fetch(election.source_key)

    async def fetch() -> list[District]:
        if election.province == "qc":
            return await quebec.fetch(election.source_key)
        return await alberta.fetch(election.source_key)

    return await cached_fetch(
        f"elections_provincial:{election.province}:{election.source_key}",
        constants.CACHE_TTL_SECONDS,
        fetch,
    )


def _squash(text: str) -> str:
    """Folded text without dots and spaces, so 'CAQ' finds 'C.A.Q.-E.F.L.'."""
    return fold(text).replace(".", "").replace(" ", "")


def list_elections(province: str | None = None, lang: Lang = "en") -> ElectionList:
    code = _province(province) if province else None
    elections = [
        ElectionInfo(
            province=e.province,
            province_name=constants.PROVINCES[e.province][0 if lang == "en" else 1],
            date=e.date,
            seats=e.seats,
            detail=_DETAIL[e.province],
            source_url=_source_url(e),
        )
        for e in constants.ELECTIONS
        if code is None or e.province == code
    ]
    blocked = [
        BlockedSource(province=b.province, source=b.source, url=b.url, reason=b.reason)
        for b in constants.BLOCKED
    ]
    return ElectionList(
        elections=elections,
        blocked=blocked,
        notes=_NOTES[lang],
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=constants.QC_PAGE,
            cached=False,
            schema_name="elections_provincial.ElectionList",
            coverage="General elections: Quebec 1973-2022, Alberta 2008-2023, British "
            "Columbia 2005-2024.",
        ),
    )


async def get_results(
    province: str,
    election: str | None = None,
    district: str | None = None,
    party: str | None = None,
    candidate: str | None = None,
    winners_only: bool = False,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
) -> ElectionResults:
    code = _province(province)
    if not 1 <= limit <= constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"elections_provincial: limit must be 1 to {constants.ROWS_LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("elections_provincial: offset must be 0 or more.")
    edition = _election(code, election)
    districts, cached = await _load(edition)

    if district:
        wanted = fold(district)
        districts = [
            d
            for d in districts
            if wanted in fold(d.name) or wanted == (d.number or "").strip().lower()
        ]

    rows: list[tuple[District, ResultRow]] = []
    for d in districts:
        for c in d.candidates:
            if winners_only and not c.elected:
                continue
            if party and not (
                fold(party) in fold(c.party or "") or _squash(party) in _squash(c.party_code or "")
            ):
                continue
            if candidate and fold(candidate) not in fold(c.name or ""):
                continue
            rows.append(
                (
                    d,
                    ResultRow(
                        province=code,
                        election_date=edition.date,
                        district=d.name,
                        district_number=d.number,
                        candidate=c.name,
                        party=c.party,
                        party_code=c.party_code,
                        votes=c.votes,
                        vote_share=c.share,
                        elected=c.elected,
                    ),
                )
            )

    total = len(rows)
    page = rows[offset : offset + limit]
    seen: dict[str, District] = {}
    for d, _row in page:
        seen.setdefault(d.name, d)
    summaries = []
    for d in seen.values():
        top = next((c for c in d.candidates if c.elected), None)
        summaries.append(
            DistrictSummary(
                district=d.name,
                electors=d.electors,
                valid_votes=d.valid_votes,
                rejected_ballots=d.rejected_ballots,
                turnout=d.turnout,
                winner=(top.name or top.party) if top else None,
            )
        )
    truncated = offset + limit < total
    return ElectionResults(
        province=code,
        election_date=edition.date,
        rows=[row for _d, row in page],
        districts=summaries,
        total_rows=total,
        offset=offset,
        truncated=truncated,
        attribution=_attribution(code),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=_source_url(edition),
            cached=cached,
            schema_name="elections_provincial.ElectionResults",
            freshness="Official results are final; by-elections are not included.",
            coverage=f"{constants.PROVINCES[code][0]} general election of {edition.date}, "
            f"{edition.seats} districts.",
            limits=(
                f"Showing rows {offset + 1} to {offset + len(page)} of {total}."
                if truncated
                else None
            ),
        ),
    )


async def get_seats(province: str, election: str | None = None) -> SeatSummary:
    code = _province(province)
    edition = _election(code, election)
    districts, cached = await _load(edition)

    seats: dict[str, int] = {}
    votes: dict[str, int] = {}
    candidates: dict[str, int] = {}
    decided = 0
    total_valid = 0
    for d in districts:
        total_valid += d.valid_votes or 0
        decided += any(c.elected for c in d.candidates)
        for c in d.candidates:
            name = c.party or c.party_code or "Unknown"
            votes[name] = votes.get(name, 0) + c.votes
            candidates[name] = candidates.get(name, 0) + 1
            seats[name] = seats.get(name, 0) + int(c.elected)
    parties = [
        PartySummary(
            party=name,
            candidates=candidates[name],
            seats=seats[name],
            votes=votes[name],
            vote_share=round(100 * votes[name] / total_valid, 2) if total_valid else 0.0,
        )
        for name in votes
    ]
    parties.sort(key=lambda p: (-p.seats, -p.votes))
    return SeatSummary(
        province=code,
        election_date=edition.date,
        seats_contested=len(districts),
        seats_decided=decided,
        total_valid_votes=total_valid,
        parties=parties,
        attribution=_attribution(code),
        provenance=make_provenance(
            source=constants.PROVENANCE_SOURCE,
            url=_source_url(edition),
            cached=cached,
            schema_name="elections_provincial.SeatSummary",
            freshness="Computed from the district rows; by-elections are not included.",
            coverage=f"{constants.PROVINCES[code][0]} general election of {edition.date}.",
            limits="Independent candidates appear under the label each source uses.",
        ),
    )

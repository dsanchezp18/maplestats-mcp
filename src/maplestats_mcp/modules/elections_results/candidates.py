"""Candidate-level results of every federal election, 1867 to 2021.

Source: Semra Sevi, "Who Runs? Canadian Federal and Ontario Provincial
Candidates since 1867", Harvard Dataverse, https://doi.org/10.7910/DVN/ABFNSQ,
licence CC0 1.0 (version 9, released 2024-04-11). Checked live 2026-10-01: the
labelled federal file "federal-candidates-2023-12-11rev.tab" (16.6 MB, 46,526
candidate rows, tab-separated, UTF-8) holds one row per candidate per riding
with name, party, votes, share and an elected flag, for 44,077 general-election
and 2,449 by-election rows. The author compiled the rows from the Library of
Parliament's ParlInfo and, for 2021, from Elections Canada.
"""

from __future__ import annotations

import csv
import io
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from maplestats_mcp.modules.elections_results.historical import _fold
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_parse
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

DATASET_DOI = "https://doi.org/10.7910/DVN/ABFNSQ"
DATASET_FILE_URL = "https://dataverse.harvard.edu/api/access/datafile/10100743"
CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_FILE_BYTES = 40 * 1024 * 1024
ROWS_LIMIT_DEFAULT = 50
ROWS_LIMIT_MAX = 1000
FIRST_ELECTION = 1
LAST_ELECTION = 44

ElectionType = Literal["general", "by-election", "all"]
_TYPES = {"general": "General", "by-election": "By-election"}

_LIMITER = get_limiter("dataverse-who-runs", rate=0.5, capacity=2.0)


class HistoricalCandidate(BaseModel):
    candidate_id: int | None = Field(
        description="The dataset's person id, the same across elections and ridings."
    )
    candidate_name: str = Field(description="As published, 'SURNAME, Given names'.")
    election: int = Field(description="Parliament number: 36 = 1997, 37 = 2000, 1 = 1867.")
    election_year: int
    election_date: str | None
    election_type: str = Field(description="'General' or 'By-election'.")
    province: str
    riding: str
    party: str = Field(description="Party label as published by ParlInfo.")
    votes: int | None
    vote_share_percent: float | None
    elected: bool
    acclaimed: bool
    incumbent: bool | None
    gender: str | None
    occupation: str | None


class HistoricalCandidates(BaseModel):
    candidates: list[HistoricalCandidate]
    total_candidates: int
    elected_in_selection: int
    offset: int
    truncated: bool
    licence: str
    citation: str
    provenance: Provenance


def _int(value: str) -> int | None:
    return int(float(value)) if value.strip() else None


def _float(value: str) -> float | None:
    return float(value) if value.strip() else None


def _parse(body: bytes) -> list[dict[str, str]] | None:
    """The file's rows, or None when its layout is not the expected one."""
    text = body.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    if not rows or "candidate_name" not in rows[0] or "party_raw" not in rows[0]:
        return None
    return rows


async def _dataset(lang: str = "en") -> tuple[list[dict[str, str]], bool]:
    async def fetch() -> list[dict[str, str]]:
        await _LIMITER.acquire()
        # Dataverse answers 303 with a signed storage URL; the shared client
        # does not follow redirects.
        current = DATASET_FILE_URL
        for _ in range(4):
            try:
                response = await get_raw(current, timeout=180.0)
                break
            except httpx.HTTPStatusError as exc:
                location = exc.response.headers.get("location")
                if exc.response.status_code in (301, 302, 303, 307, 308) and location:
                    current = str(exc.response.url.join(location))
                    if not current.startswith("https://"):
                        raise lang_error(
                            UpstreamError,
                            lang,
                            "elections_results: redirect to a non-https URL.",
                            "elections_results : redirection vers une adresse non https.",
                        ) from exc
                    continue
                raise lang_error(
                    UpstreamError,
                    lang,
                    f"elections_results: Harvard Dataverse returned HTTP "
                    f"{exc.response.status_code}.",
                    f"elections_results : Harvard Dataverse a renvoyé HTTP "
                    f"{exc.response.status_code}.",
                ) from exc
            except httpx.HTTPError as exc:
                raise lang_error(
                    UpstreamUnavailable,
                    lang,
                    "elections_results: Harvard Dataverse did not respond in time.",
                    "elections_results : Harvard Dataverse n'a pas répondu à temps.",
                ) from exc
        else:
            raise lang_error(
                UpstreamError,
                lang,
                "elections_results: Harvard Dataverse redirected too many times.",
                "elections_results : Harvard Dataverse a redirigé trop de fois.",
            )
        if len(response.content) > MAX_FILE_BYTES:
            raise lang_error(
                UpstreamError,
                lang,
                "elections_results: the candidate file is larger than expected.",
                "elections_results : le fichier des candidats est plus volumineux que prévu.",
            )
        rows = await run_parse(_parse, response.content)
        if rows is None:
            raise lang_error(
                UpstreamError,
                lang,
                "elections_results: the candidate file has an unexpected layout.",
                "elections_results : le fichier des candidats a une structure inattendue.",
            )
        return rows

    return await cached_fetch("elections_results:candidates", CACHE_TTL_SECONDS, fetch)


def _candidate(row: dict[str, str]) -> HistoricalCandidate:
    incumbent = row.get("incumbent", "")
    return HistoricalCandidate(
        candidate_id=_int(row["id"]),
        candidate_name=row["candidate_name"],
        election=_int(row["parliament"]) or 0,
        election_year=_int(row["year"]) or 0,
        election_date=row.get("edate") or None,
        election_type=row["type_elxn"],
        province=row["province"],
        riding=row["riding"],
        party=row["party_raw"],
        votes=_int(row["votes"]),
        vote_share_percent=_float(row["percent_votes"]),
        elected=row["elected"] == "Elected",
        acclaimed=row["acclaimed"] == "Acclaimed",
        incumbent=None if not incumbent else incumbent == "Incumbent",
        gender=row.get("gender") or None,
        occupation=row.get("occupation") or None,
    )


async def get_candidates(
    election: int | None = None,
    year: int | None = None,
    province: str | None = None,
    riding: str | None = None,
    candidate: str | None = None,
    party: str | None = None,
    winners_only: bool = False,
    election_type: ElectionType = "general",
    limit: int = ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> HistoricalCandidates:
    if election is not None and not FIRST_ELECTION <= election <= LAST_ELECTION:
        raise lang_error(
            InvalidInput,
            lang,
            f"elections_results: election must be {FIRST_ELECTION} to {LAST_ELECTION} "
            "(1867 to 2021).",
            f"elections_results : election doit être entre {FIRST_ELECTION} et {LAST_ELECTION} "
            "(1867 à 2021).",
        )
    if election_type not in ("general", "by-election", "all"):
        raise lang_error(
            InvalidInput,
            lang,
            "elections_results: election_type must be general, by-election or all.",
            "elections_results : election_type doit être general, by-election ou all.",
        )
    if not 1 <= limit <= ROWS_LIMIT_MAX:
        raise lang_error(
            InvalidInput,
            lang,
            f"elections_results: limit must be 1 to {ROWS_LIMIT_MAX}.",
            f"elections_results : limit doit être compris entre 1 et {ROWS_LIMIT_MAX}.",
        )
    if offset < 0:
        raise lang_error(
            InvalidInput,
            lang,
            "elections_results: offset must be 0 or more.",
            "elections_results : offset doit être 0 ou plus.",
        )

    rows, cached = await _dataset(lang)
    if election_type != "all":
        wanted_type = _TYPES[election_type]
        rows = [r for r in rows if r["type_elxn"] == wanted_type]
    if election is not None:
        rows = [r for r in rows if _int(r["parliament"]) == election]
        # year=2000 with election=36 (held in 1997) was an empty success;
        # contradictory filters are an input error naming the right year(s).
        years = sorted({y for r in rows if (y := _int(r["year"])) is not None})
        if year is not None and years and year not in years:
            held = ", ".join(str(y) for y in years)
            raise lang_error(
                InvalidInput,
                lang,
                f"elections_results: election {election} ({election_type} rows) was held in "
                f"{held}, not {year}; give one of those years, or only election or year.",
                f"elections_results : l'élection {election} (lignes {election_type}) a eu lieu "
                f"en {held}, pas en {year} ; donnez l'une de ces années, ou seulement election "
                "ou year.",
            )
    if year is not None:
        rows = [r for r in rows if _int(r["year"]) == year]
    for column, text in (
        ("province", province),
        ("riding", riding),
        ("candidate_name", candidate),
        ("party_raw", party),
    ):
        if text:
            needle = _fold(text)
            rows = [r for r in rows if needle in _fold(r[column])]
    if winners_only:
        rows = [r for r in rows if r["elected"] == "Elected"]

    total = len(rows)
    elected = sum(1 for r in rows if r["elected"] == "Elected")
    page = [_candidate(r) for r in rows[offset : offset + limit]]
    return HistoricalCandidates(
        candidates=page,
        total_candidates=total,
        elected_in_selection=elected,
        offset=offset,
        truncated=offset + limit < total,
        licence=fr_or_en(
            lang,
            "CC0 1.0 (public domain dedication)",
            "CC0 1.0 (dévouement au domaine public)",
        ),
        citation=(
            'Sevi, S. "Who Runs? Canadian Federal and Ontario Provincial Candidates from 1867 '
            f'to 2019." Canadian Journal of Political Science 54(2): 471-476. Data: {DATASET_DOI}.'
        ),
        provenance=make_provenance(
            source="harvard-dataverse-who-runs-federal-candidates",
            url=DATASET_DOI,
            cached=cached,
            schema_name="elections_results.HistoricalCandidates",
            freshness=fr_or_en(
                lang,
                "Dataverse version 9 (2024-04-11): the 1st to 44th general elections "
                "(1867 to 2021) and by-elections; later elections are in "
                "elections_results_get_table.",
                "Dataverse, version 9 (2024-04-11) : les 1re à 44e élections générales (1867 à "
                "2021) et les élections partielles ; les élections suivantes sont dans "
                "elections_results_get_table.",
            ),
            coverage=fr_or_en(
                lang,
                "Compiled by the author from the Library of Parliament's ParlInfo and, for "
                "2021, Elections Canada: not an official publication. Elected counts match the "
                "House closely but not always exactly (for example 281 of 282 seats in 1980 and "
                "1984). Cross-check the 38th to 45th with elections_results_get_table.",
                "Compilé par l'auteur à partir de ParlInfo de la Bibliothèque du Parlement et, "
                "pour 2021, d'Élections Canada : ce n'est pas une publication officielle. Le "
                "nombre d'élus concorde de près avec la Chambre, mais pas toujours exactement "
                "(p. ex. 281 des 282 sièges en 1980 et en 1984). Recoupez les 38e à 45e avec "
                "elections_results_get_table.",
            ),
            limits=join_limits(
                fr_or_en(
                    lang,
                    f"Showing rows {offset + 1} to {offset + len(page)} of {total}.",
                    f"Lignes {offset + 1} à {offset + len(page)} sur {total}.",
                )
                if offset + limit < total
                else None,
                fr_or_en(
                    lang,
                    "",
                    "Noms, partis, circonscriptions et professions viennent du jeu de données, en "
                    "anglais seulement (élu, sortant : champs elected, incumbent)",
                )
                or None,
            ),
            lang=lang,
        ),
    )

"""Client for IRCC's inventories-and-backlogs page (see constants.py for its shape).

The page is HTML with no documented contract, so the parser checks the shape
it reads (seven program tables, each with the three expected column headings
and month rows) and raises UpstreamError naming what changed, rather than
returning a partial answer. The page is parsed once and cached for an hour.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import NoReturn

import httpx

from maplestats_mcp.modules.ircc.backlog import constants
from maplestats_mcp.modules.ircc.backlog.schemas import (
    BacklogProgram,
    BacklogResult,
    BacklogRow,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# Month abbreviations as the page writes them in either language, folded
# (accents and dots removed): "Jan 22", "janv. 22", "févr. 22", "juill. 22".
_MONTHS = {
    "jan": 1,
    "janv": 1,
    "feb": 2,
    "fev": 2,
    "fevr": 2,
    "mar": 3,
    "mars": 3,
    "apr": 4,
    "avr": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "juin": 6,
    "jul": 7,
    "juil": 7,
    "juill": 7,
    "aug": 8,
    "aout": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_CELL = re.compile(r"^([a-z]+) (\d{2})$")
_PERCENT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*%$")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", stripped.casefold()).split())


class _Tables(HTMLParser):
    """Collects each <table>'s rows of cell text with the last <h3> text before it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[str, list[list[str]]]] = []
        self._heading = ""
        self._in_h3 = False
        self._rows: list[list[str]] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h3":
            self._in_h3 = True
            self._heading = ""
        elif tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3":
            self._in_h3 = False
        elif tag in ("td", "th") and self._cell is not None and self._rows:
            self._rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "table" and self._rows is not None:
            self.tables.append((self._heading, self._rows))
            self._rows = None

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._heading += data
        if self._cell is not None:
            self._cell.append(data)


def _shape_error(lang: str, expected: str) -> NoReturn:
    page = pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR)
    raise_localized(
        UpstreamError,
        f"IRCC's inventories and backlogs page is no longer shaped as MapleStats reads it "
        f"({expected}). IRCC documents no API for it; read the tables on {page}.",
        f"la page des inventaires et arriérés d'IRCC n'a plus la forme que MapleStats lit "
        f"({expected}). IRCC ne documente aucune API ; consultez les tableaux sur {page}.",
        lang,
    )


def _month(text: str, lang: str) -> date:
    match = _MONTH_CELL.match(_fold(text))
    month = _MONTHS.get(match.group(1)) if match else None
    if match is None or month is None:
        _shape_error(lang, f"month cell {text!r} is not like 'Jan 22'")
    return date(2000 + int(match.group(2)), month, 1)


def _percent(text: str, lang: str) -> float | None:
    cleaned = text.replace("\xa0", " ").replace(" ", " ").strip()
    if cleaned in ("-", "–", "—", ""):
        return None
    match = _PERCENT.match(cleaned)
    if match is None:
        _shape_error(lang, f"value cell {text!r} is neither a percentage nor '-'")
    return float(match.group(1).replace(",", "."))


def parse_page(markup: str, lang: str = "en") -> dict[str, list[BacklogRow]]:
    """program_id -> monthly rows, for every program table on the page."""
    parser = _Tables()
    parser.feed(markup)
    found: dict[str, list[BacklogRow]] = {}
    keyword = 3 if lang == "en" else 4
    for heading, rows in parser.tables:
        header = [_fold(c) for c in rows[0]] if rows else []
        if len(header) != 3 or not header[0].startswith(("month", "mois")):
            continue
        folded = _fold(html.unescape(heading))
        program = next((p for p in constants.PROGRAMS if p[keyword] in folded), None)
        if program is None:
            _shape_error(lang, f"table heading {heading.strip()!r} matches no known program")
        if program[0] in found:
            _shape_error(lang, f"two tables match the program {program[0]}")
        table: list[BacklogRow] = []
        for cells in rows[1:]:
            if len(cells) != 3:
                _shape_error(lang, f"a row of {program[0]} has {len(cells)} cells, not 3")
            table.append(
                BacklogRow(
                    program_id=program[0],
                    month=_month(cells[0], lang),
                    backlog_actual_pct=_percent(cells[1], lang),
                    backlog_projected_pct=_percent(cells[2], lang),
                )
            )
        if not table:
            _shape_error(lang, f"the table for {program[0]} has no rows")
        found[program[0]] = table
    if len(found) != len(constants.PROGRAMS):
        _shape_error(lang, f"{len(found)} program tables found, expected {len(constants.PROGRAMS)}")
    return found


async def _download(lang: str) -> str:
    url = pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR)
    await _LIMITER.acquire()
    try:
        response = await get_raw(url)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500:
            raise_localized(
                UpstreamUnavailable,
                f"canada.ca returned HTTP {status} for {url}. Try again shortly.",
                f"canada.ca a renvoyé HTTP {status} pour {url}. Réessayez sous peu.",
                lang,
            )
        raise_localized(
            UpstreamError,
            f"canada.ca returned HTTP {status} for {url}: IRCC may have moved the page.",
            f"canada.ca a renvoyé HTTP {status} pour {url} : IRCC a peut-être déplacé la page.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"canada.ca did not answer for {url} after the shared retries. Try again shortly.",
            f"canada.ca n'a pas répondu pour {url} malgré les nouvelles tentatives. "
            "Réessayez sous peu.",
            lang,
        )
    return response.content.decode("utf-8", errors="replace")


def _parse_bound(value: str | None, name: str, lang: str = "en") -> date | None:
    """'2024-06' or '2024-06-15' -> the first day of that month."""
    if value is None:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}", text):
        text += "-01"
    try:
        return date.fromisoformat(text).replace(day=1)
    except ValueError:
        pass
    raise_localized(
        InvalidInput,
        f"{name} must be a month like 2024-06, got {value!r}.",
        f"{name} doit être un mois comme 2024-06, reçu {value!r}.",
        lang,
    )


def _program_ids(program: str | None, lang: str = "en") -> list[str]:
    ids = [p[0] for p in constants.PROGRAMS]
    if program is None:
        return ids
    folded = _fold(program)
    exact = [p[0] for p in constants.PROGRAMS if folded in (p[0].replace("_", " "), _fold(p[1]))]
    matches = exact or [
        p[0]
        for p in constants.PROGRAMS
        if folded in _fold(f"{p[1]} {p[2]} {p[0].replace('_', ' ')}")
    ]
    if len(matches) != 1:
        kind_en = "matches several programs" if matches else "matches no program"
        kind_fr = (
            "correspond à plusieurs programmes" if matches else "ne correspond à aucun programme"
        )
        raise_localized(
            InvalidInput,
            f"program {program!r} {kind_en}; use one of: {', '.join(ids)}.",
            f"program {program!r} {kind_fr} ; utilisez l'un de : {', '.join(ids)}.",
            lang,
        )
    return matches


async def get_backlog(
    program: str | None = None,
    since: str | None = None,
    until: str | None = None,
    lang: str = "en",
) -> BacklogResult:
    ids = _program_ids(program, lang)
    start = _parse_bound(since, "since", lang)
    end = _parse_bound(until, "until", lang)

    async def fetch() -> dict[str, list[BacklogRow]]:
        return parse_page(await _download(lang), lang)

    tables, was_cached = await cached_fetch(
        f"ircc:backlog:{lang}", constants.CACHE_TTL_SECONDS, fetch
    )

    programs: list[BacklogProgram] = []
    rows: list[BacklogRow] = []
    for program_id in ids:
        table = tables[program_id]
        actual = [r.month for r in table if r.backlog_actual_pct is not None]
        projected = [r.month for r in table if r.backlog_projected_pct is not None]
        known = next(p for p in constants.PROGRAMS if p[0] == program_id)
        programs.append(
            BacklogProgram(
                program_id=program_id,
                label=pick(lang, known[1], known[2]),
                first_month=table[0].month,
                last_actual_month=max(actual) if actual else None,
                last_projected_month=max(projected) if projected else None,
            )
        )
        rows.extend(
            r
            for r in table
            if (start is None or r.month >= start) and (end is None or r.month <= end)
        )
    last_actuals = [p.last_actual_month for p in programs if p.last_actual_month]
    latest = f"{min(last_actuals):%Y-%m}" if last_actuals else "none"
    notes = [
        pick(
            lang,
            "Backlog here is IRCC's measure of applications in its inventory that are beyond "
            "its service standard, shown as a percentage of the inventory; it is not a "
            "processing time and says nothing about how long one application will take "
            "(use ircc_processing_get_time for IRCC's processing-time estimates). The page "
            "shows percentages only: the inventory counts are not in its tables.",
            "L'arriéré est ici la mesure d'IRCC des demandes de son inventaire qui dépassent "
            "sa norme de service, en pourcentage de l'inventaire ; ce n'est pas un délai de "
            "traitement et il ne dit rien de la durée d'une demande en particulier (voir "
            "ircc_processing_get_time pour les délais). La page ne donne que des "
            "pourcentages : les effectifs de l'inventaire ne figurent pas dans ses tableaux.",
        ),
        pick(
            lang,
            f"The earliest last-actual month among the programs returned is {latest}; later "
            "months, where shown, are IRCC's earlier projections, not outcomes. The page's "
            "own modified date can be newer than its tables.",
            f"Le plus ancien dernier mois réel parmi les programmes retournés est {latest} ; "
            "les mois suivants, le cas échéant, sont des projections antérieures d'IRCC, non "
            "des résultats. La date de modification de la page peut être plus récente que "
            "ses tableaux.",
        ),
    ]
    return BacklogResult(
        programs=programs,
        rows=rows,
        returned_count=len(rows),
        notes=notes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR),
            cached=was_cached,
            schema_name="ircc.backlog",
            as_of=datetime.now(UTC),
            freshness=pick(
                lang,
                "IRCC's inventories and backlogs page, read now; its tables run to the "
                "months shown in each program's last_actual_month.",
                "Page des inventaires et arriérés d'IRCC, lue maintenant ; ses tableaux "
                "vont jusqu'aux mois indiqués dans last_actual_month de chaque programme.",
            ),
            coverage=pick(
                lang,
                "Seven programs (Express Entry federal and provincial nominee, spouses, "
                "partners and children, citizenship grant, temporary resident visas, study "
                "permits, work permits), monthly from January 2022.",
                "Sept programmes (Entrée express fédéral et candidats des provinces, "
                "époux, conjoints et enfants, attribution de la citoyenneté, visas de "
                "résident temporaire, permis d'études, permis de travail), mensuel depuis "
                "janvier 2022.",
            ),
            lang=lang,
        ),
    )

"""HTTP client for Canadian Food Inspection Agency (CFIA) animal disease tables.

Three kinds of HTML page on inspection.canada.ca, all fetched live on
2026-09-26 in English and French (see constants.py for the URLs, robots
and terms):

- "Federally reportable diseases for terrestrial animals in Canada": one
  table per year, 2011 to 2026, of confirmed herds or flocks per disease.
  It gives yearly totals only; each total links to a per-disease "data by
  month" page.
- Those per-disease pages: one row per confirmation (year, day and month,
  province, animal type) for chronic wasting disease, scrapie, bovine
  tuberculosis, cysticercosis, BSE, trichinellosis and avian influenza
  before 2021.
- "Investigations and orders of avian influenza in domestic birds by
  province": one row per infected premises since December 2021 (662 rows:
  12 current, 650 released), and the "status by province" table of
  current and released premises and birds impacted.

Quirks confirmed live and handled here:

1. The yearly tables are Disease/Total pairs under an <h2> holding the
   year (inside <details><summary> for past years). Count cells read
   "19 (data by month)". The French page orders diseases alphabetically
   by French name and writes some names differently across years
   ("Tremblante" and "Tremblante du mouton"; "Notifiable avian influenza"
   2014-2016 and "Avian Influenza" from 2021), so rows are keyed by a
   canonical disease key, never by position. Anaplasmosis (2011, 2013)
   and anthrax (2011, 2012) carry table notes: anaplasmosis left the
   federally reportable list on April 1, 2014, and the CFIA no longer
   reports anthrax detections.
2. The French pages hold data errors the English ones do not: the French
   scrapie page dates a 2019 flock "21 huin", the French avian influenza
   page dates a December 19, 2014 flock "9 décembre", and the French
   premises table gives six premises a different detection date
   (AB-IP116 on September 25 against 26; ON-IP58 on February 12 against
   21) and malformed sort keys ("202411222", "2022061er") on twelve more.
   Dates, counts and statuses therefore always come from the English
   page; with lang="fr" the French page supplies the labels (location,
   animal type, control zone, published date text), joined by premises
   id or, for detection pages, by row only when every row's year lines
   up.
3. Detection rows can stand for several herds: "Elk (3 herds)",
   "Wapiti (3 troupeaux)". Counting those makes the rows add up to the
   yearly totals (CWD 2025: 7 rows, 9 herds). One bovine TB row's
   location is "Alberta and Saskatchewan".
4. Premises ids hide a sort padding digit: "BC-IP<span class="wb-inv">0
   </span>99" displays as BC-IP99. A current premises has a hidden
   "quarantine" span; a released one has a "*" table-note link, usually
   inside <sup> but on QC-IP65 not, and on AB-IP84 with the French label
   "Note de bas de page" on the English page. On the French page the
   location of AB-IP104 sits inside the <sup>.
5. Premises cells vary: "commercial", "Non-commercial", "captive wild"
   (untranslated on the French page too), "non- commerciale"; the WOAH
   column holds "N/A - LPAI" (with a no-break space on some rows) for
   four low pathogenic premises; N/A is also "s.o.", "S.O", "o.s."; the
   order column can hold two orders ("Revoked" then "PCZ-239 Revoked")
   and "Released" or "Zone libérée" for premises without a zone.
6. The status table writes "Under 100" / "Moins de 100" birds for New
   Brunswick, groups French thousands with spaces, and on 2026-09-26 had
   "`0" for British Columbia's current premises on the French page. The
   French premises table spells Prince Edward Island "Île-Prince-Édouard".
7. Yearly totals and premises counts are kept separately and do not
   always agree (avian influenza 2022: 279 flocks in the yearly table,
   280 premises detected that year); both are reported as published.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal, NoReturn, cast
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.cfia import constants
from maplestats_mcp.modules.cfia.schemas import (
    AvianInfluenzaResult,
    CountTotal,
    DetectionCount,
    DiseaseDetection,
    DiseaseDetectionResult,
    DiseaseYearCount,
    InfectedPremises,
    PremisesCount,
    PremisesStatus,
    ProvinceStatus,
    ProvinceStatusSummary,
    ReportableDiseaseResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_error
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SOURCE = constants.RATE_LIMIT_SOURCE

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}
Woah = Literal["poultry", "non_poultry"]
Order = Literal["active", "revoked", "released"]
StatusFilter = Literal["current", "released", "all"]

_NOT_APPLICABLE = {"n/a", "na", "s.o.", "s.o", "so", "o.s.", "os", "-", ""}
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

# What the parsers check each page against, kept here (not inline) so
# reproduce/cfia.py writes the same checks and spellings into its scripts.
# Header cells are compared folded (_fold), without hidden text.
YEAR_HEADING = re.compile(r"(19|20)\d{2}")
AS_OF = re.compile(r"(?:Current as of|À jour en date du)\s*:?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
REPORTABLE_COLUMNS = (["disease", "total"], ["maladie", "total"])
DETECTION_COLUMNS = (("year", "annee"), "date", ("location", "lieu"))
PREMISES_TABLE_ID = "dataset-filter"
PREMISES_COLUMNS = (
    ("date detected", "date de detection"),
    "province",
    ("premises type", "type de lieu"),
)
STATUS_FIRST_COLUMN = "province"
# Premises cells, compared folded with everything but letters removed.
PREMISES_TYPES = {
    "commercial": ("commercial", "commerciale"),
    "non_commercial": ("noncommercial", "noncommerciale"),
    "captive_wild": ("captivewild", "fauneencaptivite", "sauvagecaptif"),
}
WOAH_CLASSES = {
    "poultry": ("poultry", "volailles", "volaille"),
    "non_poultry": ("nonpoultry", "nonvolailles", "nonvolaille"),
}
LOW_PATHOGENIC = ("lpai", "iafp")
# The order column's first line, folded, starts with one of these.
ORDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "active": ("active", "actif"),
    "revoked": ("revoked", "revoque"),
    "released": ("released", "zone liberee", "liberee", "libere"),
}
QUARANTINE_MARKER = "quarant"
# "Alberta and Saskatchewan", "Alberta et Saskatchewan" (folded).
LOCATION_SEPARATORS = re.compile(r",|\band\b|\bet\b|/")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lowercase without accents, so 'Débilitante' matches 'debilitante'.

    Same approach as recalls/client.py: typographic apostrophes become
    "'" (the French pages mix both), ligatures are spelled out, and runs
    of whitespace (including no-break spaces) become one space.
    """
    text = text.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae")
    text = text.replace("’", "'").replace("‘", "'")
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _lang(lang: str) -> str:
    if lang not in ("en", "fr"):
        raise_error(InvalidInput, "error.invalid_input", "en", detail="lang must be 'en' or 'fr'.")
    return lang


def _today() -> date:
    return datetime.now(ZoneInfo(constants.REFERENCE_TZ)).date()


def _as_datetime(value: date | None) -> datetime | None:
    """A page's 'Date modified' as midnight Ottawa time, in UTC."""
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=ZoneInfo(constants.REFERENCE_TZ)).astimezone(
        UTC
    )


def _invalid(lang: str, detail: str) -> NoReturn:
    raise_error(InvalidInput, "error.invalid_input", lang, detail=f"cfia: {detail}")


def _changed(url: str, detail: str) -> NoReturn:
    """A page no longer has the structure the parser checks for: raise, never guess."""
    raise_error(
        UpstreamError,
        "error.upstream_error",
        "en",
        detail=f"cfia: the page layout changed at {url} ({detail}); nothing was returned "
        "rather than risk wrong figures.",
    )


def month_number(text: str) -> int | None:
    word = _fold(text).rstrip(".")
    return _MONTHS.get(word)


def parse_day_month(text: str, year: int) -> date | None:
    """'July 6', '6 Juillet', '1er juin' with the row's year -> a date, or None."""
    words = re.findall(r"[^\W\d_]+|\d+", _fold(text))
    day = month = None
    for word in words:
        if word.isdigit() and day is None:
            day = int(word)
        elif word in _MONTHS and month is None:
            month = _MONTHS[word]
    if day is None or month is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_long_date(text: str) -> date | None:
    """'September 26, 2026' or '16 mai 2026' -> a date, or None."""
    match = re.search(r"(\d{4})\s*$", _fold(text))
    return parse_day_month(text, int(match.group(1))) if match else None


def province_code(text: str) -> str | None:
    """A province or territory code from a code, English or French name."""
    value = _fold(text)
    if value.upper() in constants.PROVINCES:
        return value.upper()
    for code, names in constants.PROVINCES.items():
        if value in {_fold(name) for name in names}:
            return code
    return constants.PROVINCE_ALIASES.get(value)


def province_codes_in(location: str) -> list[str]:
    """Codes for each province named in 'Alberta and Saskatchewan' or 'Alberta et Saskatchewan'."""
    parts = LOCATION_SEPARATORS.split(_fold(location))
    codes: list[str] = []
    for part in parts:
        code = province_code(part.strip())
        if code and code not in codes:
            codes.append(code)
    return codes


def province_label(code: str, lang: str) -> str:
    names = constants.PROVINCES.get(code)
    if not names:
        return code
    return names[1] if lang == "fr" else names[0]


def _disease_candidates(key: str) -> set[str]:
    english, french, aliases = constants.DISEASES[key]
    return {key.replace("_", " "), _fold(english), _fold(french), *(_fold(a) for a in aliases)}


def disease_key(name: str) -> str:
    """The canonical key for a disease name as a page writes it.

    A name not in constants.DISEASES keeps a key built from its own
    words, so a disease the CFIA adds later still appears (and can be
    filtered by name) rather than being dropped.
    """
    folded = _fold(name)
    for key in constants.DISEASES:
        if folded in _disease_candidates(key):
            return key
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_") or "unknown"


def disease_label(key: str, lang: str, fallback: str | None = None) -> str:
    info = constants.DISEASES.get(key)
    if info is None:
        return fallback or key
    return info[1] if lang == "fr" else info[0]


def match_diseases(query: str) -> set[str]:
    """Disease keys a user query names: exact name or alias first, then substrings.

    'CWD', 'maladie débilitante chronique' and 'Chronic Wasting' all give
    chronic_wasting_disease; 'bovine' gives every bovine disease.
    """
    folded = _fold(query).replace("_", " ")
    if not folded:
        return set()
    exact = {key for key in constants.DISEASES if folded in _disease_candidates(key)}
    if exact:
        return exact
    if len(folded) < 3:
        return set()
    return {
        key
        for key in constants.DISEASES
        if any(folded in candidate for candidate in _disease_candidates(key))
    }


def _known_diseases(lang: str) -> str:
    return ", ".join(f"{key} ({disease_label(key, lang)})" for key in constants.DISEASES)


def parse_period(text: str, *, end: bool, lang: str) -> date:
    """'2026', '2026-09' or '2026-09-26' -> the first (or last) day it covers."""
    value = text.strip()
    try:
        if re.fullmatch(r"\d{4}", value):
            year = int(value)
            return date(year, 12, 31) if end else date(year, 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = (int(part) for part in value.split("-"))
            last = calendar.monthrange(year, month)[1]
            return date(year, month, last if end else 1)
        return date.fromisoformat(value)
    except ValueError:
        _invalid(lang, f"dates must be YYYY, YYYY-MM or YYYY-MM-DD, got {text!r}.")


def parse_int(text: str) -> int | None:
    """'2,552,000', '2 552 000', '`0' -> an int; 'Under 100' -> None.

    The backtick is a typo on the French status page (2026-09-26).
    """
    value = text.replace("\xa0", " ").replace(" ", " ").strip().strip("`'")
    if re.fullmatch(r"\d{1,3}([ ,]\d{3})+|\d+", value):
        return int(re.sub(r"[ ,]", "", value))
    return None


# ---------------------------------------------------------------------------
# Fetching and page structure
# ---------------------------------------------------------------------------


async def _fetch(url: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            # The site answers 410 Gone for pages it retired or moved.
            _changed(url, f"HTTP {status}, the page moved")
        raise_error(
            UpstreamUnavailable if status >= 500 else UpstreamError,
            "error.upstream_unavailable" if status >= 500 else "error.upstream_error",
            "en",
            detail=f"cfia: {url} returned HTTP {status}.",
        )
    except httpx.HTTPError as exc:
        raise_error(
            UpstreamUnavailable,
            "error.upstream_unavailable",
            "en",
            detail=f"cfia: {url} could not be reached ({type(exc).__name__}).",
        )
    if len(response.content) > constants.MAX_PAGE_BYTES:
        _changed(url, "the page is much larger than expected")
    return response.text


async def _parsed[T](
    kind: str, url: str, ttl: int, parser: Callable[[str, str], T]
) -> tuple[T, bool]:
    """Fetch and parse `url`, caching the parsed result (never a failed parse)."""

    async def fetch() -> T:
        return parser(await _fetch(url), url)

    fetcher: Callable[[], Awaitable[T]] = fetch
    return await cached_fetch(f"cfia:{kind}:{url}", ttl, fetcher)


def _main(soup: BeautifulSoup, url: str) -> Tag:
    main = soup.find("main")
    if not isinstance(main, Tag):
        _changed(url, "no <main> element")
    return main


def date_modified(soup: BeautifulSoup | Tag) -> date | None:
    """The 'Date modified' footer (<time property="dateModified">2026-09-10</time>)."""
    node = soup.find("time", attrs={"property": "dateModified"})
    if not isinstance(node, Tag):
        return None
    match = _ISO_DATE.search(node.get_text())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def page_title(soup: BeautifulSoup | Tag) -> str | None:
    """The page's <h1>, which the Canada.ca terms ask a reproduction to credit."""
    node = soup.find("h1")
    if not isinstance(node, Tag):
        return None
    return _clean(node.get_text(" ")) or None


def _table_notes(main: Tag) -> dict[str, str]:
    """Table note text by id ('fn1' -> 'Atypical scrapie'), without the return link."""
    notes: dict[str, str] = {}
    for dd in main.find_all("dd", id=True):
        for back in dd.select(".fn-rtn"):
            back.decompose()
        notes[str(dd["id"])] = _clean(dd.get_text(" "))
    return notes


def _strip_notes(cell: Tag, notes: dict[str, str]) -> tuple[str, str | None]:
    """A cell's text without its table-note markers, and the notes they point to."""
    found: list[str] = []
    for link in cell.find_all("a", class_="fn-lnk"):
        target = str(link.get("href", "")).lstrip("#")
        if target in notes and notes[target] not in found:
            found.append(notes[target])
        link.decompose()
    for sup in cell.find_all("sup"):
        sup.unwrap()
    return _clean(cell.get_text(" ")), "; ".join(found) or None


def _header_cells(table: Tag) -> list[str]:
    head = table.find("thead")
    row = head.find("tr") if isinstance(head, Tag) else table.find("tr")
    if not isinstance(row, Tag):
        return []
    cells = []
    for cell in row.find_all(["th", "td"]):
        for hidden in cell.select(".wb-inv, .glyphicon"):
            hidden.decompose()
        cells.append(_fold(cell.get_text(" ")))
    return cells


def _body_rows(table: Tag) -> list[Tag]:
    body = table.find("tbody")
    rows = (body if isinstance(body, Tag) else table).find_all("tr")
    return [row for row in rows if isinstance(row, Tag) and row.find("td")]


# ---------------------------------------------------------------------------
# Federally reportable diseases: yearly totals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _YearRow:
    year: int
    key: str
    name: str
    count: int
    note: str | None


@dataclass(frozen=True)
class _ReportablePage:
    rows: tuple[_YearRow, ...]
    current_as_of: date | None
    modified: date | None
    title: str | None = None


def parse_reportable_page(page: str, url: str) -> _ReportablePage:
    soup = BeautifulSoup(page, "html.parser")
    main = _main(soup, url)
    modified = date_modified(soup)
    notes = _table_notes(main)
    text = _clean(main.get_text(" "))
    as_of_match = AS_OF.search(text)
    current_as_of = date.fromisoformat(as_of_match.group(1)) if as_of_match else None

    tables = main.find_all("table")
    if not tables:
        _changed(url, "no yearly tables")
    rows: list[_YearRow] = []
    for table in tables:
        heading = table.find_previous("h2")
        year_text = _clean(heading.get_text(" ")) if isinstance(heading, Tag) else ""
        if not YEAR_HEADING.fullmatch(year_text):
            _changed(url, f"a table is not under a year heading ({year_text[:40]!r})")
        header = _header_cells(table)
        if header[:2] not in REPORTABLE_COLUMNS:
            _changed(url, f"unexpected columns {header}")
        for tr in _body_rows(table):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            name, note = _strip_notes(cells[0], notes)
            count_text = _clean(cells[1].get_text(" "))
            match = re.match(r"\d[\d ,]*", count_text)
            if not name and not count_text:
                continue
            count = parse_int(match.group(0).strip()) if match else None
            if not name or count is None:
                _changed(url, f"unreadable row {name!r} / {count_text!r}")
            rows.append(_YearRow(int(year_text), disease_key(name), name, count, note))
    return _ReportablePage(tuple(rows), current_as_of, modified, page_title(soup))


_REPORTABLE_NOTES = {
    "en": [
        (
            "Counts are confirmed farmed herds or flocks (premises), running totals to the end of "
            "the month before the update; the table is updated on the 10th of each month."
        ),
        (
            "Each year lists only the diseases with at least one confirmed case; rabies is compiled "
            "separately (CKAN organization cfia-acia), as are aquatic animal diseases."
        ),
        (
            "Yearly counts for 2010 and earlier are in the CKAN dataset 'Federally Reportable "
            "Diseases for Terrestrial Animals in Canada' (cfia-acia)."
        ),
        (
            "Avian influenza from 2021 counts flocks; cfia_avian_influenza lists each infected "
            "premises, and its yearly counts can differ by one or two."
        ),
    ],
    "fr": [
        (
            "Les chiffres sont les troupeaux ou bandes d'élevage (lieux) confirmés, cumulés jusqu'à "
            "la fin du mois précédant la mise à jour; le tableau est actualisé le 10 de chaque mois."
        ),
        (
            "Chaque année ne présente que les maladies ayant au moins un cas confirmé; la rage est "
            "compilée à part (organisation CKAN cfia-acia), comme les maladies des animaux "
            "aquatiques."
        ),
        (
            "Les chiffres annuels de 2010 et avant sont dans le jeu de données CKAN « Maladies "
            "déclarables au niveau fédéral chez les animaux terrestres au Canada » (cfia-acia)."
        ),
        (
            "Pour l'influenza aviaire depuis 2021, le tableau compte les troupeaux; "
            "cfia_avian_influenza donne chaque lieu infecté, et ses totaux annuels peuvent "
            "différer d'une ou deux unités."
        ),
    ],
}


def _detections_tool(key: str, year: int) -> str | None:
    """Which tool lists the detections behind a yearly count, if any.

    Avian influenza has both: flocks before 2021 are on its detection
    page, premises from December 2021 on the investigations page.
    """
    if key == "avian_influenza" and year >= 2021:
        return "cfia_avian_influenza"
    return "cfia_disease_detections" if key in constants.DETECTION_PAGES else None


def _check_years(
    year_from: int | None, year_to: int | None, lang: str
) -> tuple[int | None, int | None]:
    if year_from is not None and year_to is not None and year_from > year_to:
        _invalid(lang, "year_from must not be after year_to.")
    return year_from, year_to


async def get_reportable_diseases(
    year_from: int | None = None,
    year_to: int | None = None,
    disease: str | None = None,
    totals_by: str | None = None,
    lang: str = "en",
) -> ReportableDiseaseResult:
    lang = _lang(lang)
    year_from, year_to = _check_years(year_from, year_to, lang)
    if totals_by not in (None, "year", "disease"):
        _invalid(lang, "totals_by must be 'year', 'disease' or omitted.")
    url = constants.REPORTABLE_PAGE[lang]
    page, cached = await _parsed(
        "reportable", url, constants.REPORTABLE_TTL_SECONDS, parse_reportable_page
    )
    years = sorted({row.year for row in page.rows})
    first, last = years[0], years[-1]
    low = first if year_from is None else year_from
    high = last if year_to is None else year_to
    if high < first or low > last:
        _invalid(
            lang,
            f"the page covers {first}-{last}; for 2010 and earlier use the CKAN dataset "
            "'Federally Reportable Diseases for Terrestrial Animals in Canada' (cfia-acia).",
        )

    rows = [row for row in page.rows if low <= row.year <= high]
    keys: set[str] = set()
    if disease:
        keys = match_diseases(disease)
        folded = _fold(disease)
        rows = [
            row
            for row in rows
            if row.key in keys or (len(folded) >= 3 and folded in _fold(row.name))
        ]
        if not keys and not rows:
            _invalid(lang, f"unknown disease {disease!r}; known: {_known_diseases(lang)}.")

    out = [
        DiseaseYearCount(
            year=row.year,
            disease_key=row.key,
            disease=row.name,
            count=row.count,
            note=row.note,
            detections_tool=_detections_tool(row.key, row.year),
        )
        for row in sorted(rows, key=lambda r: (-r.year, _fold(r.name)))
    ]

    totals = None
    if totals_by:
        groups: dict[str, CountTotal] = {}
        for item in out:
            key = str(item.year) if totals_by == "year" else item.disease_key
            label = key if totals_by == "year" else disease_label(key, lang, item.disease)
            total = groups.setdefault(key, CountTotal(key=key, label=label, total=0, rows=0))
            total.total += item.count
            total.rows += 1
        totals = sorted(
            groups.values(),
            key=lambda t: (-int(t.key), "") if totals_by == "year" else (-t.total, t.key),
        )

    shown = sorted(keys | {item.disease_key for item in out})
    return ReportableDiseaseResult(
        year_from=low,
        year_to=high,
        diseases=shown,
        rows=out,
        row_count=len(out),
        totals=totals,
        current_as_of=page.current_as_of,
        years_available=years,
        source_page=url,
        notes=list(_REPORTABLE_NOTES[lang]),
        provenance=make_provenance(
            source=_SOURCE,
            url=url,
            cached=cached,
            schema_name="cfia.ReportableDiseaseResult",
            as_of=_as_datetime(page.modified),
            freshness="monthly, on the 10th (next business day if a weekend or holiday); "
            "cached 6 hours",
            coverage=f"{low}-{high} of {first}-{last}; terrestrial animals, rabies excluded",
        ),
    )


# ---------------------------------------------------------------------------
# Per-disease detection pages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DetectionRow:
    year: int
    date_text: str
    location: str
    animal_type: str
    herds: int
    age: str | None
    note: str | None


@dataclass(frozen=True)
class _DetectionPage:
    rows: tuple[_DetectionRow, ...]
    modified: date | None
    title: str | None = None


_HERDS = re.compile(
    r"\s*\((\d+)\s+(?:herds?|flocks?|troupeaux|troupeau|bandes?|premises|lieux)\)\s*",
    re.IGNORECASE,
)


def parse_detection_page(page: str, url: str) -> _DetectionPage:
    soup = BeautifulSoup(page, "html.parser")
    main = _main(soup, url)
    notes = _table_notes(main)
    table = None
    years, dates, locations = DETECTION_COLUMNS
    for candidate in main.find_all("table"):
        header = _header_cells(candidate)
        if (
            len(header) >= 4
            and header[0] in years
            and header[1].startswith(dates)
            and header[2] in locations
        ):
            table = candidate
            break
    if table is None:
        _changed(url, "no Year / Date confirmed / Location / Animal type table")
    has_age = len(_header_cells(table)) >= 5
    rows: list[_DetectionRow] = []
    for tr in _body_rows(table):
        cells = tr.find_all(["td", "th"], recursive=False)
        texts = [_clean(c.get_text(" ")) for c in cells]
        if not any(texts):
            continue
        if len(cells) < 4 or not YEAR_HEADING.fullmatch(texts[0]):
            _changed(url, f"unreadable row {texts}")
        date_text, date_note = _strip_notes(cells[1], notes)
        animal, animal_note = _strip_notes(cells[3], notes)
        location, location_note = _strip_notes(cells[2], notes)
        herds = 1
        match = _HERDS.search(animal)
        if match:
            herds = int(match.group(1))
            animal = _clean(_HERDS.sub(" ", animal))
        note = "; ".join(n for n in (date_note, location_note, animal_note) if n) or None
        rows.append(
            _DetectionRow(
                year=int(texts[0]),
                date_text=date_text,
                location=location,
                animal_type=animal,
                herds=herds,
                age=texts[4] if has_age and len(texts) > 4 and texts[4] else None,
                note=note,
            )
        )
    if not rows:
        _changed(url, "the detection table is empty")
    return _DetectionPage(tuple(rows), date_modified(soup), page_title(soup))


@dataclass
class _Detection:
    key: str
    year: int
    confirmed: date | None
    provinces: list[str]
    herds: int
    # Labels in the chosen language; animal types in both, for filtering.
    date_text: str
    location: str
    animal_type: str
    animal_types: tuple[str, ...]
    age: str | None
    note: str | None


async def _detections_for(
    key: str, lang: str, both: bool
) -> tuple[list[_Detection], bool, date | None, str]:
    """One disease's detections: data from the English page, labels in `lang`.

    `both` also reads the French page in English mode, so an animal type
    filter matches "wapiti" as well as "elk". Returns rows, whether every
    page came from cache, the English page's date modified, and a note
    when French labels could not be paired.
    """
    urls = constants.DETECTION_PAGES[key]
    english, cached = await _parsed(
        "detections", urls["en"], constants.DETECTION_TTL_SECONDS, parse_detection_page
    )
    labels: tuple[_DetectionRow, ...] = english.rows
    french_rows: tuple[_DetectionRow, ...] | None = None
    note = ""
    if lang == "fr" or both:
        try:
            french, french_cached = await _parsed(
                "detections", urls["fr"], constants.DETECTION_TTL_SECONDS, parse_detection_page
            )
            cached &= french_cached
            if [r.year for r in french.rows] == [r.year for r in english.rows]:
                french_rows = french.rows
            else:
                note = (
                    f"{disease_label(key, 'fr')} : la page française n'a pas les mêmes lignes "
                    "que la page anglaise; les libellés sont en anglais."
                )
        except (UpstreamError, UpstreamUnavailable, NotFound):
            note = f"{disease_label(key, 'fr')} : page française indisponible; libellés en anglais."
    if lang == "fr" and french_rows is not None:
        labels = french_rows
    if lang == "en":
        note = ""
    others = french_rows or (None,) * len(english.rows)
    rows = [
        _Detection(
            key=key,
            year=row.year,
            confirmed=parse_day_month(row.date_text, row.year),
            provinces=province_codes_in(row.location),
            herds=row.herds,
            date_text=label.date_text,
            location=label.location,
            animal_type=label.animal_type,
            animal_types=(row.animal_type, *((other.animal_type,) if other else ())),
            age=label.age,
            note=label.note,
        )
        for row, label, other in zip(english.rows, labels, others, strict=True)
    ]
    return rows, cached, english.modified, note


_DETECTION_NOTES = {
    "en": [
        (
            "One row per confirmation, from each disease's 'data by month' page; herds counts the "
            "herds or flocks a row stands for ('Elk (3 herds)'), which add up to the yearly totals "
            "in cfia_reportable_diseases."
        ),
        (
            "Dates, years and provinces come from the English pages, which the French ones "
            "sometimes contradict."
        ),
        (
            "Not covered here: equine infectious anemia (its page stops at 2019; yearly counts are "
            "in cfia_reportable_diseases), Newcastle disease (a control zone map), avian influenza "
            "from December 2021 (cfia_avian_influenza), rabies and aquatic diseases (CKAN "
            "organization cfia-acia)."
        ),
    ],
    "fr": [
        (
            "Une ligne par confirmation, tirée de la page « données par mois » de chaque maladie; "
            "herds compte les troupeaux ou bandes d'une ligne (« Wapiti (3 troupeaux) »), dont la "
            "somme donne les totaux annuels de cfia_reportable_diseases."
        ),
        (
            "Les dates, années et provinces viennent des pages anglaises, que les pages françaises "
            "contredisent parfois."
        ),
        (
            "Non couverts ici : l'anémie infectieuse des équidés (sa page s'arrête en 2019; totaux "
            "annuels dans cfia_reportable_diseases), la maladie de Newcastle (carte des zones de "
            "contrôle), l'influenza aviaire depuis décembre 2021 (cfia_avian_influenza), la rage "
            "et les maladies des animaux aquatiques (organisation CKAN cfia-acia)."
        ),
    ],
}


async def get_disease_detections(
    disease: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    province: str | None = None,
    animal_type: str | None = None,
    counts_by: str | None = None,
    lang: str = "en",
) -> DiseaseDetectionResult:
    lang = _lang(lang)
    year_from, year_to = _check_years(year_from, year_to, lang)
    if counts_by not in (None, "year", "month", "province", "animal_type"):
        _invalid(lang, "counts_by must be 'year', 'month', 'province', 'animal_type'.")
    keys = list(constants.DETECTION_PAGES)
    if disease:
        matched = match_diseases(disease)
        keys = [key for key in keys if key in matched]
        if not keys:
            supported = ", ".join(
                f"{key} ({disease_label(key, lang)})" for key in constants.DETECTION_PAGES
            )
            if "equine_infectious_anemia" in matched or "newcastle_disease" in matched:
                _invalid(
                    lang,
                    f"{disease!r} has no detection table in the CFIA's usual layout; use "
                    "cfia_reportable_diseases for yearly counts. Supported: " + supported + ".",
                )
            _invalid(lang, f"unknown disease {disease!r}; supported: {supported}.")
    code = None
    if province:
        code = province_code(province)
        if code is None:
            _invalid(lang, f"unknown province {province!r}; use a code such as 'SK'.")
    animal = _fold(animal_type) if animal_type else None

    rows: list[_Detection] = []
    all_cached = True
    modified: dict[str, date] = {}
    notes = list(_DETECTION_NOTES[lang])
    for key in keys:
        found, cached, page_modified, note = await _detections_for(key, lang, bool(animal))
        rows.extend(found)
        all_cached &= cached
        if page_modified:
            modified[key] = page_modified
        if note:
            notes.append(note)

    def keep(row: _Detection) -> bool:
        if year_from is not None and row.year < year_from:
            return False
        if year_to is not None and row.year > year_to:
            return False
        if code and code not in row.provinces:
            return False
        return not animal or any(animal in _fold(text) for text in row.animal_types)

    rows = [row for row in rows if keep(row)]
    rows.sort(key=lambda r: (r.confirmed or date(r.year, 1, 1), r.key), reverse=True)

    counts = None
    if counts_by:
        groups: dict[str, DetectionCount] = {}
        for row in rows:
            for key, label in _detection_groups(row, counts_by, lang):
                group = groups.setdefault(
                    key, DetectionCount(key=key, label=label, detections=0, herds=0)
                )
                group.detections += 1
                group.herds += row.herds
        if counts_by in ("year", "month"):
            counts = sorted(groups.values(), key=lambda g: g.key, reverse=True)
        else:
            counts = sorted(groups.values(), key=lambda g: (-g.herds, g.key))
        if counts_by == "month" and any(row.confirmed is None for row in rows):
            notes.append(
                "Rows whose day and month cannot be read are grouped under their year alone."
                if lang == "en"
                else "Les lignes dont le jour et le mois sont illisibles sont groupées sous "
                "leur année seule."
            )

    pages = [constants.DETECTION_PAGES[key][lang] for key in keys]
    return DiseaseDetectionResult(
        diseases=keys,
        year_from=year_from,
        year_to=year_to,
        rows=[
            DiseaseDetection(
                disease_key=row.key,
                disease=disease_label(row.key, lang),
                year=row.year,
                date_confirmed=row.confirmed,
                date_text=row.date_text,
                location=row.location,
                province_codes=row.provinces,
                animal_type=row.animal_type,
                herds=row.herds,
                age=row.age,
                note=row.note,
            )
            for row in rows
        ],
        row_count=len(rows),
        herd_count=sum(row.herds for row in rows),
        counts=counts,
        source_pages=pages,
        last_modified=modified,
        notes=notes,
        provenance=make_provenance(
            source=_SOURCE,
            url=pages[0] if len(pages) == 1 else constants.REPORTABLE_PAGE[lang],
            cached=all_cached,
            schema_name="cfia.DiseaseDetectionResult",
            as_of=_as_datetime(max(modified.values()) if modified else None),
            freshness="when a detection is confirmed (CWD monthly); cached 12 hours",
            coverage=f"{len(keys)} disease page(s): {', '.join(keys)}",
        ),
    )


def _detection_groups(row: _Detection, counts_by: str, lang: str) -> list[tuple[str, str]]:
    if counts_by == "year":
        return [(str(row.year), str(row.year))]
    if counts_by == "month":
        key = f"{row.confirmed:%Y-%m}" if row.confirmed else str(row.year)
        return [(key, key)]
    if counts_by == "province":
        codes = row.provinces or ["?"]
        return [(c, province_label(c, lang) if c != "?" else row.location) for c in codes]
    return [(_fold(row.animal_type), row.animal_type)]


# ---------------------------------------------------------------------------
# Highly pathogenic avian influenza: infected premises and status by province
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PremisesRow:
    province_code: str
    number: int
    premises_id: str
    location: str | None
    detected: date | None
    sort_key_valid: bool
    status: PremisesStatus | None
    premises_type: str | None
    premises_type_label: str | None
    woah: Woah | None
    woah_label: str | None
    low_pathogenic: bool
    control_zone: str | None
    order: Order | None
    order_text: str | None


@dataclass(frozen=True)
class _PremisesPage:
    rows: tuple[_PremisesRow, ...]
    skipped: int
    modified: date | None
    title: str | None = None


_PREMISES_ID = re.compile(r"^\s*([A-Z]{2})\s*-\s*IP\s*(\d+)\s*", re.IGNORECASE)


def _not_applicable(text: str) -> bool:
    return _fold(text) in _NOT_APPLICABLE


def normalize_premises_type(text: str) -> tuple[str | None, str | None]:
    """('commercial'|'non_commercial'|'captive_wild'|other, label as published, tidied)."""
    label = re.sub(r"\s*-\s*", "-", _clean(text)).lower()
    if not label or _not_applicable(label):
        return None, None
    compact = re.sub(r"[^a-z]", "", _fold(label))
    for key, spellings in PREMISES_TYPES.items():
        if compact in spellings:
            return key, label
    return re.sub(r"[^a-z0-9]+", "_", _fold(label)).strip("_"), label


def normalize_woah(text: str) -> tuple[Woah | None, str | None, bool]:
    """(poultry|non_poultry|None, label, low pathogenic?) from the WOAH column."""
    label = _clean(text)
    folded = _fold(label)
    low = any(marker in folded for marker in LOW_PATHOGENIC)
    compact = re.sub(r"[^a-z]", "", folded)
    for key, spellings in WOAH_CLASSES.items():
        if compact in spellings:
            return cast(Woah, key), label, low
    return None, label or None, low


def normalize_order(text: str) -> Order | None:
    first = _fold(text.split(";")[0])
    for key, prefixes in ORDER_PREFIXES.items():
        if first.startswith(prefixes):
            return cast(Order, key)
    return None


def parse_premises_page(page: str, url: str) -> _PremisesPage:
    soup = BeautifulSoup(page, "html.parser")
    main = _main(soup, url)
    table = main.find("table", id=PREMISES_TABLE_ID)
    if not isinstance(table, Tag):
        table = next(
            (
                t
                for t in main.find_all("table")
                if (_header_cells(t) or [""])[0].startswith(PREMISES_COLUMNS[0])
            ),
            None,
        )
    if not isinstance(table, Tag):
        _changed(url, "no infected premises table")
    header = _header_cells(table)
    dates, province, types = PREMISES_COLUMNS
    if (
        len(header) != 7
        or not header[0].startswith(dates)
        or header[2] != province
        or not header[3].startswith(types)
    ):
        _changed(url, f"unexpected columns {header}")

    rows: list[_PremisesRow] = []
    skipped = 0
    for tr in _body_rows(table):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 7:
            skipped += 1
            continue
        date_cell, id_cell = cells[0], cells[1]
        sort_key = str(date_cell.get("data-order", ""))
        detected = None
        sort_key_valid = False
        if re.fullmatch(r"\d{8}", sort_key):
            try:
                detected = date(int(sort_key[:4]), int(sort_key[4:6]), int(sort_key[6:]))
                sort_key_valid = True
            except ValueError:
                detected = None
        if detected is None:
            detected = parse_long_date(_clean(date_cell.get_text(" ")))

        # Status markers first, then the hidden padding digit, then any
        # remaining <sup> wrapper (which on AB-IP104 in French holds the
        # location itself).
        current = any(
            QUARANTINE_MARKER in _fold(span.get_text())
            for span in id_cell.find_all(class_="invisible")
        )
        released = bool(id_cell.find("a", class_="fn-lnk"))
        for node in id_cell.select(".invisible, a.fn-lnk"):
            node.decompose()
        for node in id_cell.select(".wb-inv"):
            node.decompose()
        for sup in id_cell.find_all("sup"):
            sup.unwrap()
        text = _clean(id_cell.get_text(" "))
        match = _PREMISES_ID.match(text)
        if not match:
            skipped += 1
            continue
        prefix, number = match.group(1).upper(), int(match.group(2))
        digits = match.group(2)
        location = _clean(text[match.end() :]) or None
        province_text = _clean(cells[2].get_text(" "))
        code = prefix if prefix in constants.PROVINCES else (province_code(province_text) or prefix)

        premises_type, premises_label = normalize_premises_type(cells[3].get_text(" "))
        woah, woah_label, low = normalize_woah(cells[4].get_text(" "))
        zone_text = _clean(cells[5].get_text(" "))
        order_lines = [_clean(line) for line in cells[6].get_text("\n").split("\n") if _clean(line)]
        order_text = "; ".join(order_lines)
        rows.append(
            _PremisesRow(
                province_code=code,
                number=number,
                premises_id=f"{prefix}-IP{digits}",
                location=location,
                detected=detected,
                sort_key_valid=sort_key_valid,
                status="current" if current else ("released" if released else None),
                premises_type=premises_type,
                premises_type_label=premises_label,
                woah=woah,
                woah_label=woah_label,
                low_pathogenic=low,
                control_zone=None if _not_applicable(zone_text) else zone_text,
                order=normalize_order(order_text),
                order_text=None if _not_applicable(order_text) else order_text,
            )
        )
    if not rows:
        _changed(url, "the infected premises table is empty")
    # A few odd rows are skipped with a note; many mean the layout moved.
    if skipped > max(5, len(rows) // 20):
        _changed(url, f"{skipped} rows could not be read")
    return _PremisesPage(tuple(rows), skipped, date_modified(soup), page_title(soup))


@dataclass(frozen=True)
class _StatusPage:
    rows: tuple[ProvinceStatus, ...]
    total_current: int | None
    total_released: int | None
    total_birds: int | None
    birds_as_of: date | None
    modified: date | None
    title: str | None = None


def parse_status_page(page: str, url: str) -> _StatusPage:
    soup = BeautifulSoup(page, "html.parser")
    main = _main(soup, url)
    table = next(
        (t for t in main.find_all("table") if (_header_cells(t) or [""])[0] == STATUS_FIRST_COLUMN),
        None,
    )
    if not isinstance(table, Tag):
        _changed(url, "no status-by-province table")
    header = _header_cells(table)
    if len(header) != 4:
        _changed(url, f"unexpected columns {header}")
    as_of_match = _ISO_DATE.search(header[3])
    birds_as_of = date.fromisoformat(as_of_match.group(0)) if as_of_match else None
    rows: list[ProvinceStatus] = []
    totals: tuple[int | None, int | None, int | None] = (None, None, None)
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) != 4 or not tr.find("td"):
            continue
        texts = [_clean(c.get_text(" ")) for c in cells]
        values = (parse_int(texts[1]), parse_int(texts[2]), parse_int(texts[3]))
        if _fold(texts[0]) == "total":
            totals = values
            continue
        code = province_code(texts[0])
        if code is None:
            _changed(url, f"unknown province {texts[0]!r}")
        rows.append(
            ProvinceStatus(
                province_code=code,
                province=texts[0],
                current_premises=values[0],
                released_premises=values[1],
                birds_impacted=values[2],
                birds_impacted_text=texts[3],
            )
        )
    if not rows:
        _changed(url, "the status table is empty")
    return _StatusPage(tuple(rows), *totals, birds_as_of, date_modified(soup), page_title(soup))


_PREMISES_TYPE_LABELS = {
    "commercial": ("commercial", "commerciale"),
    "non_commercial": ("non-commercial", "non-commerciale"),
    "captive_wild": ("captive wild", "captive wild"),
}
_WOAH_LABELS = {
    "poultry": ("poultry", "volailles"),
    "non_poultry": ("non-poultry", "non-volailles"),
}


@dataclass
class _Premises:
    row: _PremisesRow
    location: str | None
    control_zone: str | None
    order_text: str | None
    premises_type_label: str | None = None
    woah_label: str | None = None


async def _premises(lang: str) -> tuple[list[_Premises], bool, date | None, list[str]]:
    english, cached = await _parsed(
        "premises",
        constants.HPAI_PREMISES_PAGE["en"],
        constants.HPAI_TTL_SECONDS,
        parse_premises_page,
    )
    notes: list[str] = []
    if english.skipped:
        notes.append(
            f"{english.skipped} row(s) of the premises table could not be read and are left out."
            if lang == "en"
            else f"{english.skipped} ligne(s) du tableau des lieux illisibles sont omises."
        )
    french: dict[tuple[str, int], _PremisesRow] = {}
    if lang == "fr":
        try:
            page, french_cached = await _parsed(
                "premises",
                constants.HPAI_PREMISES_PAGE["fr"],
                constants.HPAI_TTL_SECONDS,
                parse_premises_page,
            )
            cached &= french_cached
            french = {(r.province_code, r.number): r for r in page.rows}
        except (UpstreamError, UpstreamUnavailable, NotFound):
            notes.append("Page française indisponible; les libellés sont en anglais.")

    out: list[_Premises] = []
    unmatched = differing = 0
    for row in english.rows:
        fr_row = french.get((row.province_code, row.number))
        type_label = row.premises_type_label
        woah_label = row.woah_label
        if row.premises_type in _PREMISES_TYPE_LABELS:
            type_label = _PREMISES_TYPE_LABELS[row.premises_type][lang == "fr"]
        if row.woah in _WOAH_LABELS:
            woah_label = _WOAH_LABELS[row.woah][lang == "fr"]
        if lang == "fr" and fr_row is None and french:
            unmatched += 1
        if fr_row is not None:
            if fr_row.detected != row.detected or not fr_row.sort_key_valid:
                differing += 1
            if row.premises_type not in _PREMISES_TYPE_LABELS:
                type_label = fr_row.premises_type_label
            if row.woah not in _WOAH_LABELS:
                woah_label = fr_row.woah_label
            out.append(
                _Premises(
                    row,
                    fr_row.location,
                    fr_row.control_zone,
                    fr_row.order_text,
                    type_label,
                    woah_label,
                )
            )
        else:
            out.append(
                _Premises(
                    row, row.location, row.control_zone, row.order_text, type_label, woah_label
                )
            )
    if lang == "fr" and french:
        if unmatched:
            notes.append(
                f"{unmatched} lieu(x) absent(s) de la page française : libellés en anglais."
            )
        if differing:
            notes.append(
                f"La page française donne une date différente ou mal formée pour {differing} "
                "lieu(x); les dates suivent la page anglaise."
            )
    return out, cached, english.modified, notes


_PREMISES_NOTES = {
    "en": [
        (
            "One row per infected premises since December 2021, with the page's own status: "
            "'current' is under CFIA quarantine, 'released' has been released from quarantine and "
            "restrictions."
        ),
        (
            "Premises types: since November 9, 2023, sites with fewer than 1,000 birds (and fewer "
            "than 300 ducks or geese) are non-commercial. WOAH classification separates poultry "
            "(birds kept to produce commercial products) from non-poultry; four 2024 premises were "
            "low pathogenic avian influenza (LPAI)."
        ),
        (
            "Dates come from the English page. The province summary is the CFIA's own table and is "
            "updated separately, so it can lag the premises list by a few days."
        ),
    ],
    "fr": [
        (
            "Une ligne par lieu infecté depuis décembre 2021, avec le statut de la page : "
            "« current » est sous quarantaine de l'ACIA, « released » a été libéré de la "
            "quarantaine et des restrictions."
        ),
        (
            "Types de lieu : depuis le 9 novembre 2023, les sites de moins de 1 000 oiseaux (et de "
            "moins de 300 canards ou oies) sont non commerciaux. La classification de l'OMSA "
            "distingue les volailles (oiseaux élevés pour des produits commerciaux) des "
            "non-volailles; quatre lieux de 2024 étaient touchés par l'influenza aviaire "
            "faiblement pathogène (IAFP)."
        ),
        (
            "Les dates viennent de la page anglaise. Le résumé par province est le tableau de "
            "l'ACIA, mis à jour séparément, et peut accuser quelques jours de retard sur la liste."
        ),
    ],
}


async def get_avian_influenza(
    status: str = "all",
    province: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    premises_type: str | None = None,
    counts_by: str = "province",
    limit: int = constants.HPAI_DEFAULT_LIMIT,
    lang: str = "en",
) -> AvianInfluenzaResult:
    lang = _lang(lang)
    if status not in ("current", "released", "all"):
        _invalid(lang, "status must be 'current', 'released' or 'all'.")
    if counts_by not in ("province", "month", "year", "premises_type"):
        _invalid(lang, "counts_by must be 'province', 'month', 'year' or 'premises_type'.")
    if not 1 <= limit <= constants.HPAI_MAX_LIMIT:
        _invalid(lang, f"limit must be between 1 and {constants.HPAI_MAX_LIMIT}.")
    code = None
    if province:
        code = province_code(province)
        if code is None:
            _invalid(lang, f"unknown province {province!r}; use a code such as 'BC'.")
    wanted_type = None
    if premises_type:
        wanted_type, _ = normalize_premises_type(premises_type)
        if wanted_type not in _PREMISES_TYPE_LABELS:
            _invalid(
                lang, "premises_type must be 'commercial', 'non_commercial' or 'captive_wild'."
            )
    start = parse_period(date_from, end=False, lang=lang) if date_from else None
    end = parse_period(date_to, end=True, lang=lang) if date_to else None
    if start and end and start > end:
        _invalid(lang, "date_from must not be after date_to.")

    premises, cached, modified, notes = await _premises(lang)
    notes = list(_PREMISES_NOTES[lang]) + notes

    def keep(item: _Premises) -> bool:
        row = item.row
        if status != "all" and row.status != status:
            return False
        if code and row.province_code != code:
            return False
        if wanted_type and row.premises_type != wanted_type:
            return False
        if start and (row.detected is None or row.detected < start):
            return False
        return not (end and (row.detected is None or row.detected > end))

    matched = [item for item in premises if keep(item)]
    matched.sort(key=lambda i: (i.row.detected or date.min, i.row.number), reverse=True)

    groups: dict[str, PremisesCount] = {}
    for item in matched:
        key, label = _premises_group(item, counts_by, lang)
        group = groups.setdefault(
            key, PremisesCount(key=key, label=label, current=0, released=0, total=0)
        )
        group.total += 1
        if item.row.status == "current":
            group.current += 1
        elif item.row.status == "released":
            group.released += 1
    if counts_by in ("month", "year"):
        counts = sorted(groups.values(), key=lambda g: g.key, reverse=True)
    else:
        counts = sorted(groups.values(), key=lambda g: (-g.total, g.key))

    unmarked = sum(1 for item in premises if item.row.status is None)
    if unmarked:
        notes.append(
            f"{unmarked} premises carry neither the quarantine nor the released marker; their "
            "status is None."
            if lang == "en"
            else f"{unmarked} lieu(x) sans marque de quarantaine ni de libération : statut None."
        )

    summary = await _province_summary(lang, notes)
    if summary is not None and status == "all" and not (code or wanted_type or start or end):
        _compare_summary(premises, summary, lang, notes)

    url = constants.HPAI_PREMISES_PAGE[lang]
    shown = matched[:limit]
    return AvianInfluenzaResult(
        status=cast(StatusFilter, status),
        total_matched=len(matched),
        returned_count=len(shown),
        premises=[_premises_model(item, lang) for item in shown],
        counts_by=counts_by,
        counts=counts,
        province_summary=summary,
        source_page=url,
        notes=notes,
        provenance=make_provenance(
            source=_SOURCE,
            url=url,
            cached=cached,
            schema_name="cfia.AvianInfluenzaResult",
            as_of=_as_datetime(modified),
            freshness="as detections are confirmed or premises released; cached 1 hour",
            coverage=f"{len(matched)} of {len(premises)} infected premises since December 2021",
            limits=(
                f"Returned the most recent {len(shown)} of {len(matched)} matching premises "
                f"(counts cover all of them); raise limit (max {constants.HPAI_MAX_LIMIT}) or "
                "narrow by province, dates or status"
                if len(matched) > limit
                else None
            ),
        ),
    )


def _premises_group(item: _Premises, counts_by: str, lang: str) -> tuple[str, str]:
    row = item.row
    if counts_by == "province":
        return row.province_code, province_label(row.province_code, lang)
    if counts_by == "month":
        key = f"{row.detected:%Y-%m}" if row.detected else "unknown"
        return key, key
    if counts_by == "year":
        key = str(row.detected.year) if row.detected else "unknown"
        return key, key
    key = row.premises_type or "unknown"
    return key, item.premises_type_label or key


def _premises_model(item: _Premises, lang: str) -> InfectedPremises:
    row = item.row
    return InfectedPremises(
        premises_id=row.premises_id,
        province_code=row.province_code,
        province=province_label(row.province_code, lang),
        location=item.location,
        date_detected=row.detected,
        status=row.status,
        premises_type=row.premises_type,
        premises_type_label=item.premises_type_label,
        woah_classification=row.woah,
        woah_classification_label=item.woah_label,
        low_pathogenic=row.low_pathogenic,
        control_zone=item.control_zone,
        control_zone_order=row.order,
        control_zone_order_text=item.order_text,
    )


async def _province_summary(lang: str, notes: list[str]) -> ProvinceStatusSummary | None:
    url = constants.HPAI_STATUS_PAGE[lang]
    try:
        page, _ = await _parsed("status", url, constants.HPAI_TTL_SECONDS, parse_status_page)
    except (UpstreamError, UpstreamUnavailable, NotFound) as exc:
        notes.append(
            f"The status-by-province table could not be read: {exc}"
            if lang == "en"
            else f"Le tableau d'état par province est illisible : {exc}"
        )
        return None
    return ProvinceStatusSummary(
        rows=list(page.rows),
        total_current=page.total_current,
        total_released=page.total_released,
        total_birds_impacted=page.total_birds,
        birds_as_of=page.birds_as_of,
        last_modified=page.modified,
        source_page=url,
    )


def _compare_summary(
    premises: list[_Premises], summary: ProvinceStatusSummary, lang: str, notes: list[str]
) -> None:
    """Note provinces where the premises list and the summary table disagree."""
    listed: dict[str, list[int]] = {}
    for item in premises:
        counts = listed.setdefault(item.row.province_code, [0, 0])
        if item.row.status == "current":
            counts[0] += 1
        elif item.row.status == "released":
            counts[1] += 1
    differences = []
    for row in summary.rows:
        current, released = listed.get(row.province_code, [0, 0])
        if (row.current_premises, row.released_premises) != (current, released):
            differences.append(
                f"{row.province_code} {current}/{released} vs "
                f"{row.current_premises}/{row.released_premises}"
            )
    if differences:
        notes.append(
            "Premises list and province summary differ (current/released, list vs summary): "
            + "; ".join(differences)
            + "."
            if lang == "en"
            else "La liste des lieux et le résumé par province diffèrent (actuels/libérés, "
            "liste vs résumé) : " + "; ".join(differences) + "."
        )

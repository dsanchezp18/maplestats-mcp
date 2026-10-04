"""Client for NRCan's annual mineral production CSV files.

Checked live 2026-10-03 for 1990, 1995, 2000, 2010, 2018 to 2025:

1. Every year has /PDF/MIS{year}TableG01-en.csv (UTF-8 with a BOM). There
   is no French file (the -fr name redirects to an error page) and no
   French page. The annual page's year selector lists 2025 back to 1990,
   the newest shown as "2025p" (preliminary).
2. Two layouts. 2019 onward: a title row, a blank row, then
   Year,Type,Commodity,Province or Territory,Category,Value,Units,Symbol
   with values like "2,309", ".." (not available) or "x" (confidential)
   and Symbol "p" for preliminary; categories are Quantity produced,
   Quantity shipped and Value of shipments. 1990 to 2018:
   Year,Commodity,Commodity Group,Province/Territory,Value Type,Units,Value
   with no symbol column, values like "4.99" or "27058554.021", "x" or
   empty, and Quantity shipped / Value of shipments only.
3. Both end with notes, links and contact lines in the first column.
4. Commodity names carry footnote markers: "Ilmenite(3)", "Lime¹(10)",
   "Potash (K₂O)(3)", "Coal(5)"; they are stripped, but chemical formulas
   in parentheses are kept.
5. The 1990-2018 files hold a "Historical data" group whose rows are
   "Grand total, 1988" ... "Grand total, 2018" (1960-1990 in the 1990
   file) under the file's own Year; each becomes a "Grand total" row of
   the year it names.
6. Units changed: kilotonnes and tonnes before 2019, metric tonnes
   after; "Iron ore" became "Iron, concentrates" and "Iron,
   agglomerates". Each row keeps its own units.
7. Every province has a row, and "Canada" is the total.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, NoReturn

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.nrcan_minerals import constants
from maplestats_mcp.modules.nrcan_minerals.schemas import (
    MineralProduction,
    MineralRow,
    MineralSeries,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
# "(3)", "¹(10)", "(1),(2)" at the end of a name; "(K₂O)" or "(MOP)" stay.
_FOOTNOTES = re.compile(r"(?:[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\(\d+\)|,)+\s*$")
_GRAND_TOTAL = re.compile(r"^Grand total,\s*(\d{4})$")


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _text(en: str, fr: str, lang: str) -> str:
    return french_spacing(fr) if lang == "fr" else en


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def clean_name(text: str) -> str:
    name = " ".join(text.split())
    while True:
        stripped = _FOOTNOTES.sub("", name).strip()
        if stripped == name:
            return name
        name = stripped


def parse_value(text: str, symbol: str = "") -> tuple[float | None, str]:
    raw = text.strip()
    if raw.lower() == "x":
        return None, "confidential"
    if raw in ("", "..", "...", "-", "F"):
        return None, "not_available"
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None, "not_available"
    return value, "preliminary" if symbol.strip().lower() == "p" else "final"


@dataclass(frozen=True)
class _Year:
    year: int
    title: str
    rows: tuple[MineralRow, ...]


def parse_csv(text: str, year: int, lang: str = "en") -> _Year:
    lines = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    title = clean_name(lines[0][0]) if lines and lines[0] else ""
    header_at = next((i for i, line in enumerate(lines) if line and line[0] == "Year"), None)
    if header_at is None:
        _raise(
            UpstreamError,
            f"nrcan_minerals: the {year} file has no 'Year' header row.",
            f"nrcan_minerals : le fichier {year} n'a pas de ligne d'en-tête 'Year'.",
            lang,
        )
    header = [h.strip() for h in lines[header_at]]

    def column(*names: str) -> int:
        for name in names:
            if name in header:
                return header.index(name)
        _raise(
            UpstreamError,
            f"nrcan_minerals: the {year} file has no {names[0]!r} column.",
            f"nrcan_minerals : le fichier {year} n'a pas de colonne {names[0]!r}.",
            lang,
        )

    at = {
        "group": column("Type", "Commodity Group"),
        "commodity": column("Commodity"),
        "province": column("Province or Territory", "Province/Territory"),
        "category": column("Category", "Value Type"),
        "units": column("Units"),
        "value": column("Value"),
    }
    symbol_at = header.index("Symbol") if "Symbol" in header else None
    rows: list[MineralRow] = []
    for line in lines[header_at + 1 :]:
        if len(line) < len(header) or not line[0].strip()[:4].isdigit():
            continue
        commodity = clean_name(line[at["commodity"]])
        row_year = int(line[0].strip()[:4])
        if match := _GRAND_TOTAL.match(commodity):
            commodity, row_year = "Grand total", int(match.group(1))
        value, symbol = parse_value(
            line[at["value"]], line[symbol_at] if symbol_at is not None else ""
        )
        rows.append(
            MineralRow(
                year=row_year,
                group=clean_name(line[at["group"]]) or None,
                commodity=commodity,
                province=line[at["province"]].strip(),
                category=line[at["category"]].strip(),
                units=line[at["units"]].strip() or None,
                value=value,
                symbol=symbol,  # type: ignore[arg-type]
            )
        )
    if not rows:
        _raise(
            UpstreamError,
            f"nrcan_minerals: the {year} file has no data rows.",
            f"nrcan_minerals : le fichier {year} n'a aucune ligne de données.",
            lang,
        )
    return _Year(year=year, title=title, rows=tuple(rows))


async def _fetch(url: str, lang: str = "en") -> httpx.Response:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (301, 302, 404, 410):
            _raise(
                NotFound,
                f"nrcan_minerals: no file at {url} (HTTP {status}).",
                f"nrcan_minerals : aucun fichier à {url} (HTTP {status}).",
                lang,
            )
        _raise(
            UpstreamError,
            f"nrcan_minerals: {url} returned HTTP {status}.",
            f"nrcan_minerals : {url} a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        _raise(
            UpstreamUnavailable,
            f"nrcan_minerals: {url} did not respond in time.",
            f"nrcan_minerals : {url} n'a pas répondu à temps.",
            lang,
        )
    if len(response.content) > constants.MAX_FILE_BYTES:
        _raise(
            UpstreamError,
            f"nrcan_minerals: {url} is much larger than expected.",
            f"nrcan_minerals : {url} est beaucoup plus volumineux que prévu.",
            lang,
        )
    return response


def parse_years(html: str) -> list[int]:
    select = BeautifulSoup(html, "html.parser").find("select", id="vYear")
    if select is None:
        return []
    years = {
        int(str(option.get("value")))
        for option in select.find_all("option")
        if str(option.get("value") or "").isdigit()
    }
    return sorted(years, reverse=True)


async def _years(lang: str = "en") -> tuple[list[int], bool]:
    async def fetch() -> list[int]:
        years = parse_years((await _fetch(constants.ANNUAL_PAGE, lang)).text)
        if not years:
            _raise(
                UpstreamError,
                "nrcan_minerals: the annual page has no year selector.",
                "nrcan_minerals : la page annuelle n'a pas de sélecteur d'année.",
                lang,
            )
        return years

    return await cached_fetch("nrcan_minerals:years", constants.YEARS_TTL_SECONDS, fetch)


async def _year(year: int, lang: str = "en") -> tuple[_Year, bool]:
    url = constants.CSV_URL.format(year=year)

    async def fetch() -> _Year:
        response = await _fetch(url, lang)
        text = response.content.decode("utf-8-sig", errors="replace")
        if text.lstrip().lower().startswith(("<!doctype", "<html")):
            _raise(
                NotFound,
                f"nrcan_minerals: {url} returned a web page, not a CSV file.",
                f"nrcan_minerals : {url} a renvoyé une page Web, pas un fichier CSV.",
                lang,
            )
        return parse_csv(text, year, lang)

    return await cached_fetch(f"nrcan_minerals:{year}", constants.CSV_TTL_SECONDS, fetch)


def _province(province: str, lang: str = "en") -> str | None:
    wanted = province.strip()
    if not wanted:
        return None
    if wanted.upper() in constants.PROVINCES:
        return constants.PROVINCES[wanted.upper()]
    for name in constants.PROVINCES.values():
        if _fold(name) == _fold(wanted):
            return name
    _raise(
        InvalidInput,
        f"nrcan_minerals: unknown province {province!r}; use a code like ON or a name, "
        "or 'Canada' for the total.",
        f"nrcan_minerals : province inconnue {province!r} ; utilisez un code comme ON ou un "
        "nom anglais, ou 'Canada' pour le total.",
        lang,
    )


def _category_matches(category: str, wanted: str) -> bool:
    folded = _fold(category)
    if wanted == "value":
        return folded.startswith("value")
    if wanted == "quantity":
        return folded.startswith("quantity")
    if wanted == "quantity_shipped":
        return folded == "quantity shipped"
    if wanted == "quantity_produced":
        return folded == "quantity produced"
    return True


def _provenance(url: str, cached: bool, schema: str, lang: str, coverage: str | None) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"nrcan_minerals.{schema}",
        freshness=_text(
            "yearly: a preliminary estimate, then final figures the following year",
            "annuelle : une estimation provisoire, puis les chiffres définitifs l'année suivante",
            lang,
        ),
        coverage=coverage,
        limits=_text(
            "",
            "Les fichiers de RNCan sont publiés en anglais seulement : noms des produits "
            "minéraux, provinces et catégories sont reproduits tels quels.",
            lang,
        )
        or None,
        licence=_text(constants.TERMS, constants.TERMS_FR, lang),
        lang=lang,
    )


async def get_production(
    year: int | None = None,
    *,
    commodity: str = "",
    province: str = "",
    category: str = "all",
    limit: int = constants.ROWS_DEFAULT_LIMIT,
    lang: str = "en",
) -> MineralProduction:
    """One reference year's rows, filtered by commodity, province and category."""
    if not 1 <= limit <= constants.ROWS_MAX_LIMIT:
        _raise(
            InvalidInput,
            f"nrcan_minerals: limit must be 1 to {constants.ROWS_MAX_LIMIT}.",
            f"nrcan_minerals : limit doit être compris entre 1 et {constants.ROWS_MAX_LIMIT}.",
            lang,
        )
    years, _ = await _years(lang)
    chosen = years[0] if year is None else year
    if chosen not in years:
        _raise(
            NotFound,
            f"nrcan_minerals: no file for {chosen}; years are {min(years)}-{max(years)}.",
            f"nrcan_minerals : aucun fichier pour {chosen} ; les années vont de {min(years)} "
            f"à {max(years)}.",
            lang,
        )
    wanted_province = _province(province, lang)
    data, cached = await _year(chosen, lang)
    words = _fold(commodity).split()
    matched = [
        r
        for r in data.rows
        if all(w in _fold(r.commodity) for w in words)
        and (wanted_province is None or r.province == wanted_province)
        and _category_matches(r.category, category)
    ]
    return MineralProduction(
        year=chosen,
        title=data.title,
        preliminary=any(r.symbol == "preliminary" for r in data.rows),
        rows=matched[:limit],
        returned_count=min(limit, len(matched)),
        total_matched=len(matched),
        commodities=sorted({r.commodity for r in data.rows}),
        available_years=years,
        provenance=_provenance(
            constants.CSV_URL.format(year=chosen),
            cached,
            "MineralProduction",
            lang,
            _text(
                f"{len(data.rows):,} rows in the {chosen} file",
                f"{len(data.rows):,} lignes dans le fichier {chosen}".replace(",", "\u00a0"),
                lang,
            ),
        ),
    )


def _pick(rows: list[MineralRow], wanted: str) -> tuple[list[MineralRow], set[str]]:
    """Rows for the commodity: an exact name wins, else one unambiguous partial match."""
    exact = [r for r in rows if _fold(r.commodity) == wanted]
    if exact:
        return exact, set()
    partial = [r for r in rows if wanted in _fold(r.commodity)]
    names = {r.commodity for r in partial}
    return (partial, set()) if len(names) == 1 else ([], names)


async def get_series(
    commodity: str,
    *,
    province: str = "Canada",
    category: str = "value",
    from_year: int | None = None,
    to_year: int | None = None,
    lang: str = "en",
) -> MineralSeries:
    """One commodity across years, read from each year's file."""
    wanted = _fold(clean_name(commodity))
    if not wanted:
        _raise(
            InvalidInput,
            "nrcan_minerals: pass a commodity, e.g. 'gold' or 'Grand total'.",
            "nrcan_minerals : donnez un produit minéral, en anglais, p. ex. 'gold' ou "
            "'Grand total'.",
            lang,
        )
    if category not in ("value", "quantity_shipped", "quantity_produced"):
        _raise(
            InvalidInput,
            "nrcan_minerals: category must be value, quantity_shipped or quantity_produced.",
            "nrcan_minerals : category doit valoir value, quantity_shipped ou quantity_produced.",
            lang,
        )
    wanted_province = _province(province, lang) or "Canada"
    years, _ = await _years(lang)
    first = max(from_year or constants.FIRST_YEAR, min(years))
    last = min(to_year or max(years), max(years))
    span = [y for y in sorted(years) if first <= y <= last]
    if not span:
        _raise(
            InvalidInput,
            f"nrcan_minerals: years are {min(years)}-{max(years)}.",
            f"nrcan_minerals : les années vont de {min(years)} à {max(years)}.",
            lang,
        )
    loaded = await asyncio.gather(*(_year(y, lang) for y in span))
    points: list[MineralRow] = []
    missing: list[int] = []
    ambiguous: set[str] = set()
    for (data, _), y in zip(loaded, span, strict=True):
        rows = [
            r
            for r in data.rows
            if r.year == y
            and r.province == wanted_province
            and _category_matches(r.category, category)
        ]
        picked, names = _pick(rows, wanted)
        ambiguous |= names
        # A name can repeat under several groups ("Total"); keep the first.
        if picked:
            points.append(picked[0])
        else:
            missing.append(y)
    if not points:
        hint = f" Several match: {sorted(ambiguous)}." if ambiguous else ""
        hint_fr = f" Plusieurs correspondent : {sorted(ambiguous)}." if ambiguous else ""
        _raise(
            NotFound,
            f"nrcan_minerals: no {commodity!r} rows for {wanted_province}.{hint}",
            f"nrcan_minerals : aucune ligne {commodity!r} pour {wanted_province}.{hint_fr}",
            lang,
        )
    note = _text(
        "Units and commodity definitions changed over time (kilotonnes before 2019, metric "
        "tonnes after; iron ore split into concentrates and agglomerates in 2019); read each "
        "point's units.",
        "Les unités et les définitions des produits ont changé au fil du temps (kilotonnes "
        "avant 2019, tonnes métriques ensuite ; le minerai de fer a été scindé en concentrés "
        "et agglomérés en 2019) ; lisez les unités de chaque point.",
        lang,
    )
    if ambiguous:
        note += _text(
            f" Years with several matching names were skipped: {sorted(ambiguous)}.",
            f" Les années où plusieurs noms correspondent ont été omises : {sorted(ambiguous)}.",
            lang,
        )
    return MineralSeries(
        commodity=points[0].commodity,
        province=wanted_province,
        category=category,
        points=points,
        missing_years=missing,
        note=note,
        provenance=_provenance(
            constants.ANNUAL_PAGE,
            all(c for _, c in loaded),
            "MineralSeries",
            lang,
            _text(
                f"{span[0]}-{span[-1]}, one file per year",
                f"{span[0]}-{span[-1]}, un fichier par année",
                lang,
            ),
        ),
    )

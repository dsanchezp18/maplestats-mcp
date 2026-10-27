"""Parsers for the CRTC Communications Market Reports workbooks.

Each parser takes a sheet as rows of cell values (what openpyxl's
`iter_rows(values_only=True)` gives), so the tests feed rows written by hand.
Layouts confirmed on the files published 2026-05-14 (prices), 2025-11-25
(retail mobile and fixed Internet sectors) and 2026-08-21 (quarterly
trends):

1. Price sheets ("Moyennes-Averages Mobile" and "... Internet"): one header
   row, then Year, Region, Province or territory, Forfait (French plan
   label), Plan (English), Average ($) and, for mobile, Speed (3G, LTE, 5G or
   "Plus bas prix / Lowest price"). Labels are not consistent: the region is
   "Urbain / Urban" in most years but "Urban" for 2025, and the French plan
   label for talk-only plans is "Forfait voix" or "Plan voix". A price the
   CRTC did not compute is "--".
2. Sector workbooks: a table of contents on the first sheet (label, tab
   name, title), then one sheet per infographic (I), figure (F, "G" for
   graphique in the French file), table (T) and supplementary table (S).
   A sheet starts with its label and title, may hold several blocks (a
   one-cell block title, a header row of years, data rows), and ends with
   "Source: CRTC data collection" and notes. Years are numbers, or text
   like "2020 (MP)" ("(TM)" in French): from 2020 the CRTC counts mobile
   phone services only. "Growth (%)" and "CAGR (%)" columns are derived and
   left out. A second header row under the years (Residential, Business)
   qualifies each column. Values are numbers or text such as "$59.97",
   "30.6%", " 28.4 ", "N/A" or "More than one quarter".
3. The "Prix-Prices" sheet: every reported price, one row per provider,
   brand, place and plan (and network for mobile); see
   parse_reported_prices.
4. Quarterly sheets: one header row of bilingual names, rows in no
   particular order; each row has a quarter ("2026 Q1"), a market and a
   metric in French and English, sometimes a subcategory, and one or two
   filled measure columns (revenues, subscribers, data in GB...).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from maplestats_mcp.shared.executor import check_deadline

_YEAR = re.compile(r"^\s*((?:19|20)\d{2})\s*(\((?:MP|TM)\))?\s*$")
_QUARTER = re.compile(r"^\s*((?:19|20)\d{2})\s*[QT]([1-4])\s*$")
_DERIVED = re.compile(r"growth|cagr|croissance|tcac", re.IGNORECASE)
_SOURCE_LINE = re.compile(r"^\s*source\s*:", re.IGNORECASE)
_NUMBER = re.compile(r"^[\s$]*(-?[\d,]*\.?\d+)\s*(%)?\s*\$?\s*$")
_NOT_AVAILABLE = {"", "--", "-", "..", "...", "n/a", "na", "n.a.", "s.o.", "x"}
_SHEET_ID = re.compile(r"^[A-Z]{1,2}-[A-Z]\d+")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def number(value: Any) -> tuple[float | None, str | None]:
    """(value, cell as published). Text that is not a number gives None."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, str(value)
    if isinstance(value, int | float):
        return float(value), None
    raw = text(value)
    if raw.lower() in _NOT_AVAILABLE:
        return None, raw or None
    match = _NUMBER.match(raw)
    if match is None:
        return None, raw
    return float(match.group(1).replace(",", "")), raw


def _year(value: Any) -> tuple[int, bool] | None:
    """A header cell that names a year: (year, mobile phone only)."""
    if isinstance(value, int) and 1990 <= value <= 2100:
        return value, False
    if isinstance(value, float) and value.is_integer() and 1990 <= value <= 2100:
        return int(value), False
    if isinstance(value, str):
        match = _YEAR.match(value)
        if match:
            return int(match.group(1)), bool(match.group(2))
    return None


def _cells(row: Sequence[Any]) -> list[Any]:
    return list(row) if row else []


def _filled(row: Sequence[Any]) -> list[Any]:
    return [c for c in row if c is not None and text(c)]


# Price sheets -------------------------------------------------------------


@dataclass(frozen=True)
class PriceRow:
    year: int
    region: str  # national, urban or rural
    geography: str  # a province code, "Canada", "Provinces", "Territories", "North", "South"
    plan_en: str
    plan_fr: str
    technology: str | None  # 3G, LTE, 5G, lowest; None for Internet
    value: float | None
    as_published: str | None


_REGIONS = {"national": "national", "urban": "urban", "urbain / urban": "urban", "rural": "rural"}
_GEOGRAPHIES = {
    "canada": "Canada",
    "provinces": "Provinces",
    "territoires / territories": "Territories",
    "territories": "Territories",
    "north": "North",
    "south": "South",
}


def _plan_fr(plan_en: str, forfait: str) -> str:
    # The French column says "Forfait voix" in some years and "Plan voix" in
    # others for the same talk-only plan.
    if plan_en.lower() == "talk plan":
        return "Forfait voix"
    return forfait or plan_en


def parse_prices(rows: Iterable[Sequence[Any]], service: str) -> list[PriceRow]:
    iterator = iter(rows)
    header = [text(c).lower() for c in next(iterator, ())]
    if not header or not header[0].startswith("ann"):
        raise ValueError("the price sheet does not start with a Year header")
    speed_at = next((i for i, h in enumerate(header) if "speed" in h), None)
    out: list[PriceRow] = []
    for raw in iterator:
        row = _cells(raw)
        if len(row) < 6 or _year(row[0]) is None:
            continue
        region = _REGIONS.get(text(row[1]).lower(), text(row[1]).lower())
        place = text(row[2])
        geography = _GEOGRAPHIES.get(place.lower(), place.upper())
        plan_en = text(row[4])
        if service == "mobile":
            plan_en = re.sub(r"(\d)\s*GB$", r"\1 GB", plan_en)
        technology = None
        if speed_at is not None and speed_at < len(row):
            speed = text(row[speed_at])
            technology = "lowest" if "lowest" in speed.lower() else speed or None
        value, published = number(row[5])
        out.append(
            PriceRow(
                year=_year(row[0])[0],  # type: ignore[index]
                region=region,
                geography=geography,
                plan_en=plan_en,
                plan_fr=_plan_fr(plan_en, text(row[3])),
                technology=technology,
                value=value,
                as_published=published,
            )
        )
    return out


@dataclass(frozen=True)
class ReportedPrice:
    """One row of the "Prix-Prices" sheet: one provider's price in one place."""

    year: int
    provider: str | None  # the reporting entity; blank in every 2016 row
    brand: str | None
    region: str  # urban or rural
    place: str  # a census metropolitan area (urban) or a rural community
    province: str
    service: str  # mobile, internet or tv
    plan_en: str
    plan_fr: str
    technology: str | None  # 3G, LTE or 5G for mobile
    value: float | None
    as_published: str | None


_MOBILE_TECHNOLOGIES = {"3G", "LTE", "5G"}


def _column(header: list[str], *words: str) -> int | None:
    return next((i for i, h in enumerate(header) if all(w in h for w in words)), None)


def parse_reported_prices(rows: Iterable[Sequence[Any]]) -> list[ReportedPrice]:
    """The "Prix-Prices" sheet, every provider's reported price by place and plan.

    Confirmed on the file of 2026-05-14: 35,361 rows, 2016-2025, columns
    Year, Entity, Region, Census metropolitan area, Province, Forfait, Plan,
    Reported monthly price, Brand, Speed, Channels. The "census metropolitan
    area" column holds the 24 urban CMAs (13 from 2024) on urban rows and a
    rural community on rural rows. Mobile rows always name a network (3G, LTE
    or 5G) in Speed; mobile plans are written "50GB Plan" in some years and
    "50GB" in others; Internet plans are speeds ("50/10 Mbps"); TV rows (IPTV,
    DTH, Cable) are kept with service "tv". Entity is blank in every 2016 row
    and Brand in about a quarter of the rows.
    """
    iterator = iter(rows)
    header = [text(c).lower() for c in next(iterator, ())]
    at = {
        "year": 0,
        "provider": _column(header, "entity"),
        "region": _column(header, "region"),
        "place": _column(header, "census metropolitan"),
        "province": _column(header, "province"),
        "forfait": _column(header, "forfait"),
        "price": _column(header, "price"),
        "brand": _column(header, "brand"),
        "speed": _column(header, "speed"),
    }
    plan_at = next((i for i, h in enumerate(header) if h == "plan"), None)
    if not header or not header[0].startswith("ann") or plan_at is None or None in at.values():
        raise ValueError("the Prix-Prices sheet does not have the expected columns")
    columns: dict[str, int] = {k: v for k, v in at.items() if v is not None}
    width = max(*columns.values(), plan_at) + 1
    out: list[ReportedPrice] = []
    for number_read, raw in enumerate(iterator):
        if number_read % 2000 == 0:
            check_deadline()
        row = _cells(raw)
        if len(row) < width or _year(row[0]) is None:
            continue
        plan_en = re.sub(r"(\d)\s*GB(?:\s+Plan)?$", r"\1 GB", text(row[plan_at]))
        speed = text(row[columns["speed"]])
        if speed in _MOBILE_TECHNOLOGIES or plan_en.endswith(" GB") or plan_en == "Talk Plan":
            service = "mobile"
        elif plan_en.lower().endswith("mbps"):
            service = "internet"
        else:
            service = "tv"
        region = text(row[columns["region"]]).lower()
        value, published = number(row[columns["price"]])
        out.append(
            ReportedPrice(
                year=_year(row[0])[0],  # type: ignore[index]
                provider=text(row[columns["provider"]]) or None,
                brand=text(row[columns["brand"]]) or None,
                region="rural" if region == "rural" else "urban",
                place=text(row[columns["place"]]),
                province=text(row[columns["province"]]).upper(),
                service=service,
                plan_en=plan_en,
                plan_fr=_plan_fr(plan_en, text(row[columns["forfait"]])),
                technology=speed if service == "mobile" and speed else None,
                value=value,
                as_published=published,
            )
        )
    return out


def parse_version(rows: Iterable[Sequence[Any]]) -> tuple[str | None, date | None]:
    """The current version and its release date from a "Version" sheet."""
    for raw in rows:
        row = _cells(raw)
        if len(row) >= 3 and "current" in text(row[2]).lower():
            released = row[1]
            if isinstance(released, datetime):
                return text(row[0]), released.date()
            if isinstance(released, str):
                # The CSV copy writes 8/21/2026; the workbook a real date.
                match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", released.strip())
                if match:
                    month, day, year = (int(g) for g in match.groups())
                    return text(row[0]), date(year, month, day)
            return text(row[0]), None
    return None, None


# Sector workbooks -----------------------------------------------------------


@dataclass(frozen=True)
class TableRef:
    table_id: str
    label: str
    title: str
    kind: str  # infographic, figure, table, supplementary


def _kind(sheet: str) -> str:
    letter = sheet.split("-", 1)[1][:1] if "-" in sheet else ""
    return {
        "I": "infographic",
        "F": "figure",
        "G": "figure",
        "T": "table",
        "S": "supplementary",
    }.get(letter, "other")


def parse_contents(rows: Iterable[Sequence[Any]], sheets: Sequence[str]) -> list[TableRef]:
    """Tables listed on the contents sheet that exist as sheets, in order, once each."""
    names = set(sheets)
    seen: set[str] = set()
    out: list[TableRef] = []
    for raw in rows:
        cells = [text(c) for c in _cells(raw)]
        cells = [c for c in cells if c]
        if len(cells) < 3 or cells[1] not in names or cells[1] in seen:
            continue
        seen.add(cells[1])
        out.append(TableRef(cells[1], cells[0], cells[2], _kind(cells[1])))
    return out


def sheet_aliases(table_id: str) -> list[str]:
    """The same table's tab name in the other language's workbook (F <-> G)."""
    wanted = table_id.strip().upper()
    out = [wanted]
    match = re.match(r"^([A-Z]{1,2})-([FG])(.*)$", wanted)
    if match:
        prefix, letter, rest = match.groups()
        other = "G" if letter == "F" else "F"
        # "N-F2 & F13" is "N-G2 & G13" in the French workbook.
        out.append(f"{prefix}-{other}{rest.replace(letter, other)}")
    return out


@dataclass
class Observation:
    block: str | None
    series: str
    qualifier: str | None
    year: int
    mobile_phone_only: bool
    value: float | None
    as_published: str | None


@dataclass
class ParsedTable:
    label: str
    title: str
    observations: list[Observation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    derived_columns: list[str] = field(default_factory=list)


def _header_years(row: list[Any]) -> dict[int, tuple[int, bool]]:
    found = {i: y for i, c in enumerate(row) if (y := _year(c)) is not None}
    return found if len(found) >= 2 else {}


def _qualifier_row(row: list[Any], years: dict[int, tuple[int, bool]]) -> bool:
    """A second header row: text under the year columns and no numbers anywhere."""
    under = [row[i] for i in years if i < len(row) and row[i] is not None]
    return bool(under) and all(isinstance(c, str) and number(c)[0] is None for c in under)


def parse_table(rows: Iterable[Sequence[Any]]) -> ParsedTable:
    nonempty = [r for r in (_cells(raw) for raw in rows) if _filled(r)]
    label = text(_filled(nonempty[0])[0]) if nonempty else ""
    title = text(_filled(nonempty[1])[0]) if len(nonempty) > 1 else ""
    table = ParsedTable(label=label, title=title)
    years: dict[int, tuple[int, bool]] = {}
    qualifiers: dict[int, str] = {}
    first_year = 0
    block: str | None = None
    pending_block: str | None = None
    carried: list[str] = []
    in_notes = False
    for row in nonempty[2:]:
        filled = _filled(row)
        first = text(row[0]) if row else ""
        found = _header_years(row)
        if found and not in_notes:
            years, qualifiers, first_year = found, {}, min(found)
            block, pending_block, carried = pending_block, None, []
            for i, cell in enumerate(row):
                if i >= first_year and _year(cell) is None and text(cell):
                    name = text(cell)
                    if _DERIVED.search(name) and name not in table.derived_columns:
                        table.derived_columns.append(name)
            continue
        if (
            years
            and not qualifiers
            and not in_notes
            and _qualifier_row(row, years)
            and not any(text(row[i]) for i in range(min(first_year, len(row))))
        ):
            qualifiers = {i: text(row[i]) for i in years if i < len(row) and text(row[i])}
            continue
        if _SOURCE_LINE.match(first) or in_notes:
            in_notes = True
            table.notes.append(text(filled[0]) if len(filled) == 1 else " ".join(map(text, filled)))
            continue
        labels = [text(row[i]) if i < len(row) else "" for i in range(first_year)]
        values = [(i, row[i] if i < len(row) else None) for i in years]
        has_value = any(number(v)[0] is not None or text(v) for _, v in values)
        if not years or (len(filled) == 1 and not has_value):
            # A one-cell row names the block the next header row starts (MB-S1
            # holds two); one between a header and its first data row is skipped.
            if not years or table.observations:
                pending_block = text(filled[0])
            continue
        if not has_value:
            continue
        # Merged label cells come through empty after their first row.
        carried = [lab or (carried[i] if i < len(carried) else "") for i, lab in enumerate(labels)]
        series = " | ".join(lab for lab in carried if lab) or title
        for i, cell in values:
            value, published = number(cell)
            if value is None and published is None:
                continue
            year, mobile_only = years[i]
            table.observations.append(
                Observation(
                    block=block,
                    series=series,
                    qualifier=qualifiers.get(i),
                    year=year,
                    mobile_phone_only=mobile_only,
                    value=value,
                    as_published=published,
                )
            )
    return table


def is_table_sheet(name: str) -> bool:
    return bool(_SHEET_ID.match(name))


# Quarterly trends -------------------------------------------------------------


@dataclass(frozen=True)
class TrendRow:
    year: int
    quarter: int
    market_en: str | None
    market_fr: str | None
    metric_en: str
    metric_fr: str
    subcategory_en: str | None
    subcategory_fr: str | None
    measure_en: str
    measure_fr: str
    value: float


_PAIRS = {
    "marché d'affaires": "market_fr",
    "business market": "market_en",
    "mesure": "metric_fr",
    "metric": "metric_en",
    "souscatégorie": "subcategory_fr",
    "subcategory": "subcategory_en",
}


def _measure_names(name: str) -> tuple[str, str]:
    if " / " in name:
        fr, en = name.split(" / ", 1)
        return en.strip(), fr.strip()
    return name, name


def parse_trends(rows: Iterable[Sequence[Any]]) -> list[TrendRow]:
    iterator = iter(rows)
    header = [text(c) for c in next(iterator, ())]
    if not header or header[0].lower() != "date":
        raise ValueError("the quarterly sheet does not start with a Date header")
    roles: dict[str, int] = {}
    measures: dict[int, tuple[str, str]] = {}
    for i, name in enumerate(header[1:], start=1):
        role = _PAIRS.get(name.lower())
        if role:
            roles[role] = i
        elif name:
            measures[i] = _measure_names(name)
    if "metric_en" not in roles:
        raise ValueError("the quarterly sheet has no Metric column")

    def cell(row: list[Any], role: str) -> str | None:
        at = roles.get(role)
        return (text(row[at]) or None) if at is not None and at < len(row) else None

    out: list[TrendRow] = []
    for raw in iterator:
        row = _cells(raw)
        match = _QUARTER.match(text(row[0])) if row else None
        if match is None:
            continue
        for i, (measure_en, measure_fr) in measures.items():
            value = number(row[i])[0] if i < len(row) else None
            if value is None:
                continue
            out.append(
                TrendRow(
                    year=int(match.group(1)),
                    quarter=int(match.group(2)),
                    market_en=cell(row, "market_en"),
                    market_fr=cell(row, "market_fr"),
                    metric_en=cell(row, "metric_en") or "",
                    metric_fr=cell(row, "metric_fr") or cell(row, "metric_en") or "",
                    subcategory_en=cell(row, "subcategory_en"),
                    subcategory_fr=cell(row, "subcategory_fr") or cell(row, "subcategory_en"),
                    measure_en=measure_en,
                    measure_fr=measure_fr,
                    value=value,
                )
            )
    out.sort(
        key=lambda r: (
            r.metric_en,
            r.market_en or "",
            r.subcategory_en or "",
            r.measure_en,
            r.year,
            r.quarter,
        )
    )
    return out

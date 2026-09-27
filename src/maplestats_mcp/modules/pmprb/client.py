"""Client for PMPRB annual report tables and patented medicines lists.

Checked live 2026-09-27 on canada.ca, English and French:

1. The annual reports index links each report as "Annual Report YYYY" /
   "Rapport annuel YYYY" (HTML for 2018 to 2024; the 2018 one sits under
   /reports-studies/ rather than /annual-reports/) and the patented
   medicines lists as "List of Patented Medicines YYYY" (HTML for 2020
   and 2021 only; PDF for 2018 and 2019; none after 2021). Everything
   from 2017 back is on the retired pmprb-cepmb.gc.ca site, so links are
   read from the index rather than built, and only canada.ca HTML pages
   are kept.
2. A report holds 31 (2023) to 63 (2020 to 2022) <table>s. Few have a
   <caption>; the title ("Table 7. Total R&D Expenditures ...", "Figure 1.
   Annual Rate of Change ...") is a <b> in the <p> or <figure> just
   before the table, and a chart's numbers are in a table inside the
   <details> "Figure description" after it. One title can own several
   tables (Figure 2 has two; Table 2 has three, captioned "Allegations of
   Excessive Pricing" and so on). In 2021, two tables carry the real
   title as their <caption> while the nearest <b> is the previous figure,
   so a caption that starts with "Table"/"Figure" wins.
3. Some tables have two header rows with colspans (2024 Table 5: "Patented
   medicine" over "Sales ($billions)" and "Change in sales"), so headers
   are laid out on a grid before columns are named.
4. Numbers are written "$17,093,674", "10.9%", "$531.08" in English and
   "1 294,8 $", "2,2 %" with no-break or narrow spaces in French (one
   French cell has no space: "1 294,8$").
5. The medicines lists are one table per company (103 in 2020 and 2021,
   captioned with the company) with DIN, brand, ingredient, ATC, dosage
   form, comments and status in that order in both languages; French
   headers differ between tables ("Appellation commerciale" or "Nom de
   marque"), so columns are read by position. Empty comments read
   "blank". Status spellings vary ("Does Not Trigger", "Does not
   Trigger"; "NOH" in 2021, "Notice of Hearing" in 2020).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from maplestats_mcp.modules.pmprb import constants
from maplestats_mcp.modules.pmprb.schemas import (
    PmprbMedicine,
    PmprbMedicineList,
    PmprbReport,
    PmprbTable,
    PmprbTableInfo,
    PmprbTableList,
    PmprbTableResult,
    Value,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_LABEL = re.compile(r"^\s*(Table|Tableau|Figure)\s+\d+", re.IGNORECASE)
_SPACES = re.compile(r"[\s   ]+")
_NUMBER = re.compile(r"[-+]?\d+(\.\d+)?")
_TITLE_TAGS = ("b", "strong", "h3", "h4", "figcaption")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _text(node: Tag | NavigableString) -> str:
    return _SPACES.sub(" ", node.get_text(" ")).strip()


async def _fetch(url: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 410):
            raise NotFound(f"pmprb: {url} is gone (HTTP {status}); the page moved.") from exc
        raise UpstreamError(f"pmprb: {url} returned HTTP {status}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"pmprb: {url} did not respond in time.") from exc
    if len(response.content) > constants.MAX_PAGE_BYTES:
        raise UpstreamError(f"pmprb: {url} is much larger than expected; the page changed.")
    return response.text


def _provenance(url: str, cached: bool, schema: str, coverage: str | None = None) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"pmprb.{schema}",
        freshness="once a year (each annual report)",
        coverage=coverage,
        limits="Canada.ca terms: non-commercial reproduction with attribution to PMPRB",
    )


# ------------------------------------------------------------------ index


def parse_index(html: str, base: str) -> list[PmprbReport]:
    soup = BeautifulSoup(html, "html.parser")
    reports: dict[tuple[str, int], PmprbReport] = {}
    for anchor in (soup.find("main") or soup).find_all("a"):
        title = _text(anchor)
        url = urljoin(base, str(anchor.get("href") or ""))
        parsed = urlparse(url)
        if parsed.netloc != "www.canada.ca" or not parsed.path.endswith(".html"):
            continue
        for kind, pattern in (
            ("annual_report", constants.REPORT_LINK),
            ("patented_medicines_list", constants.LIST_LINK),
        ):
            if match := re.match(pattern, title):
                year = int(match.group(1))
                reports.setdefault(
                    (kind, year),
                    PmprbReport(year=year, kind=kind, title=title, url=url),  # type: ignore[arg-type]
                )
    return sorted(reports.values(), key=lambda r: (r.kind, -r.year))


async def _reports(lang: str) -> tuple[list[PmprbReport], bool]:
    url = constants.INDEX_PAGE[lang]

    async def fetch() -> list[PmprbReport]:
        found = parse_index(await _fetch(url), url)
        if not any(r.kind == "annual_report" for r in found):
            raise UpstreamError("pmprb: the annual reports index lists no HTML report.")
        return found

    return await cached_fetch(f"pmprb:index:{lang}", constants.INDEX_TTL_SECONDS, fetch)


async def _report(year: int, kind: str, lang: str) -> PmprbReport:
    reports, _ = await _reports(lang)
    for report in reports:
        if report.year == year and report.kind == kind:
            return report
    years = sorted(r.year for r in reports if r.kind == kind)
    what = "annual report" if kind == "annual_report" else "patented medicines list"
    raise NotFound(f"pmprb: no HTML {what} for {year}; available: {years}.")


# ------------------------------------------------------------------ tables


def parse_number(text: str, lang: str) -> Value:
    """'$17,093,674' -> 17093674, '2,2 %' (fr) -> 2.2; anything else stays text."""
    cleaned = _SPACES.sub("", text).replace("$", "").replace("%", "").replace("−", "-")
    cleaned = cleaned.replace(",", ".") if lang == "fr" else cleaned.replace(",", "")
    if not _NUMBER.fullmatch(cleaned):
        return text or None
    return float(cleaned) if "." in cleaned else int(cleaned)


def _span(cell: Tag, attribute: str) -> int:
    raw = str(cell.get(attribute) or "1").strip()
    return max(1, int(raw)) if raw.isdigit() else 1


def _grid(table: Tag) -> tuple[list[list[str]], int]:
    """Cell text laid out on a grid (colspan and rowspan expanded), and header rows."""
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    grid: list[list[str | None]] = []
    carry: dict[tuple[int, int], str] = {}
    for r, tr in enumerate(rows):
        line: list[str | None] = []
        c = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while (r, c) in carry:
                line.append(carry.pop((r, c)))
                c += 1
            text = _text(cell)
            for _ in range(_span(cell, "colspan")):
                line.append(text)
                for extra in range(1, _span(cell, "rowspan")):
                    carry[(r + extra, c)] = text
                c += 1
        while (r, c) in carry:
            line.append(carry.pop((r, c)))
            c += 1
        grid.append(line)
    width = max((len(line) for line in grid), default=0)
    cells = [[x or "" for x in line] + [""] * (width - len(line)) for line in grid]

    thead = table.find("thead")
    if thead is not None:
        headers = len(thead.find_all("tr"))
    else:
        headers = 0
        for tr in rows:
            if tr.find("td") is None:
                headers += 1
            else:
                break
    return cells, max(1, headers) if cells else 0


def _columns(header_rows: list[list[str]]) -> list[str]:
    names: list[str] = []
    for c in range(len(header_rows[0]) if header_rows else 0):
        parts: list[str] = []
        for row in header_rows:
            if row[c] and (not parts or parts[-1] != row[c]):
                parts.append(row[c])
        name = " - ".join(parts) or ("row" if c == 0 else f"column {c + 1}")
        base, n = name, 2
        while name in names:
            name = f"{base} ({n})"
            n += 1
        names.append(name)
    return names


def _label_and_section(table: Tag) -> tuple[str | None, str | None, str | None]:
    caption = table.find("caption")
    caption_text = _text(caption) if caption is not None else None
    label: str | None = None
    section: str | None = None
    if caption_text and _LABEL.match(caption_text):
        label, caption_text = caption_text, None
    for node in table.previous_elements:
        if isinstance(node, Tag) and node.name in ("h2", "h3") and not _LABEL.match(_text(node)):
            section = _text(node)
            break
        # Titles are <b>, <strong> or (Figure 5 in 2019-2022) <h3>; a <p>
        # starting "Figure 1 illustrates ..." (2018) is prose, not a title.
        owner = node.parent if isinstance(node, NavigableString) else None
        if (
            label is None
            and owner is not None
            and owner.name in _TITLE_TAGS
            and _LABEL.match(str(node))
        ):
            label = _text(owner)
    return label, caption_text, section


def parse_report(html: str, year: int, lang: str) -> list[PmprbTable]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[PmprbTable] = []
    for index, table in enumerate((soup.find("main") or soup).find_all("table"), start=1):
        if table.find_parent("table") is not None:
            continue
        cells, header_count = _grid(table)
        if not cells:
            continue
        columns = _columns(cells[:header_count])
        rows = [
            {name: parse_number(value, lang) for name, value in zip(columns, line, strict=False)}
            for line in cells[header_count:]
            if any(line)
        ]
        label, subtitle, section = _label_and_section(table)
        info = PmprbTableInfo(
            year=year,
            index=index,
            label=label,
            subtitle=subtitle,
            section=section,
            columns=columns,
            row_count=len(rows),
        )
        tables.append(PmprbTable(info=info, rows=rows))
    return tables


async def _report_tables(year: int, lang: str) -> tuple[PmprbReport, list[PmprbTable], bool]:
    report = await _report(year, "annual_report", lang)

    async def fetch() -> list[PmprbTable]:
        tables = parse_report(await _fetch(report.url), year, lang)
        if not tables:
            raise UpstreamError(f"pmprb: the {year} report page has no tables; it changed.")
        return tables

    tables, cached = await cached_fetch(
        f"pmprb:report:{year}:{lang}", constants.PAGE_TTL_SECONDS, fetch
    )
    return report, tables, cached


def _table_matches(info: PmprbTableInfo, words: list[str]) -> bool:
    text = _fold(
        " ".join([info.label or "", info.subtitle or "", info.section or "", *info.columns])
    )
    return all(w in text for w in words)


async def list_report_tables(
    year: int | None = None, *, query: str = "", lang: str = "en"
) -> PmprbTableList:
    """The reports on canada.ca, and the tables of one year (or all years) matching `query`."""
    reports, cached = await _reports(lang)
    words = _fold(query).split()
    years = [r.year for r in reports if r.kind == "annual_report"]
    if year is not None:
        years = [year]
    elif not words:
        return PmprbTableList(
            reports=reports,
            total_matched=0,
            provenance=_provenance(
                constants.INDEX_PAGE[lang], cached, "PmprbTableList", "pass a year or a query"
            ),
        )
    loaded = await asyncio.gather(*(_report_tables(y, lang) for y in years))
    found = [t.info for _, tables, _ in loaded for t in tables if _table_matches(t.info, words)]
    url = loaded[0][0].url if year is not None else constants.INDEX_PAGE[lang]
    return PmprbTableList(
        reports=reports,
        tables=found,
        total_matched=len(found),
        provenance=_provenance(
            url,
            all(c for _, _, c in loaded),
            "PmprbTableList",
            f"annual reports {min(years)}-{max(years)}",
        ),
    )


def _selector(text: str) -> str:
    return _fold(text).replace("tableau", "table")


async def get_report_table(year: int, table: str, *, lang: str = "en") -> PmprbTableResult:
    """Tables of one report picked by position ('12') or title ('Figure 1', 'Table 5')."""
    wanted = table.strip()
    if not wanted:
        raise InvalidInput("pmprb: pass a table position like '12' or a title like 'Figure 1'.")
    report, tables, cached = await _report_tables(year, lang)
    if wanted.isdigit():
        chosen = [t for t in tables if t.info.index == int(wanted)]
    else:
        prefix = _selector(wanted)
        chosen = [
            t
            for t in tables
            if t.info.label and re.match(re.escape(prefix) + r"(?!\d)", _selector(t.info.label))
        ]
    if not chosen:
        raise NotFound(
            f"pmprb: no table {wanted!r} in the {year} report; see pmprb_list_report_tables."
        )
    return PmprbTableResult(
        report=report,
        tables=chosen,
        provenance=_provenance(report.url, cached, "PmprbTableResult"),
    )


# -------------------------------------------------------------- medicines


def _status(text: str, lang: str) -> tuple[str | None, str | None]:
    folded = _fold(text)
    if not folded:
        return None, None
    for code, (english, french, spellings) in constants.STATUSES.items():
        if folded in spellings or folded == _fold(english) or folded == _fold(french):
            return code, french if lang == "fr" else english
    return None, text


def parse_medicines(html: str, lang: str) -> list[PmprbMedicine]:
    soup = BeautifulSoup(html, "html.parser")
    medicines: list[PmprbMedicine] = []
    for table in (soup.find("main") or soup).find_all("table"):
        caption = table.find("caption")
        company = _text(caption) if caption is not None else ""
        for tr in table.find_all("tr")[1:]:
            cells = [_text(td) for td in tr.find_all(["th", "td"])]
            if len(cells) < 7 or not cells[0]:
                continue
            code, label = _status(cells[6], lang)
            comments = cells[5] if cells[5].casefold() not in ("", "blank") else None
            medicines.append(
                PmprbMedicine(
                    company=company,
                    din=cells[0],
                    brand_name=cells[1],
                    medicinal_ingredient=cells[2],
                    atc=cells[3] or None,
                    dosage_form=cells[4] or None,
                    comments=comments,
                    status=code,
                    status_label=label,
                )
            )
    return medicines


async def search_patented_medicines(
    query: str = "",
    *,
    company: str = "",
    atc: str = "",
    status: str | None = None,
    year: int = 2021,
    limit: int = constants.MEDICINES_DEFAULT_LIMIT,
    lang: str = "en",
) -> PmprbMedicineList:
    """Patented medicines reported for a year, filtered by words, company, ATC or status."""
    if not 1 <= limit <= constants.MEDICINES_MAX_LIMIT:
        raise InvalidInput(f"pmprb: limit must be 1 to {constants.MEDICINES_MAX_LIMIT}.")
    if status and status not in constants.STATUSES:
        raise InvalidInput(f"pmprb: unknown status {status!r}; use {list(constants.STATUSES)}.")
    report = await _report(year, "patented_medicines_list", lang)

    async def fetch() -> list[PmprbMedicine]:
        found = parse_medicines(await _fetch(report.url), lang)
        if not found:
            raise UpstreamError(f"pmprb: the {year} medicines list has no rows; it changed.")
        return found

    medicines, cached = await cached_fetch(
        f"pmprb:medicines:{year}:{lang}", constants.PAGE_TTL_SECONDS, fetch
    )
    words = _fold(query).split()
    wanted_company = _fold(company)
    wanted_atc = atc.strip().upper()
    matched = [
        m
        for m in medicines
        if all(
            w in _fold(f"{m.din} {m.brand_name} {m.medicinal_ingredient} {m.company}")
            for w in words
        )
        and (not wanted_company or wanted_company in _fold(m.company))
        and (not wanted_atc or (m.atc or "").upper().startswith(wanted_atc))
        and (not status or m.status == status)
    ]
    counts: dict[str, int] = {}
    for m in matched:
        counts[m.status or "other"] = counts.get(m.status or "other", 0) + 1
    shown = matched[:limit]
    return PmprbMedicineList(
        report=report,
        medicines=shown,
        returned_count=len(shown),
        total_matched=len(matched),
        by_status=dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        provenance=_provenance(
            report.url, cached, "PmprbMedicineList", f"{len(medicines)} medicines reported"
        ),
    )

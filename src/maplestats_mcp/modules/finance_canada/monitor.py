"""Client for The Fiscal Monitor's monthly canada.ca pages.

Checked live 2026-10-03 on the July 2026 issue, English and French, and
the feed's 61 issues since January 2021:

1. Issues come from the publications feed (type "Fiscal Monitor"); a
   link ends in /fiscal-monitor/2026/07.html (/revue-financiere/ in
   French). Some issues cover two months ("April and May 2026", linked
   as 2026/04), so the period is the link's year and month.
2. Six numbered tables carry a <caption> "Table 2<br><strong>Revenues
   </strong>" ("Tableau 2 Revenus"); three chart data tables have none
   and sit in a <figure> whose <figcaption> reads "Chart 1 ..."
   ("Graphique 1 ...", with a no-break space).
3. Headers are up to three <thead> rows with colspans ("July" over
   "2025" and "2026"; "($ millions)" over both), and a year can carry a
   footnote <sup>1</sup>, which is dropped. Section rows ("Tax
   revenues", "Income taxes") are a single <th colspan=7>.
4. Numbers: "17,121", "-1,512", "(7,711)" for negatives, "7.9"; French
   "17 121" with no-break spaces, "5,2", "(7 711)". "n/a" / "s.o." and
   dashes mean no value.
5. The same tables are published as CSV files in a yearly ZIP on
   open.canada.ca ("The Fiscal Monitor: 2026"), but those lag the page
   by a month or more, so the page is read.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.finance_canada import constants
from maplestats_mcp.modules.finance_canada.client import _raise, _say, feed, fetch, fold
from maplestats_mcp.modules.finance_canada.schemas import (
    MonitorIssue,
    MonitorIssueList,
    MonitorTable,
    MonitorTables,
    Value,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_PERIOD = re.compile(r"/(\d{4})/(\d{2})\.html$")
_SPACES = re.compile(r"[\s   ]+")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_NONE = {"", "-", "–", "—", "n/a", "s.o.", "...", ".."}


def issues_from_feed(entries: list[dict[str, Any]], lang: str) -> list[MonitorIssue]:
    found: dict[str, MonitorIssue] = {}
    for entry in entries:
        if entry.get("pub-type") != "Fiscal Monitor":
            continue
        link = str(entry.get("link-fr" if lang == "fr" else "link") or "")
        match = _PERIOD.search(link)
        if not match:
            continue
        period = f"{match.group(1)}-{match.group(2)}"
        found[period] = MonitorIssue(
            period=period,
            title=str(entry.get("title-fr" if lang == "fr" else "title") or ""),
            published=str(entry.get("pub-date") or "") or None,
            url=link,
        )
    return sorted(found.values(), key=lambda i: i.period, reverse=True)


def _provenance(url: str, cached: bool, schema: str, lang: str) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"finance_canada.{schema}",
        freshness=_say(
            "monthly, about two months after the month it covers",
            "mensuelle, environ deux mois après le mois visé",
            lang,
        ),
        coverage=_say("issues since January 2021", "numéros depuis janvier 2021", lang),
        licence=_say(constants.MONITOR_TERMS, constants.MONITOR_TERMS_FR, lang),
        lang=lang,
    )


async def list_issues(*, lang: str = "en") -> MonitorIssueList:
    entries, cached = await feed(lang)
    issues = issues_from_feed(entries, lang)
    if not issues:
        _raise(
            UpstreamError,
            "finance_canada: the feed lists no Fiscal Monitor issue.",
            "finance_canada : le fil ne liste aucun numéro de La revue financière.",
            lang,
        )
    return MonitorIssueList(
        issues=issues,
        provenance=_provenance(constants.FEED_URL, cached, "MonitorIssueList", lang),
    )


def parse_number(text: str, lang: str = "en") -> Value:
    """'(7,711)' -> -7711, '17 121' (fr) -> 17121, '5,2' (fr) -> 5.2; text stays text."""
    raw = _SPACES.sub(" ", text).strip()
    if raw.casefold() in _NONE:
        return None
    compact = raw.replace(" ", "")
    negative = compact.startswith("(") and compact.endswith(")")
    compact = compact.strip("()").replace("−", "-")
    # English groups thousands with commas; French with spaces and a decimal comma.
    compact = compact.replace(",", ".") if lang == "fr" else compact.replace(",", "")
    if not _NUMBER.match(compact):
        return raw
    value = float(compact)
    value = -value if negative else value
    return int(value) if value.is_integer() and "." not in compact else value


def _cell_text(cell: Tag) -> str:
    for sup in cell.find_all("sup"):
        sup.decompose()
    return _SPACES.sub(" ", cell.get_text(" ")).strip()


def _grid(table: Tag) -> tuple[list[list[str]], int, list[bool]]:
    """Cell text laid out with colspans expanded, header row count, and section-row flags."""
    trs = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    grid: list[list[str]] = []
    single: list[bool] = []
    # Cells carried down by rowspan (the 2023 issues' empty top-left header
    # cell spans all header rows), keyed by (row, column).
    carry: dict[tuple[int, int], str] = {}

    def span(cell: Tag, attribute: str) -> int:
        raw = str(cell.get(attribute) or "1").strip()
        return max(1, int(raw)) if raw.isdigit() else 1

    for r, tr in enumerate(trs):
        line: list[str] = []
        cells = tr.find_all(["th", "td"], recursive=False)
        for cell in cells:
            while (r, len(line)) in carry:
                line.append(carry.pop((r, len(line))))
            text = _cell_text(cell)
            for _ in range(span(cell, "colspan")):
                for below in range(1, span(cell, "rowspan")):
                    carry[(r + below, len(line))] = text
                line.append(text)
        while (r, len(line)) in carry:
            line.append(carry.pop((r, len(line))))
        grid.append(line)
        single.append(len(cells) == 1)
    thead = table.find("thead")
    headers = len(thead.find_all("tr")) if thead is not None else 1
    return grid, headers, single


def _label(table: Tag, index: int) -> str:
    caption = table.find("caption")
    if caption is not None:
        return _cell_text(caption)
    figure = table.find_parent("figure")
    figcaption = (
        figure.find("figcaption") if figure is not None else table.find_previous("figcaption")
    )
    if figcaption is not None:
        return _SPACES.sub(" ", figcaption.get_text(" ")).strip()
    return f"Chart data {index}"


def parse_issue(html: str, lang: str = "en") -> list[MonitorTable]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[MonitorTable] = []
    for index, table in enumerate((soup.find("main") or soup).find_all("table"), start=1):
        if table.find_parent("table") is not None:
            continue
        grid, header_count, single = _grid(table)
        if len(grid) <= header_count:
            continue
        width = max(len(line) for line in grid)
        headers = [line + [""] * (width - len(line)) for line in grid[:header_count]]
        # A "Change" column has an empty top cell; it belongs to the group on its left.
        if header_count > 1:
            for c in range(2, width):
                if not headers[0][c]:
                    headers[0][c] = headers[0][c - 1]
        names: list[str] = []
        keep: list[int] = []
        previous: list[str] | None = None
        for c in range(width):
            parts: list[str] = []
            for line in headers:
                if line[c] and (not parts or parts[-1] != line[c]):
                    parts.append(line[c])
            # Two-month issues give the current-year cell colspan=2 in the header
            # and in every row, so the expanded copy repeats the previous column.
            if c > 1 and parts and parts == previous:
                continue
            previous = parts
            base = " - ".join(parts) or ("row" if c == 0 else f"column {c + 1}")
            name, n = base, 2
            while name in names:
                name = f"{base} ({n})"
                n += 1
            names.append(name)
            keep.append(c)
        rows: list[dict[str, Value]] = []
        section: str | None = None
        for line, is_section in zip(grid[header_count:], single[header_count:], strict=True):
            if is_section:
                section = line[0] if line else None
                continue
            record: dict[str, Value] = {names[0]: line[0] if line else ""}
            for name, c in zip(names[1:], keep[1:], strict=True):
                record[name] = parse_number(line[c] if c < len(line) else "", lang)
            if section:
                record["section"] = section
            rows.append(record)
        # A trailing header cell with no data under it (two-month issues) is dropped.
        empty = [n for n in names[1:] if all(r.get(n) is None for r in rows)]
        if empty and rows:
            names = [n for n in names if n not in empty]
            rows = [{k: v for k, v in r.items() if k not in empty} for r in rows]
        tables.append(MonitorTable(label=_label(table, index), columns=names, rows=rows))
    return tables


async def get_tables(period: str = "", *, table: str = "", lang: str = "en") -> MonitorTables:
    """One issue's tables (all, or those whose label starts with `table`)."""
    issues = (await list_issues(lang=lang)).issues
    wanted = period.strip()
    if wanted and not re.fullmatch(r"\d{4}-\d{2}", wanted):
        _raise(
            InvalidInput,
            "finance_canada: period is YYYY-MM, e.g. '2026-07'.",
            "finance_canada : period est au format AAAA-MM, p. ex. '2026-07'.",
            lang,
        )
    issue = issues[0] if not wanted else next((i for i in issues if i.period == wanted), None)
    if issue is None:
        nearby = [i.period for i in issues if i.period[:4] == wanted[:4]]
        _raise(
            NotFound,
            f"finance_canada: no Fiscal Monitor for {wanted}; that year has {nearby or 'none'} "
            "(two-month issues are listed under their first month).",
            f"finance_canada : aucune revue financière pour {wanted} ; cette année compte "
            f"{nearby or 'aucun numéro'} (les numéros de deux mois sont listés sous leur "
            "premier mois).",
            lang,
        )

    async def load() -> list[MonitorTable]:
        response = await fetch(issue.url, constants.MAX_PAGE_BYTES, lang)
        found = parse_issue(response.text, lang)
        if not found:
            _raise(
                UpstreamError,
                f"finance_canada: {issue.url} has no tables; the page changed.",
                f"finance_canada : {issue.url} n'a aucun tableau ; la page a changé.",
                lang,
            )
        return found

    tables, cached = await cached_fetch(
        f"finance_canada:monitor:{issue.period}:{lang}", constants.MONITOR_TTL_SECONDS, load
    )
    chosen = tables
    if table.strip():
        key = fold(table).replace("tableau", "table").replace("graphique", "chart")
        if key.isdigit():
            key = f"table {key}"
        chosen = [
            t
            for t in tables
            if re.match(
                re.escape(key) + r"(?!\d)",
                fold(t.label).replace("tableau", "table").replace("graphique", "chart"),
            )
        ]
        if not chosen:
            labels = [t.label for t in tables]
            _raise(
                NotFound,
                f"finance_canada: no {table!r} in the {issue.period} issue; tables are {labels}.",
                f"finance_canada : aucun {table!r} dans le numéro {issue.period} ; les "
                f"tableaux sont {labels}.",
                lang,
            )
    return MonitorTables(
        issue=issue,
        tables=chosen,
        provenance=_provenance(issue.url, cached, "MonitorTables", lang),
    )

"""Members' expenditure reports (House of Commons proactive disclosure).

Checked live 2026-11-07 (see constants.DISCLOSURE_URL):

- The landing page lists every quarterly report since fiscal 2020-2021 Q2 as
  links /members/{fiscal year}/{quarter}?summaryId=<id>; fiscal year 2027 is
  2026-2027 and Q1 is April to June 2026. The quarter page answers without
  the summaryId. An unknown quarter answers 302 to an error page.
- A quarter page holds the report id (in /members/<report id>/csv, the summary
  CSV; not the summaryId of the link) and, on each member's row, links to
  /{travel,hospitality,contract}/{fy}/{q}/<member id>. Member ids differ per
  report and are the same in English and French; the detail CSVs are
  /{kind}/<report id>/<member id>/csv.
- CSVs are UTF-8 with a BOM. The summary has a header row (Name,
  Constituency, Caucus, Salaries, Travel, Hospitality, Contracts); names
  carry two spaces after the comma ("Aboultaif,  Ziad"), the page one. Detail
  CSVs start with a title line, then a header. French columns are in the same
  order, so columns are read by position.
- Q1 2026-2027: 370 members. Aboultaif's detail CSVs add up to the summary
  (travel 62,251.81, hospitality 349.43, contracts 14,503.00). Travel lines
  can predate the quarter (late claims) and can be negative (corrections).
  A hospitality event paid to several suppliers has one line per supplier,
  each repeating the event total.
"""

from __future__ import annotations

import csv
import html
import re
import unicodedata
from datetime import date

import httpx

from maplestats_mcp.modules.ourcommons import constants
from maplestats_mcp.modules.ourcommons.client import (
    _LIMITER,
    Lang,
    _check_lang,
    _fold,
    _needles,
)
from maplestats_mcp.modules.ourcommons.schemas import (
    ContractLine,
    ExpenditureReport,
    ExpenditureReports,
    ExpenditureTotals,
    HospitalityLine,
    MemberExpenditure,
    MemberExpenditureDetails,
    MemberExpenditures,
    TravelLine,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw

CATEGORIES = ("travel", "hospitality", "contract")
SORT_KEYS = ("total", "salaries", "travel", "hospitality", "contracts", "name")

_QUARTER_LINK = re.compile(r"/(?:members|deputes)/(\d{4})/([1-4])\?summaryId=")
_REPORT_ID = re.compile(r"/(?:members|deputes)/([0-9a-f-]{36})/csv", re.IGNORECASE)
_ROW = re.compile(r'<tr class="expenses-main-info">(.*?)</tr>', re.DOTALL)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_MEMBER_ID = re.compile(r"/\d{4}/[1-4]/([0-9a-f-]{36})", re.IGNORECASE)


def _clean(text: str) -> str:
    """Tags removed, entities decoded, whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _key(name: str, constituency: str) -> tuple[str, str]:
    return re.sub(r"\s+", " ", name).strip(), unicodedata.normalize("NFC", constituency.strip())


def period(fiscal_year: int, quarter: int) -> tuple[date, date]:
    """Fiscal year 2027 Q1 is April 1 to June 30, 2026 (label on the page)."""
    start_year = fiscal_year - 1 if quarter < 4 else fiscal_year
    start_month = {1: 4, 2: 7, 3: 10, 4: 1}[quarter]
    end_month = start_month + 2
    end_day = 30 if end_month in (6, 9) else 31
    return date(start_year, start_month, 1), date(start_year, end_month, end_day)


async def _get(url: str, lang: str, what_en: str, what_fr: str) -> str:
    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (301, 302, 404):
                # Unknown quarters and member ids answer 302 to an error page.
                raise lang_error(
                    NotFound,
                    lang,
                    f"ourcommons: {what_en} not found ({url}).",
                    f"ourcommons : {what_fr} introuvable ({url}).",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"ourcommons: {url} returned HTTP {status}.",
                f"ourcommons : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"ourcommons: {url} did not respond in time.",
                f"ourcommons : {url} n'a pas répondu à temps.",
            ) from exc
        return response.content.decode("utf-8-sig")

    text, _cached = await cached_fetch(
        f"ourcommons:{url}", constants.CACHE_TTL_EXPENDITURES_SECONDS, fetch
    )
    return text


def _amount(value: str) -> float | None:
    # A blank cell is not reported, not zero: keep it missing.
    value = value.strip()
    return float(value) if value else None


def _present_sum(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present), 2) if present else None


def _date(value: str) -> date | None:
    value = value.strip()
    return date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def _provenance(url: str, schema: str, lang: Lang, coverage: str | None = None):
    return make_provenance(
        source=constants.PROVENANCE_SOURCE,
        url=url,
        cached=False,
        schema_name=schema,
        freshness=fr_or_en(
            lang,
            "Quarterly; each report is published about three months after its quarter ends.",
            "Trimestriel ; chaque rapport paraît environ trois mois après la fin du trimestre.",
        ),
        coverage=coverage,
        limits=fr_or_en(
            lang,
            "Year-to-date figures are not given: each report covers one quarter. Before "
            "fiscal 2020-2021 Q2 the reports are only on the previous-reports page.",
            "Pas de cumul annuel : chaque rapport couvre un trimestre. Avant le 2e trimestre "
            "de 2020-2021, les rapports ne sont que sur la page des rapports antérieurs.",
        ),
        lang=lang,
    )


async def list_expenditure_reports(lang: Lang = "en") -> ExpenditureReports:
    _check_lang(lang)
    base = constants.DISCLOSURE_URL.format(lang=lang)
    page = await _get(base, lang, "the expenditure reports page", "la page des rapports")
    found = sorted({(int(y), int(q)) for y, q in _QUARTER_LINK.findall(page)}, reverse=True)
    if not found:
        raise lang_error(
            UpstreamError,
            lang,
            "ourcommons: no quarterly report links on the expenditure page; it may have changed.",
            "ourcommons : aucun lien de rapport trimestriel sur la page ; elle a peut-être changé.",
        )
    reports = []
    for fiscal_year, quarter in found:
        start, end = period(fiscal_year, quarter)
        reports.append(
            ExpenditureReport(
                fiscal_year=fiscal_year,
                fiscal_year_label=f"{fiscal_year - 1}-{fiscal_year}",
                quarter=quarter,
                period_start=start,
                period_end=end,
                url=f"{base}/{fiscal_year}/{quarter}",
            )
        )
    return ExpenditureReports(
        total_reports=len(reports),
        reports=reports,
        provenance=_provenance(base, "ourcommons.ExpenditureReports", lang),
    )


async def _quarter(
    fiscal_year: int | None, quarter: int | None, lang: Lang
) -> tuple[int, int, str, str, dict[tuple[str, str], str]]:
    """(fiscal year, quarter, page url, report id, member ids by (name, constituency))."""
    if (fiscal_year is None) != (quarter is None):
        raise lang_error(
            InvalidInput,
            lang,
            "ourcommons: give both fiscal_year and quarter, or neither for the latest report.",
            "ourcommons : indiquez fiscal_year et quarter, ou aucun des deux pour le dernier "
            "rapport.",
        )
    reports = (await list_expenditure_reports(lang)).reports
    if fiscal_year is None or quarter is None:
        fiscal_year, quarter = reports[0].fiscal_year, reports[0].quarter
    elif (fiscal_year, quarter) not in {(r.fiscal_year, r.quarter) for r in reports}:
        oldest, newest = reports[-1], reports[0]
        raise lang_error(
            NotFound,
            lang,
            f"ourcommons: no expenditure report for fiscal year {fiscal_year} Q{quarter}. "
            f"Reports run from {oldest.fiscal_year} Q{oldest.quarter} to "
            f"{newest.fiscal_year} Q{newest.quarter} (fiscal year 2027 is 2026-2027).",
            f"ourcommons : aucun rapport de dépenses pour l'exercice {fiscal_year} "
            f"T{quarter}. Les rapports vont de {oldest.fiscal_year} T{oldest.quarter} à "
            f"{newest.fiscal_year} T{newest.quarter} (l'exercice 2027 est 2026-2027).",
        )
    url = f"{constants.DISCLOSURE_URL.format(lang=lang)}/{fiscal_year}/{quarter}"
    page = await _get(url, lang, "that quarter's report", "le rapport de ce trimestre")
    report = _REPORT_ID.search(page)
    if not report:
        raise lang_error(
            UpstreamError,
            lang,
            f"ourcommons: no CSV link on {url}; the page may have changed.",
            f"ourcommons : aucun lien CSV sur {url} ; la page a peut-être changé.",
        )
    members: dict[tuple[str, str], str] = {}
    for row in _ROW.findall(page):
        cells = [_clean(cell) for cell in _CELL.findall(row)]
        member = _MEMBER_ID.search(row)
        if len(cells) >= 2 and member:
            members[_key(cells[0], cells[1])] = member.group(1)
    return fiscal_year, quarter, url, report.group(1), members


async def _summary(report_id: str, lang: Lang) -> list[MemberExpenditure]:
    url = f"{constants.DISCLOSURE_URL.format(lang=lang)}/{report_id}/csv"
    text = await _get(url, lang, "the summary CSV", "le CSV du sommaire")
    rows = list(csv.reader(text.splitlines()))
    out = []
    for row in rows[1:]:
        if len(row) < 7:
            continue
        salaries, travel, hospitality, contracts = (_amount(v) for v in row[3:7])
        out.append(
            MemberExpenditure(
                name=_key(row[0], row[1])[0],
                constituency=row[1].strip(),
                caucus=row[2].strip(),
                salaries=salaries,
                travel=travel,
                hospitality=hospitality,
                contracts=contracts,
                total=_present_sum([salaries, travel, hospitality, contracts]),
            )
        )
    if not out:
        raise lang_error(
            UpstreamError,
            lang,
            f"ourcommons: {url} held no member rows.",
            f"ourcommons : {url} ne contient aucune ligne de député.",
        )
    return out


def _check_limit(limit: int, lang: Lang) -> None:
    if not 1 <= limit <= constants.EXPENDITURES_LIMIT_MAX:
        raise lang_error(
            InvalidInput,
            lang,
            f"ourcommons: limit must be 1 to {constants.EXPENDITURES_LIMIT_MAX}.",
            f"ourcommons : limit doit être compris entre 1 et {constants.EXPENDITURES_LIMIT_MAX}.",
        )


def _filter(
    rows: list[MemberExpenditure],
    name: str | None,
    constituency: str | None,
    caucus: str | None,
) -> list[MemberExpenditure]:
    caucus_needles = _needles(caucus, constants.PARTY_GROUPS) if caucus else ()

    def keep(row: MemberExpenditure) -> bool:
        if name and _fold(name) not in _fold(row.name):
            return False
        if constituency and _fold(constituency) not in _fold(row.constituency):
            return False
        return not caucus_needles or any(n in _fold(row.caucus) for n in caucus_needles)

    return [row for row in rows if keep(row)]


async def get_member_expenditures(
    fiscal_year: int | None = None,
    quarter: int | None = None,
    name: str | None = None,
    constituency: str | None = None,
    caucus: str | None = None,
    sort_by: str = "total",
    limit: int = constants.EXPENDITURES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> MemberExpenditures:
    _check_lang(lang)
    _check_limit(limit, lang)
    if sort_by not in SORT_KEYS:
        raise lang_error(
            InvalidInput,
            lang,
            f"ourcommons: sort_by must be one of {', '.join(SORT_KEYS)}.",
            f"ourcommons : sort_by doit être l'une des valeurs {', '.join(SORT_KEYS)}.",
        )
    fiscal_year, quarter, url, report_id, _ = await _quarter(fiscal_year, quarter, lang)
    rows = await _summary(report_id, lang)
    matches = _filter(rows, name, constituency, caucus)
    if sort_by == "name":
        matches.sort(key=lambda r: _fold(r.name))
    else:
        # Blank amounts sort last, never as zero.
        matches.sort(
            key=lambda r: (getattr(r, sort_by) is not None, getattr(r, sort_by) or 0.0),
            reverse=True,
        )
    start, end = period(fiscal_year, quarter)
    return MemberExpenditures(
        fiscal_year=fiscal_year,
        quarter=quarter,
        period_start=start,
        period_end=end,
        members_in_report=len(rows),
        total_matches=len(matches),
        totals=ExpenditureTotals(
            salaries=_present_sum([r.salaries for r in matches]),
            travel=_present_sum([r.travel for r in matches]),
            hospitality=_present_sum([r.hospitality for r in matches]),
            contracts=_present_sum([r.contracts for r in matches]),
            total=_present_sum([r.total for r in matches]),
        ),
        members=matches[:limit],
        provenance=_provenance(
            f"{constants.DISCLOSURE_URL.format(lang=lang)}/{report_id}/csv",
            "ourcommons.MemberExpenditures",
            lang,
            coverage=fr_or_en(
                lang,
                f"Members' Expenditures Report, {start} to {end} ({url}).",
                f"Rapport sur les dépenses des députés, du {start} au {end} ({url}).",
            ),
        ),
    )


def _detail_rows(text: str) -> list[list[str]]:
    # A title line, then the header, then the lines.
    return [row for row in list(csv.reader(text.splitlines()))[2:] if any(c.strip() for c in row)]


async def get_member_expenditure_details(
    name: str,
    constituency: str | None = None,
    fiscal_year: int | None = None,
    quarter: int | None = None,
    categories: list[str] | None = None,
    lang: Lang = "en",
) -> MemberExpenditureDetails:
    _check_lang(lang)
    wanted = categories or list(CATEGORIES)
    unknown = [c for c in wanted if c not in CATEGORIES]
    if unknown:
        raise lang_error(
            InvalidInput,
            lang,
            f"ourcommons: categories must be among {', '.join(CATEGORIES)}; got {unknown}.",
            f"ourcommons : categories doit être parmi {', '.join(CATEGORIES)} ; reçu {unknown}.",
        )
    fiscal_year, quarter, url, report_id, member_ids = await _quarter(fiscal_year, quarter, lang)
    rows = _filter(await _summary(report_id, lang), name, constituency, None)
    if len(rows) != 1:
        found = "; ".join(f"{r.name} ({r.constituency})" for r in rows[:15])
        raise lang_error(
            NotFound if not rows else InvalidInput,
            lang,
            f"ourcommons: {len(rows)} members match name {name!r} in this report"
            + (f": {found}. Narrow with constituency." if rows else "."),
            f"ourcommons : {len(rows)} députés correspondent au nom {name!r} dans ce rapport"
            + (f" : {found}. Précisez avec constituency." if rows else "."),
        )
    member = rows[0]
    member_id = member_ids.get(_key(member.name, member.constituency))
    base = constants.DISCLOSURE_URL.format(lang=lang)
    paths = constants.DETAIL_PATHS[lang]

    async def detail(kind: str) -> list[list[str]]:
        # A member with nothing in any category has no link, so no id: no lines.
        if not member_id:
            return []
        csv_url = f"{base}/{paths[kind]}/{report_id}/{member_id}/csv"
        return _detail_rows(await _get(csv_url, lang, f"{kind} details", f"détail {kind}"))

    travel = hospitality = contracts = None
    if "travel" in wanted:
        travel = [
            TravelLine(
                start_date=_date(r[0]),
                end_date=_date(r[1]),
                departure=r[2],
                places_visited=r[3],
                purpose=r[4],
                traveller_name=r[5].strip() or None,
                traveller_type=r[6],
                transportation=_amount(r[7]),
                accommodation=_amount(r[8]),
                meals_and_incidentals=_amount(r[9]),
                total=_amount(r[10]),
            )
            for r in await detail("travel")
            if len(r) >= 11
        ]
    if "hospitality" in wanted:
        hospitality = [
            HospitalityLine(
                event_date=_date(r[0]),
                location=r[1],
                attendees=int(r[2]) if r[2].strip().isdigit() else None,
                purpose=r[3],
                supplier=r[4],
                amount=_amount(r[5]),
                event_total=_amount(r[6]),
            )
            for r in await detail("hospitality")
            if len(r) >= 7
        ]
    if "contract" in wanted:
        contracts = [
            ContractLine(
                supplier=r[0], description=r[1], contract_date=_date(r[2]), total=_amount(r[3])
            )
            for r in await detail("contract")
            if len(r) >= 4
        ]
    start, end = period(fiscal_year, quarter)
    return MemberExpenditureDetails(
        name=member.name,
        constituency=member.constituency,
        caucus=member.caucus,
        fiscal_year=fiscal_year,
        quarter=quarter,
        period_start=start,
        period_end=end,
        travel_total=member.travel,
        hospitality_total=member.hospitality,
        contracts_total=member.contracts,
        travel=travel,
        hospitality=hospitality,
        contracts=contracts,
        provenance=_provenance(
            url,
            "ourcommons.MemberExpenditureDetails",
            lang,
            coverage=fr_or_en(
                lang,
                f"{member.name}, {start} to {end}. Travel lines can predate the quarter (late "
                "claims) or be negative (corrections).",
                f"{member.name}, du {start} au {end}. Des déplacements peuvent précéder le "
                "trimestre (demandes tardives) ou être négatifs (corrections).",
            ),
        ),
    )

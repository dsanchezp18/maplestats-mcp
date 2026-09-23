"""Client for EPCOR Edmonton water quality pages. See the module
docstring for the page structures and naming quirks confirmed live.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from maple_data_mcp.modules.epcor import constants
from maple_data_mcp.modules.epcor.schemas import (
    DailyReading,
    DailyWaterQuality,
    Plant,
    System,
    WaterQualityReport,
    WaterQualityReportList,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SPAN_RE = re.compile(r'<span id="([A-Za-z]+?)Label(\d+)">([^<]*)</span>')
_MONTHS = {
    name: number
    for number, name in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
_REPORT_LINK_RE = re.compile(r'/content/dam/epcor/documents/water-quality-reports/[^"&\s]+?\.pdf')
# Accepts both the underscore (to mid-2025) and hyphen (after) naming,
# and the doubled dot in at least one real file name.
_REPORT_NAME_RE = re.compile(
    r"^(?:(?P<year>\d{4})(?:-(?P<month>\d{2}))?|(?P<bare_month>\d{2}))[-_]edmonton[-_]"
    r"(?P<system>wastewater|water)[-_]quality[-_](?P<kind>.+?)\.+pdf$"
)


async def _get_text(url: str, context: str, params: dict[str, str] | None = None) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, params=params)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"epcor:{context} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"epcor:{context} did not respond in time.") from exc
    return response.text


def _to_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        # "--" marks a missing reading (confirmed live).
        return None


def infer_label_date(label: str, today: date) -> date | None:
    """Turn a year-less label like "SEP-15" into a date no later than today."""
    match = re.fullmatch(r"([A-Z]{3})-(\d{1,2})", label.strip().upper())
    if not match or match.group(1) not in _MONTHS:
        return None
    month, day = _MONTHS[match.group(1)], int(match.group(2))
    year = today.year if (month, day) <= (today.month, today.day) else today.year - 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_daily_page(page: str, today: date) -> list[DailyReading]:
    values: dict[str, dict[int, str]] = {}
    for prefix, index, value in _SPAN_RE.findall(page):
        values.setdefault(prefix, {})[int(index)] = html.unescape(value).strip()
    labels = values.get("Date", {})
    if not labels:
        raise UpstreamError("epcor:daily_water_quality page no longer has DateLabel spans.")
    readings = []
    for index in sorted(labels):
        measures = {
            field: _to_float(values.get(prefix, {}).get(index, ""))
            for prefix, (field, _unit) in constants.MEASURES.items()
        }
        readings.append(
            DailyReading(
                date=infer_label_date(labels[index], today),
                date_label=labels[index],
                **measures,
            )
        )
    return readings


async def get_daily_water_quality(plant: Plant = "els", *, lang: str = "en") -> DailyWaterQuality:
    """Last 7 days of daily-average treated-water readings for one plant."""
    del lang
    if plant not in constants.PLANTS:
        raise InvalidInput(f"plant must be one of {sorted(constants.PLANTS)}, got {plant!r}.")
    params = {"zone": constants.PLANTS[plant]}

    async def fetch() -> str:
        return await _get_text(constants.DAILY_URL, "daily_water_quality", params)

    page, was_cached = await cached_fetch(
        f"epcor:daily:{plant}", constants.CACHE_TTL_DAILY_SECONDS, fetch
    )
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    return DailyWaterQuality(
        plant=plant,
        plant_name=constants.PLANT_NAMES[plant],
        units={field: unit for field, unit in constants.MEASURES.values()},
        readings=parse_daily_page(page, today),
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.DAILY_URL}?zone={params['zone']}",
            cached=was_cached,
            schema_name="epcor.DailyWaterQuality",
            freshness="daily averages, last 7 days; unvalidated monitoring data",
            limits="values leave the treatment plant; tap values can differ",
        ),
    )


def parse_report_links(page: str) -> list[WaterQualityReport]:
    reports: list[WaterQualityReport] = []
    for path in sorted(set(_REPORT_LINK_RE.findall(page))):
        file_name = path.rsplit("/", 1)[1]
        match = _REPORT_NAME_RE.match(file_name)
        if not match:
            continue
        year = match.group("year")
        month = match.group("month") or match.group("bare_month")
        system: System = "wastewater" if match.group("system") == "wastewater" else "water"
        reports.append(
            WaterQualityReport(
                year=int(year) if year else None,
                month=int(month) if month else None,
                system=system,
                kind=match.group("kind").replace("_", "-"),
                file_name=file_name,
                url=f"{constants.REPORTS_BASE_URL}{path}",
            )
        )
    return reports


async def list_water_quality_reports(
    year: int | None = None,
    month: int | None = None,
    system: System | None = None,
    kind: str | None = None,
    *,
    lang: str = "en",
) -> WaterQualityReportList:
    """List EPCOR Edmonton water-quality report PDFs, newest first."""
    del lang
    if month is not None and not 1 <= month <= 12:
        raise InvalidInput(f"month must be between 1 and 12, got {month}.")

    async def fetch() -> str:
        return await _get_text(constants.REPORTS_PAGE_URL, "water_quality_reports")

    page, was_cached = await cached_fetch(
        "epcor:reports", constants.CACHE_TTL_REPORTS_SECONDS, fetch
    )
    all_reports = parse_report_links(page)
    if not all_reports:
        raise UpstreamError("epcor:water_quality_reports page no longer lists report PDFs.")
    matches = [
        report
        for report in all_reports
        if (year is None or report.year == year)
        and (month is None or report.month == month)
        and (system is None or report.system == system)
        and (kind is None or report.kind == kind)
    ]
    matches.sort(key=lambda r: (r.year or 0, r.month or 0, r.system, r.kind), reverse=True)
    return WaterQualityReportList(
        total_matches=len(matches),
        kinds_available=sorted({report.kind for report in all_reports}),
        reports=matches,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=constants.REPORTS_PAGE_URL,
            cached=was_cached,
            schema_name="epcor.WaterQualityReportList",
            limits="links only; the reports themselves are PDFs",
        ),
    )

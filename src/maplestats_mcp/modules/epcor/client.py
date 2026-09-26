"""Client for EPCOR Edmonton water quality pages. See the module
docstring for the page structures and naming quirks confirmed live.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.epcor import constants
from maplestats_mcp.modules.epcor.schemas import (
    DailyReading,
    DailyWaterQuality,
    Plant,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

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

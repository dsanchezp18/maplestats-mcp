"""Client for EPCOR Edmonton water quality pages. See the module
docstring for the page structures and naming quirks confirmed live.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.epcor import constants
from maplestats_mcp.modules.epcor.schemas import (
    DailyReading,
    DailyWaterQuality,
    Plant,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
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


async def _get_text(
    url: str, context: str, params: dict[str, str] | None = None, *, lang: str = "en"
) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, params=params)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # get_raw already retried 429/5xx three times; what is left is an outage,
        # not a changed page. Mapping it to UpstreamError told callers the page
        # had changed shape (found 2026-10-03 by a mocked 503 test; errors.py
        # and statcan/census_profile treat 429/5xx as UpstreamUnavailable).
        if status == 429 or status >= 500:
            raise_localized(
                UpstreamUnavailable,
                f"epcor:{context} failed with HTTP {status} after retries. Try again shortly.",
                f"epcor:{context} a échoué avec le code HTTP {status} malgré les nouvelles "
                "tentatives. Réessayez dans un instant.",
                lang,
            )
        raise_localized(
            UpstreamError,
            f"epcor:{context} returned HTTP {status}.",
            f"epcor:{context} a renvoyé le code HTTP {status}.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"epcor:{context} did not respond in time.",
            f"epcor:{context} n'a pas répondu à temps.",
            lang,
        )
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


def parse_daily_page(page: str, today: date, *, lang: str = "en") -> list[DailyReading]:
    values: dict[str, dict[int, str]] = {}
    for prefix, index, value in _SPAN_RE.findall(page):
        values.setdefault(prefix, {})[int(index)] = html.unescape(value).strip()
    labels = values.get("Date", {})
    if not labels:
        raise_localized(
            UpstreamError,
            "epcor:daily_water_quality page no longer has DateLabel spans.",
            "la page epcor:daily_water_quality ne contient plus d'éléments DateLabel.",
            lang,
        )
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
    if plant not in constants.PLANTS:
        raise_localized(
            InvalidInput,
            f"plant must be one of {sorted(constants.PLANTS)}, got {plant!r}.",
            f"plant doit être l'une des valeurs {sorted(constants.PLANTS)} ; reçu {plant!r}.",
            lang,
        )
    params = {"zone": constants.PLANTS[plant]}
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()

    async def fetch() -> str:
        page = await _get_text(constants.DAILY_URL, "daily_water_quality", params, lang=lang)
        # Parse before caching so a 200 error or maintenance page raises here and
        # is not cached for an hour (confirmed 2026-10-03 with a mocked error page:
        # every call kept failing after the page recovered).
        parse_daily_page(page, today, lang=lang)
        return page

    page, was_cached = await cached_fetch(
        f"epcor:daily:{plant}", constants.CACHE_TTL_DAILY_SECONDS, fetch
    )
    readings = parse_daily_page(page, today, lang=lang)
    # The newest day the page reports (OCT-02 on 2026-10-03), at local midnight.
    days = [r.date for r in readings if r.date is not None]
    as_of = (
        datetime.combine(max(days), time(), tzinfo=ZoneInfo(constants.TIMEZONE)) if days else None
    )
    return DailyWaterQuality(
        plant=plant,
        plant_name=constants.PLANT_NAMES[plant],
        units={
            field: pick(lang, unit, constants.UNITS_FR.get(unit, unit))
            for field, unit in constants.MEASURES.values()
        },
        readings=readings,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=f"{constants.DAILY_URL}?zone={params['zone']}",
            cached=was_cached,
            schema_name="epcor.DailyWaterQuality",
            as_of=as_of,
            freshness=pick(
                lang,
                "daily averages, last 7 days; unvalidated monitoring data",
                "moyennes quotidiennes des 7 derniers jours ; données de surveillance non validées",
            ),
            limits=pick(
                lang,
                "values leave the treatment plant; tap values can differ",
                "valeurs mesurées à la sortie de l'usine de traitement ; les valeurs au "
                "robinet peuvent différer",
            ),
            lang=lang,
        ),
    )

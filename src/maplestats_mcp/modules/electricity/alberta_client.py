"""Client for Alberta electricity data from the AESO's public ETS reports.

The Alberta Electric System Operator publishes its market reports on the
Energy Trading System site (ets.aeso.ca) without a key. Confirmed live
2026-11-08:

- `HistoricalPoolPriceReportServlet?beginDate=MMDDYYYY&endDate=MMDDYYYY&
  contentType=csv`: hourly pool price, AESO's 30-day rolling average and
  Alberta Internal Load (AIL), one row per hour ending (`"11/01/2026 01"`).
  The autumn daylight-saving day has a second hour 02 written `"02*"` (seen
  in 2025-11-02); the spring day skips HE 02. Hours not yet settled are rows
  of `"-"`. endDate is exclusive (unlike the daily report's), at most 721
  days per request; the oldest row is 1999-01-01.
- `DailyAveragePoolPriceReportServlet` (same parameters): daily, on-peak and
  off-peak averages and their 30-day rolling averages, newest day first, at
  most 31 days per request.
- Both servlets answer a bad range with HTTP 200 and an HTML page
  `<h2>Validation Error</h2>...`, not an error status.
- `Market/Reports/Manual/PoolMonthlySummary/PMS_MM01YYYY.html`: one HTML page
  per month (HTTP 404 until AESO prepares it, early the next month). From
  about 2009 the page has a "Monthly Statistics" table (price minimum,
  average, maximum and demand-weighted average, AIL minimum, average and
  maximum, total energy in GWh, load factor) and a summary sentence with the
  on-peak and off-peak averages; older pages have a daily table ending in a
  "Monthly Value" row (price minimum, maximum, average, from about 2008 a
  demand-weighted average, then demand minimum, maximum, average, and energy
  in MWh).
- `CSDReportServlet`: the Current Supply Demand report (HTML; a CSV variant
  exists but drops the names of the hydro, storage, solar, wind and other
  asset sections). Summary lines (total net generation, net actual
  interchange, AIL, reserves), generation by fuel group (maximum capability,
  total net generation, dispatched contingency reserve), flows on the BC,
  Montana and Saskatchewan paths, and every asset. Refreshed about every two
  minutes. On live reads AIL equalled total net generation minus net actual
  interchange, so a positive interchange is a net export.
- ets.aeso.ca serves plain HTTP only (HTTPS fails the TLS handshake). There
  is no robots.txt on ets.aeso.ca or www.aeso.ca (both HTTP 404).

AESO's newer API (api.aeso.ca) needs a subscription key and is not used.

Terms: www.aeso.ca/legal/ (the ETS site's legal notice links there) allows
the material to be "used and copied for non-commercial, personal or
educational purposes, provided that the material is not modified and that
copyright notices are not deleted". Values are passed through as published,
nothing here is recomputed from them except the legacy monthly energy total
(MWh to GWh), and every result repeats the terms and a commercial-use notice.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.electricity import constants
from maplestats_mcp.modules.electricity.client import _check_limit, _error, _parse_date, _say
from maplestats_mcp.modules.electricity.schemas import (
    AlbertaAsset,
    AlbertaDailyPrice,
    AlbertaDailyPrices,
    AlbertaFuelGroup,
    AlbertaInterchange,
    AlbertaMonth,
    AlbertaMonthlySummary,
    AlbertaPoolPrice,
    AlbertaPoolPriceHour,
    AlbertaSupplyDemand,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.licences import AESO_TERMS
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    "electricity:aeso",
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TZ = ZoneInfo(constants.AESO_TIMEZONE)
_FIRST_DATE = date.fromisoformat(constants.AESO_FIRST_DATE)

NOTICE_EN = (
    "AESO terms allow non-commercial use only: commercial use needs the AESO's written "
    "permission (https://www.aeso.ca/legal/)."
)
NOTICE_FR = (
    "Les conditions de l'AESO permettent seulement un usage non commercial : un usage "
    "commercial exige l'autorisation écrite de l'AESO (https://www.aeso.ca/legal/)."
)


def alberta_today() -> date:
    """Today in Alberta (Mountain time), the clock AESO's reports use."""
    return datetime.now(_TZ).date()


def _notice(lang: str) -> str:
    return NOTICE_FR if lang == "fr" else NOTICE_EN


def _provenance(
    url: str, cached: bool, schema: str, freshness: str, limits: str | None, lang: str
) -> Provenance:
    return make_provenance(
        source=constants.SOURCE,
        url=url,
        cached=cached,
        schema_name=f"electricity.{schema}",
        freshness=freshness,
        coverage=_say(
            "Alberta (AESO-operated grid) only",
            "Alberta seulement (réseau exploité par l'AESO)",
            lang,
        ),
        licence=AESO_TERMS,
        commercial_use="not_allowed",  # non-commercial, personal or educational use only
        limits=limits,
        lang=lang,
    )


async def _get_text(url: str, params: dict[str, Any] | None, context: str, lang: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise _error(
                NotFound,
                f"electricity:{context}: AESO has no report at {url}.",
                f"electricity:{context} : l'AESO n'a pas de rapport à {url}.",
                lang,
            ) from exc
        raise _error(
            UpstreamError,
            f"electricity:{context}: AESO returned HTTP {status}.",
            f"electricity:{context} : l'AESO a renvoyé HTTP {status}.",
            lang,
        ) from exc
    except httpx.HTTPError as exc:
        raise _error(
            UpstreamUnavailable,
            f"electricity:{context}: AESO did not respond in time.",
            f"electricity:{context} : l'AESO n'a pas répondu à temps.",
            lang,
        ) from exc
    text = response.text
    # The servlets report a rejected range as HTTP 200 with an HTML page.
    if "Validation Error" in text[:500]:
        reason = re.sub(r"<[^>]+>", " ", text).replace("Validation Error", "")
        reason = " ".join(reason.split())
        raise _error(
            InvalidInput,
            f"electricity:{context}: AESO rejected the request: {reason}",
            f"electricity:{context} : l'AESO a refusé la requête : {reason}",
            lang,
        )
    return text


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.replace("$", "").replace(",", "").replace("%", "").strip()
    if text in {"", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _mmddyyyy(day: date) -> str:
    return day.strftime("%m%d%Y")


def _csv_rows(text: str) -> list[list[str]]:
    return [row for row in csv.reader(text.splitlines()) if row]


def _check_range(start: date, end: date, max_days: int, lang: str) -> None:
    if end < start:
        raise _error(
            InvalidInput,
            f"end_date {end} is before start_date {start}.",
            f"end_date {end} précède start_date {start}.",
            lang,
        )
    if start < _FIRST_DATE:
        raise _error(
            InvalidInput,
            f"AESO pool prices start {_FIRST_DATE}; got start_date {start}.",
            f"Les prix du pool de l'AESO commencent le {_FIRST_DATE} ; reçu start_date {start}.",
            lang,
        )
    if (end - start).days + 1 > max_days:
        raise _error(
            InvalidInput,
            f"At most {max_days} days per call; got {(end - start).days + 1}.",
            f"Au plus {max_days} jours par appel ; reçu {(end - start).days + 1}.",
            lang,
        )


def _ttl(end: date) -> int:
    recent = end >= alberta_today() - timedelta(days=1)
    return constants.CACHE_TTL_LATEST_SECONDS if recent else constants.CACHE_TTL_ARCHIVE_SECONDS


# ------------------------------------------------------------ hourly price


def parse_pool_price_csv(text: str) -> list[AlbertaPoolPriceHour]:
    """Rows of the hourly pool price CSV, unpublished hours included (values None)."""
    hours: list[AlbertaPoolPriceHour] = []
    for row in _csv_rows(text):
        match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4}) (\d{2})(\*?)", row[0].strip())
        if match is None or len(row) < 4:
            continue
        month, day, year, hour, star = match.groups()
        hours.append(
            AlbertaPoolPriceHour(
                date=date(int(year), int(month), int(day)),
                hour_ending=int(hour),
                repeated_hour=star == "*",
                pool_price=_number(row[1]),
                rolling_30day_average=_number(row[2]),
                ail_demand_mw=_number(row[3]),
            )
        )
    return hours


async def get_pool_price(
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.DEFAULT_LIMIT,
    *,
    lang: str = "en",
) -> AlbertaPoolPrice:
    _check_limit(limit, lang)
    start = _parse_date(start_date, "start_date", lang)
    end = _parse_date(end_date, "end_date", lang)
    today = alberta_today()
    # With no start the window below is invented to finish at `end` (or today),
    # so the rows wanted are its last `limit`, not its first.
    newest = start is None
    if end is None:
        end = today if start is None else min(today, start + timedelta(days=1))
    if start is None:
        # Enough days for `limit` published hours, plus today's unsettled ones.
        start = end - timedelta(days=-(-limit // 24))
    # The servlet's endDate is exclusive (11/01 to 11/02 returns 11/01 only; the
    # same date twice returns that day), so ask for the day after `end`; a
    # 721-day request then covers 720 days.
    _check_range(start, end, constants.AESO_HOURLY_MAX_DAYS - 1, lang)
    url = f"{constants.AESO_REPORTS_URL}/HistoricalPoolPriceReportServlet"
    params = {
        "beginDate": _mmddyyyy(start),
        "endDate": _mmddyyyy(end + timedelta(days=1)),
        "contentType": "csv",
    }

    async def fetch() -> list[AlbertaPoolPriceHour]:
        return parse_pool_price_csv(await _get_text(url, params, "alberta_pool_price", lang))

    hours, was_cached = await cached_fetch(f"electricity:aeso:pool:{start}:{end}", _ttl(end), fetch)
    hours = [h for h in hours if start <= h.date <= end]
    published = [h for h in hours if h.pool_price is not None]
    pending = sum(
        1
        for h in hours
        if h.pool_price is None and h.rolling_30day_average is None and h.ail_demand_mw is None
    )
    shown = published[-limit:] if newest else published[:limit]
    last = published[-1] if published else None
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return AlbertaPoolPrice(
        start_date=start,
        end_date=end,
        rows=shown,
        rows_matched=len(published),
        hours_not_yet_published=pending,
        latest_published_date=last.date if last else None,
        latest_published_hour_ending=last.hour_ending if last else None,
        commercial_use_notice=_notice(lang),
        provenance=_provenance(
            f"{url}?{query}",
            was_cached,
            "AlbertaPoolPrice",
            _say(
                "settled hour by hour; the latest hours of today appear as they settle",
                "réglé heure par heure ; les dernières heures du jour s'ajoutent à mesure",
                lang,
            ),
            _say(
                f"Rows capped at {limit}; {len(published)} published hours matched. Hours are "
                "hour ending in Alberta clock time (Mountain, with daylight saving). Values are "
                f"AESO's, unmodified. {NOTICE_EN}",
                f"Lignes plafonnées à {limit} ; {len(published)} heures publiées correspondent. "
                "Les heures sont des heures de fin, heure de l'Alberta (Rocheuses, avec heure "
                f"avancée). Valeurs de l'AESO, non modifiées. {NOTICE_FR}",
                lang,
            ),
            lang,
        ),
    )


# ------------------------------------------------------------- daily price


def parse_daily_csv(text: str) -> list[AlbertaDailyPrice]:
    """Rows of the daily average pool price CSV (any order)."""
    days: list[AlbertaDailyPrice] = []
    for row in _csv_rows(text):
        match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", row[0].strip())
        if match is None or len(row) < 7:
            continue
        month, day, year = match.groups()
        values = [_number(cell) for cell in row[1:7]]
        days.append(
            AlbertaDailyPrice(
                date=date(int(year), int(month), int(day)),
                average=values[0],
                on_peak_average=values[1],
                off_peak_average=values[2],
                rolling_30day_average=values[3],
                rolling_30day_on_peak_average=values[4],
                rolling_30day_off_peak_average=values[5],
            )
        )
    return days


async def get_daily_prices(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    lang: str = "en",
) -> AlbertaDailyPrices:
    start = _parse_date(start_date, "start_date", lang)
    end = _parse_date(end_date, "end_date", lang)
    if end is None:
        today = alberta_today()
        end = today if start is None else min(today, start + timedelta(days=30))
    if start is None:
        start = end - timedelta(days=constants.AESO_DAILY_MAX_DAYS - 1)
    _check_range(start, end, constants.AESO_DAILY_SPAN_DAYS, lang)
    url = f"{constants.AESO_REPORTS_URL}/DailyAveragePoolPriceReportServlet"

    # AESO serves at most 31 days per request, so a longer range is fetched in chunks.
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=constants.AESO_DAILY_MAX_DAYS - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    by_date: dict[date, AlbertaDailyPrice] = {}
    all_cached = True
    for first, last in chunks:
        params = {"beginDate": _mmddyyyy(first), "endDate": _mmddyyyy(last), "contentType": "csv"}

        async def fetch(params: dict[str, str] = params) -> list[AlbertaDailyPrice]:
            return parse_daily_csv(await _get_text(url, params, "alberta_daily_prices", lang))

        rows, was_cached = await cached_fetch(
            f"electricity:aeso:daily:{first}:{last}", _ttl(last), fetch
        )
        all_cached = all_cached and was_cached
        for row in rows:
            if first <= row.date <= last:
                by_date[row.date] = row
    days = [by_date[d] for d in sorted(by_date)]
    first_query = f"beginDate={_mmddyyyy(chunks[0][0])}&endDate={_mmddyyyy(chunks[0][1])}"
    return AlbertaDailyPrices(
        start_date=start,
        end_date=end,
        days=days,
        requests_made=len(chunks),
        commercial_use_notice=_notice(lang),
        provenance=_provenance(
            f"{url}?{first_query}&contentType=csv",
            all_cached,
            "AlbertaDailyPrices",
            _say(
                "daily; today's averages cover the hours settled so far",
                "quotidien ; les moyennes du jour couvrent les heures déjà réglées",
                lang,
            ),
            _say(
                "On-peak is HE 08-23 and off-peak the other hours, Alberta time. Averages are "
                f"AESO's, unmodified; the URL shows the first of {len(chunks)} 31-day requests. "
                f"{NOTICE_EN}",
                "Les heures de pointe sont HE 08 à 23 et les heures creuses les autres, heure de "
                "l'Alberta. Moyennes de l'AESO, non modifiées ; l'URL montre la première de "
                f"{len(chunks)} requêtes de 31 jours. {NOTICE_FR}",
                lang,
            ),
            lang,
        ),
    )


# -------------------------------------------------------- HTML table rows


class _RowParser(HTMLParser):
    """Text of each table row's cells, innermost tables first.

    The AESO pages nest tables; a stack keeps an outer row's cells from
    absorbing the text of the rows inside it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._stack: list[tuple[list[str], list[str] | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._stack.append(([], None))
        elif tag in {"td", "th"} and self._stack:
            cells, _ = self._stack[-1]
            self._stack[-1] = (cells, [])

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._stack:
            cells, buffer = self._stack[-1]
            if buffer is not None:
                cells.append(" ".join("".join(buffer).replace("\xa0", " ").split()))
            self._stack[-1] = (cells, None)
        elif tag == "tr" and self._stack:
            cells, buffer = self._stack.pop()
            if buffer is not None:
                cells.append(" ".join("".join(buffer).replace("\xa0", " ").split()))
            kept = [cell for cell in cells if cell]
            if kept:
                self.rows.append(kept)

    def handle_data(self, data: str) -> None:
        if self._stack:
            _, buffer = self._stack[-1]
            if buffer is not None:
                buffer.append(data)


def table_rows(text: str) -> list[list[str]]:
    parser = _RowParser()
    parser.feed(text)
    parser.close()
    return parser.rows


# ---------------------------------------------------------- monthly summary


def _month(value: str | None, name: str, lang: str) -> date | None:
    if value is None or not value.strip():
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if match is None or not 1 <= int(match.group(2)) <= 12:
        raise _error(
            InvalidInput,
            f"{name} must be YYYY-MM, got {value!r}.",
            f"{name} doit être AAAA-MM, reçu {value!r}.",
            lang,
        )
    return date(int(match.group(1)), int(match.group(2)), 1)


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _monthly_url(month: date) -> str:
    return f"{constants.AESO_MONTHLY_URL}/PMS_{month.month:02d}01{month.year}.html"


def parse_monthly_html(text: str, month: date) -> AlbertaMonth | None:
    """The month's statistics from a Pool Monthly Summary page, or None if not found."""
    rows = table_rows(text)
    url = _monthly_url(month)
    key = f"{month.year}-{month.month:02d}"
    for index, row in enumerate(rows):
        if row and row[-1] == "Load Factor" and index + 1 < len(rows):
            values = [_number(cell) for cell in rows[index + 1]]
            if len(values) < 9:
                continue
            plain = " ".join(" ".join(r) for r in rows[:index])
            on_peak = re.search(r"on peak pool price averaged \$([\d,.]+)", plain, re.IGNORECASE)
            off_peak = re.search(r"off peak pool price averaged \$([\d,.]+)", plain, re.IGNORECASE)
            return AlbertaMonth(
                month=key,
                layout="monthly_statistics",
                pool_price_minimum=values[0],
                pool_price_average=values[1],
                pool_price_maximum=values[2],
                pool_price_weighted_average=values[3],
                on_peak_average=_number(on_peak.group(1).rstrip(".")) if on_peak else None,
                off_peak_average=_number(off_peak.group(1).rstrip(".")) if off_peak else None,
                ail_minimum_mw=values[4],
                ail_average_mw=values[5],
                ail_maximum_mw=values[6],
                total_energy_gwh=values[7],
                load_factor_percent=values[8],
                url=url,
            )
    # Legacy pages: Day, price Minimum, Maximum, Average, [Weighted Average #
    # from about 2008], demand Minimum, Maximum, Average, energy (MWh).
    weighted = False
    for row in rows:
        if row and row[0] == "Day":
            weighted = any(cell.startswith("Weighted") for cell in row)
        if row and row[0] == "Monthly Value" and len(row) >= 8 + weighted:
            values = [_number(cell) for cell in row[1 : 9 + weighted]]
            if not weighted:
                values.insert(3, None)
            energy_mwh = values[7]
            return AlbertaMonth(
                month=key,
                layout="legacy_daily_table",
                pool_price_minimum=values[0],
                pool_price_maximum=values[1],
                pool_price_average=values[2],
                pool_price_weighted_average=values[3],
                on_peak_average=None,
                off_peak_average=None,
                ail_minimum_mw=values[4],
                ail_maximum_mw=values[5],
                ail_average_mw=values[6],
                total_energy_gwh=round(energy_mwh / 1000, 3) if energy_mwh is not None else None,
                load_factor_percent=None,
                url=url,
            )
    return None


async def get_monthly_summary(
    start_month: str | None = None,
    end_month: str | None = None,
    *,
    lang: str = "en",
) -> AlbertaMonthlySummary:
    first = _month(start_month, "start_month", lang)
    last = _month(end_month, "end_month", lang)
    this_month = alberta_today().replace(day=1)
    latest_only = first is None and last is None
    if latest_only:
        # The previous month's page appears a few days into the month.
        first = last = _add_months(this_month, -1)
    elif first is None:
        first = last
    elif last is None:
        last = first
    assert first is not None and last is not None
    if last < first:
        raise _error(
            InvalidInput,
            f"end_month {last:%Y-%m} is before start_month {first:%Y-%m}.",
            f"end_month {last:%Y-%m} précède start_month {first:%Y-%m}.",
            lang,
        )
    if first < _FIRST_DATE:
        raise _error(
            InvalidInput,
            f"AESO monthly summaries start {_FIRST_DATE:%Y-%m}; got {first:%Y-%m}.",
            f"Les sommaires mensuels de l'AESO commencent en {_FIRST_DATE:%Y-%m} ; reçu "
            f"{first:%Y-%m}.",
            lang,
        )
    span = (last.year - first.year) * 12 + last.month - first.month + 1
    if span > constants.AESO_MONTHLY_MAX_MONTHS:
        raise _error(
            InvalidInput,
            f"At most {constants.AESO_MONTHLY_MAX_MONTHS} months per call; got {span}.",
            f"Au plus {constants.AESO_MONTHLY_MAX_MONTHS} mois par appel ; reçu {span}.",
            lang,
        )

    async def read(month: date) -> tuple[AlbertaMonth | None, bool]:
        if month >= this_month:
            return None, True

        # A missing page (404) or one that does not parse raises inside the fetch
        # and is caught outside it: a None returned here would be cached for the
        # 6 h archive TTL, and the month would stay "not published" for hours
        # after AESO posts it. Only a parsed month is cached.
        async def fetch() -> AlbertaMonth:
            text = await _get_text(_monthly_url(month), None, "alberta_monthly_summary", lang)
            parsed = parse_monthly_html(text, month)
            if parsed is None:
                raise _error(
                    NotFound,
                    f"electricity:alberta_monthly_summary: no readable summary for {month:%Y-%m}.",
                    f"electricity:alberta_monthly_summary : aucun sommaire lisible pour "
                    f"{month:%Y-%m}.",
                    lang,
                )
            return parsed

        try:
            return await cached_fetch(
                f"electricity:aeso:monthly:{month:%Y-%m}",
                constants.CACHE_TTL_ARCHIVE_SECONDS,
                fetch,
            )
        except NotFound:
            return None, False

    months: list[AlbertaMonth] = []
    missing: list[str] = []
    all_cached = True
    month = first
    while month <= last:
        found, was_cached = await read(month)
        all_cached = all_cached and was_cached
        if found is None:
            missing.append(f"{month:%Y-%m}")
        else:
            months.append(found)
        month = _add_months(month, 1)
    if latest_only and not months:
        # Early in a month the previous month's page may not be ready yet.
        earlier = _add_months(first, -1)
        found, _ = await read(earlier)
        if found is not None:
            months.append(found)
            missing = []
    if not months and not missing:
        raise _error(
            NotFound,
            "No AESO monthly summary found for the requested months.",
            "Aucun sommaire mensuel de l'AESO pour les mois demandés.",
            lang,
        )
    return AlbertaMonthlySummary(
        months=months,
        months_not_published=missing,
        commercial_use_notice=_notice(lang),
        provenance=_provenance(
            months[0].url if months else _monthly_url(first),
            all_cached,
            "AlbertaMonthlySummary",
            _say(
                "monthly; AESO prepares each month's summary early the next month",
                "mensuel ; l'AESO prépare le sommaire de chaque mois au début du mois suivant",
                lang,
            ),
            _say(
                "Values are AESO's Pool Monthly Summary figures, unmodified, except that a "
                "legacy-layout month's energy total is AESO's MWh divided by 1,000. On-peak "
                "and off-peak averages come from AESO's summary sentence. "
                f"{NOTICE_EN}",
                "Valeurs du sommaire mensuel du pool de l'AESO, non modifiées, sauf l'énergie "
                "totale des mois à l'ancienne présentation (MWh de l'AESO divisés par 1 000). "
                "Les moyennes de pointe et hors pointe viennent de la phrase de résumé de "
                f"l'AESO. {NOTICE_FR}",
                lang,
            ),
            lang,
        ),
    )


# ------------------------------------------------------ current supply/demand

_HEADER_CELLS = {"GROUP", "PATH", "ASSET", "TOTAL"}
_SECTIONS = {"SUMMARY", "GENERATION", "INTERCHANGE"}


def _snake(label: str) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", label.lower()).split())


def parse_supply_demand_html(text: str) -> dict[str, Any]:
    """Pieces of the Current Supply Demand page as plain values."""
    summary: dict[str, float | None] = {}
    fuels: list[AlbertaFuelGroup] = []
    paths: list[AlbertaInterchange] = []
    assets: list[AlbertaAsset] = []
    last_update: str | None = None
    section: str | None = None
    top: str | None = None
    group: str | None = None
    for cells in table_rows(text):
        first = cells[0]
        if len(cells) == 1:
            if first.startswith("Last Update"):
                last_update = first.split(":", 1)[1].strip()
            elif first in _SECTIONS:
                section = first
            elif section == "INTERCHANGE" or section == "ASSETS":
                # After the interchange table, single cells name asset sections:
                # upper case for a fuel (GAS, WIND), title case for a gas subgroup.
                section = "ASSETS"
                if first.isupper():
                    top = first.title()
                    group = top
                else:
                    group = f"{top}: {first}" if top else first
            continue
        if first in _HEADER_CELLS:
            continue
        if section == "SUMMARY" and len(cells) == 2:
            summary[first] = _number(cells[1])
        elif section == "GENERATION" and len(cells) >= 4:
            values = [_number(cell) for cell in cells[1:4]]
            fuels.append(
                AlbertaFuelGroup(
                    fuel=first,
                    maximum_capability_mw=values[0],
                    total_net_generation_mw=values[1],
                    dispatched_contingency_reserve_mw=values[2],
                )
            )
        elif section == "INTERCHANGE" and len(cells) == 2:
            paths.append(AlbertaInterchange(path=first, actual_flow_mw=_number(cells[1])))
        elif section == "ASSETS" and group and len(cells) >= 4:
            values = [_number(cell) for cell in cells[1:4]]
            marks = re.search(r"[*^]+$", first)
            name = first[: marks.start()].strip() if marks else first
            assets.append(
                AlbertaAsset(
                    group=group,
                    asset=name,
                    maximum_capability_mw=values[0],
                    total_net_generation_mw=values[1],
                    dispatched_contingency_reserve_mw=values[2],
                    net_to_grid="*" in (marks.group(0) if marks else ""),
                    includes_storage="^" in (marks.group(0) if marks else ""),
                )
            )
    return {
        "last_update": last_update,
        "summary": summary,
        "fuels": fuels,
        "paths": paths,
        "assets": assets,
    }


_MAIN_SUMMARY = {
    "Alberta Internal Load (AIL)": "alberta_internal_load_mw",
    "Alberta Total Net Generation": "total_net_generation_mw",
    "Net Actual Interchange": "net_actual_interchange_mw",
    "Net-To-Grid Generation": "net_to_grid_generation_mw",
}


async def get_supply_demand(
    include_assets: bool = False,
    group: str | None = None,
    *,
    lang: str = "en",
) -> AlbertaSupplyDemand:
    url = f"{constants.AESO_REPORTS_URL}/CSDReportServlet"

    async def fetch() -> dict[str, Any]:
        parsed = parse_supply_demand_html(await _get_text(url, None, "alberta_supply_demand", lang))
        if not parsed["summary"] or not parsed["fuels"]:
            raise _error(
                UpstreamError,
                "electricity:alberta_supply_demand: the AESO page had no summary table.",
                "electricity:alberta_supply_demand : la page de l'AESO n'avait pas de sommaire.",
                lang,
            )
        return parsed

    parsed, was_cached = await cached_fetch(
        "electricity:aeso:csd", constants.AESO_CACHE_TTL_CURRENT_SECONDS, fetch
    )
    summary: dict[str, float | None] = parsed["summary"]
    main = {field: summary.get(label) for label, field in _MAIN_SUMMARY.items()}
    others = {_snake(k) + "_mw": v for k, v in summary.items() if k not in _MAIN_SUMMARY}
    assets: list[AlbertaAsset] = parsed["assets"] if include_assets else []
    if include_assets and group:
        wanted = group.strip().lower()
        assets = [a for a in assets if wanted in a.group.lower()]
    groups = sorted({a.group for a in parsed["assets"]})
    return AlbertaSupplyDemand(
        last_update=parsed["last_update"],
        alberta_internal_load_mw=main["alberta_internal_load_mw"],
        total_net_generation_mw=main["total_net_generation_mw"],
        net_actual_interchange_mw=main["net_actual_interchange_mw"],
        net_to_grid_generation_mw=main["net_to_grid_generation_mw"],
        other_measures_mw=others,
        generation_by_fuel=parsed["fuels"],
        interchange=parsed["paths"],
        assets=assets,
        commercial_use_notice=_notice(lang),
        provenance=_provenance(
            url,
            was_cached,
            "AlbertaSupplyDemand",
            _say(
                "current snapshot, refreshed by AESO about every two minutes",
                "instantané, mis à jour par l'AESO environ toutes les deux minutes",
                lang,
            ),
            _say(
                "MW at the last update; MC is maximum capability, TNG total net generation, "
                "DCR dispatched contingency reserve. A positive interchange is a net export. "
                f"Asset groups: {', '.join(groups)}. Values are AESO's, unmodified. {NOTICE_EN}",
                "MW à la dernière mise à jour ; MC est la capacité maximale, TNG la production "
                "nette totale, DCR la réserve pour éventualités appelée. Un échange positif est "
                f"une exportation nette. Groupes d'actifs : {', '.join(groups)}. Valeurs de "
                f"l'AESO, non modifiées. {NOTICE_FR}",
                lang,
            ),
            lang,
        ),
    )

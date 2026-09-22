"""Client for AER statistical reports (ST1 well licences, ST3 production
volumes). See the module docstring for the two opposite redirect
behaviors this relies on (static.aer.ca bypass for ST1 .TXT files,
real HTTP 303 for ST3 .xlsx/ST1 .zip files).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx

from maple_data_mcp.modules.aer import constants
from maple_data_mcp.modules.aer.schemas import (
    ProductionVolumesLink,
    WellLicenceArchiveLink,
    WellLicenceDailyReport,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, UpstreamUnavailable
from maple_data_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# follow_redirects=True: needed for the real HTTP 303s on ST3 .xlsx and
# ST1 .zip links (see module docstring) -- the ST1 .TXT files instead
# bypass www.aer.ca entirely rather than relying on this.
_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
_HEADERS = {"User-Agent": "maple-data-mcp/0.1"}

_DATE_LINE_RE = re.compile(r"DATE:\s+(\d{1,2}\s+\w+\s+\d{4})")


def _parse_report_date(raw_text: str) -> date | None:
    match = _DATE_LINE_RE.search(raw_text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=UTC).date()
    except ValueError:
        return None


async def get_well_licences_daily(
    day: str | None = None, *, lang: str = "en"
) -> WellLicenceDailyReport:
    """Fetch AER's ST1 "Well Licences Issued - Daily List" for one day of
    the current week. `day` is a weekday name (e.g. "monday"); defaults
    to today in America/Edmonton time, since that is AER's own reporting
    timezone. Returns raw report text -- see the module docstring for
    why this stays a text report rather than a structured parse (each
    licence record spans 5 fixed-width lines with no stable column
    boundaries confirmed safe to split on)."""
    del lang
    if day is None:
        today = datetime.now(ZoneInfo(constants.TIMEZONE))
        day = today.strftime("%A").lower()
    day_key = day.strip().lower()
    if day_key not in constants.DAY_CODES:
        raise InvalidInput(f"day must be one of {sorted(constants.DAY_CODES)}, got {day!r}.")
    day_code = constants.DAY_CODES[day_key]
    url = constants.WELL_LICENCE_DAILY_URL.format(day_code=day_code)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await _client.get(url, headers=_HEADERS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "aer:get_well_licences_daily did not respond in time."
            ) from exc
        return response.text

    cache_key = f"aer:well-licences-daily:{day_key}"
    raw_text, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DAILY_SECONDS, fetch)

    return WellLicenceDailyReport(
        day=day_key,
        report_date=_parse_report_date(raw_text),
        raw_text=raw_text,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceDailyReport",
            freshness="posted nightly by 12:00am MT; each weekday's file is overwritten weekly",
        ),
    )


def _archive_url(year: int, month: int | None) -> str:
    if month is not None:
        if not (1 <= month <= 12):
            raise InvalidInput(f"month must be between 1 and 12, got {month}.")
        return constants.WELL_LICENCE_MONTHLY_ZIP_URL.format(year=year, month=month)
    if year >= constants.WELL_LICENCE_YEARLY_URL_PATH_BOUNDARY_YEAR:
        return constants.WELL_LICENCE_YEARLY_ZIP_URL_NEW.format(year=year)
    return constants.WELL_LICENCE_YEARLY_ZIP_URL_OLD.format(year=year)


async def get_well_licence_archive_link(
    year: int, month: int | None = None, *, lang: str = "en"
) -> WellLicenceArchiveLink:
    """Resolve (and confirm existence of) an AER ST1 well-licence archive
    ZIP. Pass `month` (1-12) for one month of the *current* year (AER
    only publishes monthly ZIPs for the year in progress); omit it for
    a full prior year's ZIP. Discovery-only -- these are large
    fixed-width archives, not parsed here."""
    del lang
    url = _archive_url(year, month)

    async def fetch() -> httpx.Response:
        await _LIMITER.acquire()
        try:
            return await _client.head(url, headers=_HEADERS)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "aer:get_well_licence_archive_link did not respond in time."
            ) from exc

    cache_key = f"aer:well-licence-archive:{year}:{month}"
    response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LINK_SECONDS, fetch)
    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None

    return WellLicenceArchiveLink(
        year=year,
        month=month,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceArchiveLink",
        ),
    )


async def get_production_volumes_link(product: str, *, lang: str = "en") -> ProductionVolumesLink:
    """Resolve (and confirm existence of) AER's ST3 current-month
    production-volume/price XLSX for one product. `product` is one of
    "butane", "ethane", "gas", "ngl", "oil", "propane", "sulphur",
    "oil_prices". Discovery-only -- this project has no pinned
    XLSX-parsing dependency, so the file itself is not parsed here."""
    del lang
    product_key = product.strip().lower()
    if product_key not in constants.PRODUCTION_PRODUCTS:
        raise InvalidInput(
            f"product must be one of {sorted(constants.PRODUCTION_PRODUCTS)}, got {product!r}."
        )
    product_path = constants.PRODUCTION_PRODUCTS[product_key]
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path=product_path)

    async def fetch() -> httpx.Response:
        await _LIMITER.acquire()
        try:
            return await _client.head(url, headers=_HEADERS)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "aer:get_production_volumes_link did not respond in time."
            ) from exc

    cache_key = f"aer:production-volumes:{product_key}"
    response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LINK_SECONDS, fetch)
    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None

    return ProductionVolumesLink(
        product=product_key,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        last_modified=response.headers.get("last-modified"),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.ProductionVolumesLink",
            freshness="ST3 is released monthly, one month in arrears",
        ),
    )

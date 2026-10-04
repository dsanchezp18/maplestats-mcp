"""Client for AER statistical reports (ST1 well licences, ST3 production
volumes). See the module docstring for the two opposite redirect
behaviors this relies on (static.aer.ca bypass for ST1 .TXT files,
real HTTP 303 for ST3 .xlsx/ST1 .zip files).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import NoReturn
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.aer import constants
from maplestats_mcp.modules.aer.schemas import (
    ProductionVolumesLink,
    WellLicenceArchiveLink,
    WellLicenceDailyReport,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# follow_redirects=True: needed for the real HTTP 303s on ST3 .xlsx and
# ST1 .zip links (see module docstring) -- the ST1 .TXT files instead
# bypass www.aer.ca entirely rather than relying on this.
_client = new_client(http2=False, follow_redirects=True)

_DATE_LINE_RE = re.compile(r"DATE:\s+(\d{1,2}\s+\w+\s+\d{4})")

# AER publishes its ST1/ST3 reports in English only, so a French call gets
# the text as is plus this note rather than a silent English answer.
_ENGLISH_ONLY_FR = french_spacing(
    "Les rapports de l'AER n'existent qu'en anglais ; ils sont reproduits tels quels."
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English text unchanged; French goes through the typed-error template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _join_notes(*notes: str | None) -> str | None:
    return " ".join(n for n in notes if n) or None


def _parse_report_date(raw_text: str) -> date | None:
    match = _DATE_LINE_RE.search(raw_text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def _expected_date(day_key: str, today: date) -> date:
    """The most recent date (today or earlier) falling on that weekday."""
    target = list(constants.DAY_CODES).index(day_key)  # sunday = 0
    today_index = (today.weekday() + 1) % 7
    return today - timedelta(days=(today_index - target) % 7)


async def get_well_licences_daily(
    day: str | None = None, *, lang: str = "en"
) -> WellLicenceDailyReport:
    """Fetch AER's ST1 "Well Licences Issued - Daily List" for one weekday.
    `day` is a weekday name (e.g. "monday"); defaults to yesterday in
    America/Edmonton time, AER's own reporting timezone: a day's file is
    posted around midnight after it ends, so before then "today" still
    holds last week's list (live 2026-10-03, a Saturday: the default
    returned the 2026-09-26 list). Each weekday file is overwritten
    weekly; when it still holds an older list than the latest date with
    that weekday, `note` says so. Returns raw report text -- see the
    module docstring for why this stays a text report rather than a
    structured parse (each licence record spans 5 fixed-width lines with
    no stable column boundaries confirmed safe to split on)."""
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    if day is None:
        day = (today - timedelta(days=1)).strftime("%A").lower()
    day_key = day.strip().lower()
    if day_key not in constants.DAY_CODES:
        _raise(
            InvalidInput,
            f"day must be one of {sorted(constants.DAY_CODES)}, got {day!r}.",
            f"day doit être l'un de {sorted(constants.DAY_CODES)} (jours de la semaine en "
            f"anglais), reçu {day!r}.",
            lang,
        )
    expected = _expected_date(day_key, today)
    day_code = constants.DAY_CODES[day_key]
    url = constants.WELL_LICENCE_DAILY_URL.format(day_code=day_code)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await _client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                "aer:get_well_licences_daily did not respond in time.",
                "aer:get_well_licences_daily n'a pas répondu à temps.",
                lang,
            )
        return response.text

    cache_key = f"aer:well-licences-daily:{day_key}"
    raw_text, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_DAILY_SECONDS, fetch)
    report_date = _parse_report_date(raw_text)
    note = None
    if report_date is not None and report_date < expected:
        note = (
            f"This is the {report_date.isoformat()} list: the {day_key} list for "
            f"{expected.isoformat()} is not posted yet (files appear around midnight "
            "Alberta time after the day ends)."
            if lang != "fr"
            else french_spacing(
                f"Voici la liste du {report_date.isoformat()} : celle du "
                f"{expected.isoformat()} ({day_key}) n'est pas encore publiée (les fichiers "
                "paraissent vers minuit, heure de l'Alberta, après la fin de la journée)."
            )
        )
    if lang == "fr":
        note = _join_notes(note, _ENGLISH_ONLY_FR)

    return WellLicenceDailyReport(
        day=day_key,
        report_date=report_date,
        expected_date=expected,
        note=note,
        raw_text=raw_text,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceDailyReport",
            as_of=(
                datetime.combine(report_date, time(), tzinfo=ZoneInfo(constants.TIMEZONE))
                if report_date
                else None
            ),
            freshness=(
                "posted nightly by 12:00am MT; each weekday's file is overwritten weekly"
                if lang != "fr"
                else french_spacing(
                    "publié chaque nuit avant minuit (heure des Rocheuses) ; le fichier de "
                    "chaque jour de la semaine est remplacé chaque semaine"
                )
            ),
            lang=lang,
        ),
    )


def _archive_url(year: int, month: int | None, lang: str = "en") -> str:
    if month is not None:
        if not (1 <= month <= 12):
            _raise(
                InvalidInput,
                f"month must be between 1 and 12, got {month}.",
                f"month doit être compris entre 1 et 12, reçu {month}.",
                lang,
            )
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
    today = datetime.now(ZoneInfo(constants.TIMEZONE)).date()
    first = constants.WELL_LICENCE_FIRST_YEAR
    if not first <= year <= today.year:
        _raise(
            InvalidInput,
            f"year must be between {first} and {today.year} "
            f"(AER's ST1 archive starts in {first}), got {year}.",
            f"year doit être compris entre {first} et {today.year} "
            f"(l'archive ST1 de l'AER commence en {first}), reçu {year}.",
            lang,
        )
    url = _archive_url(year, month, lang)
    if month is not None and (year, month) > (today.year, today.month):
        _raise(
            InvalidInput,
            f"{year}-{month:02d} has not happened yet; nothing is published.",
            f"{year}-{month:02d} n'est pas encore arrivé ; rien n'est publié.",
            lang,
        )

    async def fetch() -> httpx.Response:
        await _LIMITER.acquire()
        try:
            return await _client.head(url, headers=constants.HEAD_HEADERS)
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                "aer:get_well_licence_archive_link did not respond in time.",
                "aer:get_well_licence_archive_link n'a pas répondu à temps.",
                lang,
            )

    cache_key = f"aer:well-licence-archive:{year}:{month}"
    response, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_LINK_SECONDS, fetch)
    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None
    note = None
    if not exists:
        recent = month is not None and (year, month) >= (today.year, today.month - 1)
        if lang == "fr":
            note = french_spacing(
                "Pas encore publié : l'AER met en ligne le ZIP de chaque mois après la fin du mois."
                if recent
                else "L'AER n'a aucun fichier à cette adresse."
            )
        else:
            note = (
                "Not published yet: AER posts each month's ZIP after the month ends."
                if recent
                else "AER has no file at this address."
            )
    if lang == "fr":
        note = _join_notes(note, _ENGLISH_ONLY_FR)

    return WellLicenceArchiveLink(
        year=year,
        month=month,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="aer.WellLicenceArchiveLink",
            lang=lang,
        ),
    )


async def get_production_volumes_link(product: str, *, lang: str = "en") -> ProductionVolumesLink:
    """Resolve (and confirm existence of) AER's ST3 current-month
    production-volume/price XLSX for one product. `product` is one of
    "butane", "ethane", "gas", "ngl", "oil", "propane", "sulphur",
    "oil_prices". Discovery-only -- this project has no pinned
    XLSX-parsing dependency, so the file itself is not parsed here."""
    product_key = product.strip().lower()
    if product_key not in constants.PRODUCTION_PRODUCTS:
        _raise(
            InvalidInput,
            f"product must be one of {sorted(constants.PRODUCTION_PRODUCTS)}, got {product!r}.",
            f"product doit être l'un de {sorted(constants.PRODUCTION_PRODUCTS)}, reçu {product!r}.",
            lang,
        )
    product_path = constants.PRODUCTION_PRODUCTS[product_key]
    url = constants.PRODUCTION_VOLUMES_URL.format(product_path=product_path)

    async def fetch() -> httpx.Response:
        await _LIMITER.acquire()
        try:
            return await _client.head(url, headers=constants.HEAD_HEADERS)
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                "aer:get_production_volumes_link did not respond in time.",
                "aer:get_production_volumes_link n'a pas répondu à temps.",
                lang,
            )

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
            freshness=(
                "ST3 is released monthly, one month in arrears"
                if lang != "fr"
                else "ST3 est publié chaque mois, avec un mois de décalage"
            ),
            limits=_ENGLISH_ONLY_FR if lang == "fr" else None,
            lang=lang,
        ),
    )

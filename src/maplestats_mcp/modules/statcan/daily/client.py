"""Client for The Daily's official Atom feeds.

Confirmed live 2026-09-20. Two real quirks handled:

1. `<title>` and `<summary>` are `type="xhtml"`, holding a nested
   `<div>` that can itself contain inline markup (e.g. a
   `<span class="refper">` wrapping a reference period inside the
   title, confirmed live: "Employer pension plans ...,
   <span class="refper">first quarter 2026</span>"). This client joins
   all text content within the div (`itertext()`) rather than reading
   only the div's direct text, which would silently drop that inline
   text.
2. Some entries are not data releases but simple "new product"
   announcements pointing at a catalogue-number resolver
   (`cgi-bin/IPS/display?cat_num=...`) rather than a
   `daily-quotidien/...` article page -- both are returned as-is via
   `url`; this client does not try to distinguish release articles
   from product announcements, since both are genuine Daily entries.

`search_archive` covers the full release history instead of the Atom
feeds' 100-day window, via a JSON file the release-schedule calendar
page loads client-side (found by reading that page's raw HTML for its
inline `eventsjson:` config, not from any documented API) -- one 3.7 MB
array, 18,222 entries confirmed live from 2012-03-14 onward, no
pagination. Its own `date` field carries an artificial time-of-day
(e.g. "00:00:01", "00:00:02", ...) used only to order same-day entries,
not a real timestamp, so this client keeps only the date component.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx

from maplestats_mcp.modules.statcan.daily import constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveEntry,
    DailyArchiveSearchResult,
    DailyRelease,
    DailyReleaseList,
    ReleaseCalendarEntry,
    ReleaseCalendarResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


def _xhtml_text(entry: ElementTree.Element, tag: str) -> str | None:
    element = entry.find(f"atom:{tag}", constants.ATOM_NS)
    if element is None:
        return None
    div = element.find("xhtml:div", constants.ATOM_NS)
    text = "".join((div if div is not None else element).itertext())
    text = " ".join(text.split())
    return text or None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _release_from_entry(entry: ElementTree.Element) -> DailyRelease:
    link = entry.find("atom:link", constants.ATOM_NS)
    updated = entry.find("atom:updated", constants.ATOM_NS)
    return DailyRelease(
        title=_xhtml_text(entry, "title") or "",
        url=(link.get("href") if link is not None else None) or "",
        published_at=_parse_datetime(updated.text if updated is not None else None),
        summary=_xhtml_text(entry, "summary"),
    )


async def get_releases(
    subject: str = "all", *, lang: str = "en", limit: int = constants.RELEASES_LIMIT_DEFAULT
) -> DailyReleaseList:
    """Fetch recent releases from The Daily for one subject (or "all")."""
    code = constants.SUBJECT_TO_CODE.get(subject)
    if code is None:
        raise InvalidInput(
            f"statcan_daily:get_releases: subject must be one of "
            f"{sorted(constants.SUBJECT_TO_CODE)}, got {subject!r}."
        )
    if limit < 1 or limit > constants.RELEASES_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_daily:get_releases: limit must be between 1 and "
            f"{constants.RELEASES_LIMIT_MAX}, got {limit}."
        )
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = f"{constants.BASE_URL}/{code}-{suffix}.atom"

    async def fetch() -> bytes:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
            return response.content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                f"statcan_daily:get_releases returned HTTP {status} for subject {subject!r}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_daily:get_releases did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    cache_key = f"statcan-daily:releases:{code}:{suffix}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise UpstreamError(
            f"statcan_daily:get_releases: response for subject {subject!r} was not valid XML."
        ) from exc

    entries = root.findall("atom:entry", constants.ATOM_NS)[:limit]
    releases = [_release_from_entry(entry) for entry in entries]
    return DailyReleaseList(
        subject=subject,
        releases=releases,
        returned_count=len(releases),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyReleaseList",
        ),
    )


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(
            f"statcan_daily:search_archive: expected a YYYY-MM-DD date, got {value!r}."
        ) from exc


def _parse_archive_entry_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def search_archive(
    query: str = "",
    *,
    lang: str = "en",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ARCHIVE_SEARCH_LIMIT_DEFAULT,
) -> DailyArchiveSearchResult:
    """Search the full Daily release archive (2012-03-14 onward) by title/period and date range."""
    if limit < 1 or limit > constants.ARCHIVE_SEARCH_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_daily:search_archive: limit must be between 1 and "
            f"{constants.ARCHIVE_SEARCH_LIMIT_MAX}, got {limit}."
        )
    parsed_start = _parse_iso_date(start_date) if start_date else None
    parsed_end = _parse_iso_date(end_date) if end_date else None

    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.FULL_ARCHIVE_URL.format(suffix=suffix)

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(f"statcan_daily:search_archive returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_daily:search_archive did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    cache_key = f"statcan-daily:archive:{suffix}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ARCHIVE_SECONDS, fetch)
    if not isinstance(payload, list):
        raise UpstreamError("statcan_daily:search_archive: expected a JSON array from the archive.")

    query_lower = query.strip().lower()
    matched: list[DailyArchiveEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        entry_date = _parse_archive_entry_date(item.get("date"))
        if entry_date is None:
            continue
        if parsed_start is not None and entry_date < parsed_start:
            continue
        if parsed_end is not None and entry_date > parsed_end:
            continue
        title = item.get("title") or ""
        reference_period = item.get("description") or None
        if (
            query_lower
            and query_lower not in title.lower()
            and (not reference_period or query_lower not in reference_period.lower())
        ):
            continue
        relative_url = item.get("url") or ""
        matched.append(
            DailyArchiveEntry(
                release_date=entry_date,
                title=title,
                reference_period=reference_period,
                url=f"https://www150.statcan.gc.ca{relative_url}",
            )
        )

    matched.sort(key=lambda entry: entry.release_date, reverse=True)
    page = matched[:limit]
    return DailyArchiveSearchResult(
        query=query,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyArchiveSearchResult",
        ),
    )


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'Enquete' finds 'Enquête'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("œ", "oe"))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


async def _fetch_schedule(url: str, label: str) -> tuple[list[Any], bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(f"statcan_daily:release_calendar returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "statcan_daily:release_calendar did not respond in time "
                "(already retried by shared/http.py). Try again shortly."
            ) from exc

    payload, was_cached = await cached_fetch(
        f"statcan-daily:calendar:{label}", constants.CACHE_TTL_ARCHIVE_SECONDS, fetch
    )
    if not isinstance(payload, list):
        raise UpstreamError(
            f"statcan_daily:release_calendar: expected a JSON array from the {label} schedule."
        )
    return payload, was_cached


def _calendar_entries(
    payload: list[Any], kind: str, today: date, host_prefix: str
) -> list[ReleaseCalendarEntry]:
    entries: list[ReleaseCalendarEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        # Products carry a clean release_date; indicators only the "date" with
        # an artificial time-of-day (00:00:01, 00:00:02) that orders same-day rows.
        release_date = _parse_archive_entry_date(item.get("release_date") or item.get("date"))
        if release_date is None:
            continue
        relative_url = item.get("url") or ""
        description = item.get("description") or None
        entries.append(
            ReleaseCalendarEntry(
                release_date=release_date,
                kind=kind,
                title=item.get("title") or "",
                reference_period=description if kind == "key_indicator" else None,
                catalogue_number=item.get("pid") or None,
                scheduled=release_date >= today,
                # Future indicator rows have url == "": the article does not exist yet.
                url=f"{host_prefix}{relative_url}" if relative_url else None,
            )
        )
    return entries


async def get_release_calendar(
    query: str = "",
    *,
    lang: str = "en",
    kind: str = "key_indicators",
    upcoming_only: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.CALENDAR_LIMIT_DEFAULT,
) -> ReleaseCalendarResult:
    """Release calendar: scheduled Daily indicator releases and catalogue product releases."""
    if kind not in ("key_indicators", "products", "all"):
        raise InvalidInput(
            "statcan_daily:get_release_calendar: kind must be one of "
            f"('key_indicators', 'products', 'all'), got {kind!r}."
        )
    if limit < 1 or limit > constants.CALENDAR_LIMIT_MAX:
        raise InvalidInput(
            f"statcan_daily:get_release_calendar: limit must be between 1 and "
            f"{constants.CALENDAR_LIMIT_MAX}, got {limit}."
        )
    parsed_start = _parse_iso_date(start_date) if start_date else None
    parsed_end = _parse_iso_date(end_date) if end_date else None
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    today = datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).date()
    host = "https://www150.statcan.gc.ca"

    entries: list[ReleaseCalendarEntry] = []
    all_cached = True
    urls: list[str] = []
    if kind in ("key_indicators", "all"):
        url = constants.KEY_INDICATORS_URL.format(suffix=suffix)
        payload, was_cached = await _fetch_schedule(url, f"indicators:{suffix}")
        entries += _calendar_entries(payload, "key_indicator", today, host)
        all_cached &= was_cached
        urls.append(url)
    if kind in ("products", "all"):
        url = constants.PRODUCTS_URL.format(suffix=suffix)
        payload, was_cached = await _fetch_schedule(url, f"products:{suffix}")
        entries += _calendar_entries(payload, "product", today, host)
        all_cached &= was_cached
        urls.append(url)

    latest_scheduled = max((e.release_date for e in entries), default=None)
    words = re.findall(r"\w+", _fold(query))
    matched: list[ReleaseCalendarEntry] = []
    for entry in entries:
        if upcoming_only and not entry.scheduled:
            continue
        if parsed_start is not None and entry.release_date < parsed_start:
            continue
        if parsed_end is not None and entry.release_date > parsed_end:
            continue
        haystack = _fold(
            f"{entry.title} {entry.reference_period or ''} {entry.catalogue_number or ''}"
        )
        if all(word in haystack for word in words):
            matched.append(entry)

    # Soonest first when asking about the future, newest first for history.
    matched.sort(key=lambda entry: entry.release_date, reverse=not upcoming_only)
    page = matched[:limit]
    return ReleaseCalendarResult(
        query=query,
        kind=kind,
        upcoming_only=upcoming_only,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        today=today,
        latest_scheduled_date=latest_scheduled,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=urls[0],
            cached=all_cached,
            schema_name="statcan_daily.ReleaseCalendarResult",
            limits=(
                "Dates are StatCan's planned schedule and can change. The products file "
                "lists catalogue releases up to today only; future dates come from the "
                "key-indicators file."
            ),
        ),
    )

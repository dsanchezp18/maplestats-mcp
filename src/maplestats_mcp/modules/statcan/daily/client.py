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
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from maplestats_mcp.modules.statcan.daily import constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveEntry,
    DailyArchiveSearchResult,
    DailyArticle,
    DailyRelease,
    DailyReleaseList,
    ReleaseCalendarEntry,
    ReleaseCalendarResult,
    ReleaseFiles,
    ReleaseFilesResult,
    ReleaseHistory,
    ReleaseProduct,
    ReleaseSurvey,
    ReleaseTable,
    UpcomingRelease,
    UpcomingReleasesResult,
)
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)
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
    use_lang(lang)
    code = constants.SUBJECT_TO_CODE.get(subject)
    if code is None:
        raise InvalidInput(
            say(
                f"statcan_daily:get_releases: subject must be one of "
                f"{sorted(constants.SUBJECT_TO_CODE)}, got {subject!r}.",
                f"statcan_daily:get_releases : subject doit être l'une des valeurs {sorted(constants.SUBJECT_TO_CODE)}, reçu {subject!r}.",
            )
        )
    if limit < 1 or limit > constants.RELEASES_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:get_releases: limit must be between 1 and "
                f"{constants.RELEASES_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:get_releases : limit doit être entre 1 et {constants.RELEASES_LIMIT_MAX}, reçu {limit}.",
            )
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
                say(
                    f"statcan_daily:get_releases returned HTTP {status} for subject {subject!r}.",
                    f"statcan_daily:get_releases a renvoyé HTTP {status} pour le sujet {subject!r}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:get_releases did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:get_releases n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-daily:releases:{code}:{suffix}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)

    try:
        root = DefusedET.fromstring(body)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise UpstreamError(
            say(
                f"statcan_daily:get_releases: response for subject {subject!r} was not valid XML.",
                f"statcan_daily:get_releases : la réponse pour le sujet {subject!r} n'était pas du XML valide.",
            )
        ) from exc

    all_entries = root.findall("atom:entry", constants.ATOM_NS)
    releases = [_release_from_entry(entry) for entry in all_entries[:limit]]
    in_feed = len(all_entries)
    return DailyReleaseList(
        subject=subject,
        releases=releases,
        returned_count=len(releases),
        total_in_feed=in_feed,
        truncated=in_feed > len(releases),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyReleaseList",
            limits=say(
                f"Returned the first {len(releases)} of {in_feed} releases in the feed; "
                f"raise limit (up to {constants.RELEASES_LIMIT_MAX}) for more.",
                f"Les {len(releases)} premières diffusions sur {in_feed} dans le fil ; "
                f"augmentez limit (jusqu'à {constants.RELEASES_LIMIT_MAX}) pour en voir plus.",
            )
            if in_feed > len(releases)
            else None,
            lang=lang,
        ),
    )


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidInput(
            say(
                f"statcan_daily:search_archive: expected a YYYY-MM-DD date, got {value!r}.",
                f"statcan_daily:search_archive : date attendue au format AAAA-MM-JJ, reçu {value!r}.",
            )
        ) from exc


def _parse_archive_entry_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_ARCHIVE_HOST = "https://www150.statcan.gc.ca"


async def _load_archive(lang: str) -> tuple[list[Any], bool, str]:
    """The whole Daily release archive (one JSON array, cached), its cache flag and URL."""
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.FULL_ARCHIVE_URL.format(suffix=suffix)

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamError(
                say(
                    f"statcan_daily:search_archive returned HTTP {status}.",
                    f"statcan_daily:search_archive a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:search_archive did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:search_archive n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    cache_key = f"statcan-daily:archive:{suffix}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ARCHIVE_SECONDS, fetch)
    if not isinstance(payload, list):
        raise UpstreamError(
            say(
                "statcan_daily:search_archive: expected a JSON array from the archive.",
                "statcan_daily:search_archive : tableau JSON attendu de l'archive.",
            )
        )

    return payload, was_cached, url


async def search_archive(
    query: str = "",
    *,
    lang: str = "en",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = constants.ARCHIVE_SEARCH_LIMIT_DEFAULT,
) -> DailyArchiveSearchResult:
    """Search the full Daily release archive (2012-03-14 onward) by title/period and date range."""
    use_lang(lang)
    if limit < 1 or limit > constants.ARCHIVE_SEARCH_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:search_archive: limit must be between 1 and "
                f"{constants.ARCHIVE_SEARCH_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:search_archive : limit doit être entre 1 et {constants.ARCHIVE_SEARCH_LIMIT_MAX}, reçu {limit}.",
            )
        )
    parsed_start = _parse_iso_date(start_date) if start_date else None
    parsed_end = _parse_iso_date(end_date) if end_date else None

    payload, was_cached, url = await _load_archive(lang)
    # Same reference timezone as the release calendar: a release dated today
    # in Toronto is still "scheduled" until its article exists.
    today = datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).date()

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
        # Upcoming "meeting" entries carry url == "": no article yet, so no link
        # (prefixing the host would yield the bare home page).
        relative_url = item.get("url") or ""
        matched.append(
            DailyArchiveEntry(
                release_date=entry_date,
                title=title,
                reference_period=reference_period,
                scheduled=entry_date >= today,
                url=f"{_ARCHIVE_HOST}{relative_url}" if relative_url else None,
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
            lang=lang,
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
            raise UpstreamError(
                say(
                    f"statcan_daily:release_calendar returned HTTP {status}.",
                    f"statcan_daily:release_calendar a renvoyé HTTP {status}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:release_calendar did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:release_calendar n'a pas répondu à temps (nouvelles tentatives déjà faites). Réessayez sous peu.",
                )
            ) from exc

    payload, was_cached = await cached_fetch(
        f"statcan-daily:calendar:{label}", constants.CACHE_TTL_ARCHIVE_SECONDS, fetch
    )
    if not isinstance(payload, list):
        raise UpstreamError(
            say(
                f"statcan_daily:release_calendar: expected a JSON array from the {label} schedule.",
                f"statcan_daily:release_calendar : tableau JSON attendu du calendrier {label}.",
            )
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


# Words that ask the question rather than name the release ("next CPI release date").
# Dropped before matching titles, in the calendars as in the history below: "next" is
# in no title, so "next consumer price index" once matched nothing scheduled.
_QUESTION_WORDS = frozenset(
    [
        "next",
        "upcoming",
        "release",
        "releases",
        "released",
        "date",
        "dates",
        "when",
        "scheduled",
        "schedule",
        "prochain",
        "prochaine",
        "prochaines",
        "diffusion",
        "diffusions",
        "date",
        "dates",
        "quand",
        "prevue",
        "prevu",
    ]
)
# Words that name a period. The history drops them too: "PTEA 2026" or "LFS for
# October" should find the release's past dates, whose periods are other years and months.
_PERIOD_WORDS = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "janvier",
        "fevrier",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
        "first",
        "second",
        "third",
        "fourth",
        "quarter",
        "premier",
        "deuxieme",
        "troisieme",
        "quatrieme",
        "trimestre",
    ]
)
_HISTORY_SIZE = 3
_YEAR = re.compile(r"(19|20)\d\d")


def _query_words(query: str) -> list[str]:
    """The query's words, folded, without the ones that only ask the question."""
    return [w for w in re.findall(r"\w+", _fold(query)) if w not in _QUESTION_WORDS]


def _release_words(query: str) -> list[str]:
    """The words that name the release itself: no years, months or quarters."""
    return [w for w in _query_words(query) if not _YEAR.fullmatch(w) and w not in _PERIOD_WORDS]


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # February 29
        return day.replace(year=day.year + years, day=28)


async def _release_history(
    query: str,
    lang: str,
    today: date,
    scheduled: list[tuple[date, str, str | None]] | None = None,
    more_scheduled: Callable[[], Awaitable[list[tuple[date, str, str | None]]]] | None = None,
) -> ReleaseHistory | None:
    """The same release's past (and known scheduled) dates, for a query that matched nothing.

    An analyst asking when the 2026 provincial and territorial economic accounts come out
    gets nothing from the calendars, which list a few weeks to six months ahead. The archive
    says when the release came out before (2025-11-06, 2024-11-07, 2023-11-08), and with the
    one already scheduled (2025 accounts, 2026-11-05) that answers "around November 2027",
    as long as it is called an estimate. `scheduled` adds releases a calendar knows about
    that the archive may not list yet (the two-week page has more than the archive);
    `more_scheduled` fetches more of them, only once the archive has a match.
    """
    words = _release_words(query)
    if not words:
        return None
    try:
        payload, _, _ = await _load_archive(lang)
    except (UpstreamError, UpstreamUnavailable):
        return None  # a guide, not the answer: the calendar result stands without it
    rows: dict[tuple[date, str], tuple[str | None, str | None]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        when = _parse_archive_entry_date(item.get("date"))
        title = (item.get("title") or "").strip()
        if when and title and all(word in _fold(title) for word in words):
            rows[(when, title)] = (item.get("description") or None, item.get("url") or None)
    if not rows:
        return None
    if more_scheduled is not None:
        scheduled = [*(scheduled or []), *await more_scheduled()]
    for when, title, period in scheduled or []:
        if all(word in _fold(title) for word in words):
            rows.setdefault((when, title), (period, None))
    past = sorted((k for k in rows if k[0] < today), reverse=True)
    if not past:
        return None
    # The newest past match names the release; keep only that title, so "supply and use
    # tables" does not mix in "Digital supply and use tables".
    title = past[0][1]
    entries = [
        DailyArchiveEntry(
            release_date=when,
            title=title,
            reference_period=rows[(when, t)][0],
            scheduled=False,
            url=f"{_ARCHIVE_HOST}{rows[(when, t)][1]}" if rows[(when, t)][1] else None,
        )
        for when, t in past
        if t == title
    ][:_HISTORY_SIZE]
    ahead = sorted((when, rows[(when, t)][0]) for when, t in rows if when >= today and t == title)
    gaps = sorted((a.release_date - b.release_date).days for a, b in pairwise(entries))
    gap = gaps[len(gaps) // 2] if gaps else None

    # The estimate: an annual release and a year asked for give that year's date; otherwise
    # the latest known date (scheduled or past) plus the usual gap.
    asked = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", query)]
    latest_date, latest_period = ahead[-1] if ahead else (entries[0].release_date, None)
    if not ahead:
        latest_period = entries[0].reference_period
    annual = gap is not None and 300 <= gap <= 430
    estimate: date | None = None
    if annual and asked and latest_period and _YEAR.fullmatch(latest_period.strip()):
        years = asked[-1] - int(latest_period.strip())
        estimate = _add_years(latest_date, years) if years > 0 else None
    elif gap and not ahead:
        estimate = entries[0].release_date + timedelta(days=gap)
    if estimate is not None and estimate < today:
        estimate = None  # overdue by its own pattern: no honest estimate

    dates = ", ".join(
        e.release_date.isoformat() + (f" ({e.reference_period})" if e.reference_period else "")
        for e in entries
    )
    next_known = "; ".join(
        f"{when.isoformat()}" + (f" ({period})" if period else "") for when, period in ahead
    )
    note = say(
        "No release date is announced for what you asked."
        + (f" Already scheduled: {title}, {next_known}." if ahead else "")
        + f" Past releases of {title}: {dates}."
        + (
            f" If it follows that pattern, it would come out around {estimate.isoformat()}: "
            "an estimate from past dates, not a scheduled date."
            if estimate
            else ""
        ),
        "Aucune date de diffusion n'est annoncée pour ce qui est demandé."
        + (f" Déjà prévu : {title}, {next_known}." if ahead else "")
        + f" Diffusions passées de {title} : {dates}."
        + (
            f" S'il suit ce rythme, il paraîtrait vers le {estimate.isoformat()} : "
            "une estimation tirée des dates passées, pas une date prévue."
            if estimate
            else ""
        ),
    )
    return ReleaseHistory(
        note=note,
        title=title,
        previous_releases=entries,
        scheduled_releases=[
            DailyArchiveEntry(
                release_date=when, title=title, reference_period=period, scheduled=True
            )
            for when, period in ahead
        ],
        typical_gap_days=gap,
        estimated_next_date=estimate,
    )


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
    use_lang(lang)
    if kind not in ("key_indicators", "products", "all"):
        raise InvalidInput(
            say(
                "statcan_daily:get_release_calendar: kind must be one of "
                f"('key_indicators', 'products', 'all'), got {kind!r}.",
                f"statcan_daily:get_release_calendar : kind doit être l'une des valeurs ('key_indicators', 'products', 'all'), reçu {kind!r}.",
            )
        )
    if limit < 1 or limit > constants.CALENDAR_LIMIT_MAX:
        raise InvalidInput(
            say(
                f"statcan_daily:get_release_calendar: limit must be between 1 and "
                f"{constants.CALENDAR_LIMIT_MAX}, got {limit}.",
                f"statcan_daily:get_release_calendar : limit doit être entre 1 et {constants.CALENDAR_LIMIT_MAX}, reçu {limit}.",
            )
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
    words = _query_words(query)
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
    history = None
    if query.strip() and upcoming_only and not matched:
        # The two-week page lists releases the key-indicators file does not (the PTEA and
        # supply and use tables, checked 2026-11-04), so the history sees both.
        known = [(e.release_date, e.title, e.reference_period) for e in entries if e.scheduled]
        history = await _release_history(
            query, lang, today, known, more_scheduled=lambda: _two_weeks(lang)
        )
    return ReleaseCalendarResult(
        query=query,
        kind=kind,
        upcoming_only=upcoming_only,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        today=today,
        latest_scheduled_date=latest_scheduled,
        not_scheduled=history,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=urls[0],
            cached=all_cached,
            schema_name="statcan_daily.ReleaseCalendarResult",
            limits=say(
                "Dates are StatCan's planned schedule and can change. The products file "
                "lists catalogue releases up to today only; future dates come from the "
                "key-indicators file.",
                "Les dates sont le calendrier prévu par Statistique Canada et peuvent changer. "
                "Le fichier des produits liste les diffusions au catalogue jusqu'à aujourd'hui "
                "seulement ; les dates futures viennent du fichier des indicateurs clés.",
            ),
            lang=lang,
        ),
    )


# An article id is "dq" + the release day (YYMMDD) + one or more letters, the letter
# telling apart the day's articles (dq261104a, dq261104b, ...). The feeds and the archive
# give full URLs on www.statcan.gc.ca or www150.statcan.gc.ca; either form, or the bare
# id, is accepted, and the page is always read in the language asked for.
_ARTICLE_ID = re.compile(r"\b(dq(\d{6})[a-z]+)(?:-(?:eng|fra))?(?:\.htm)?", re.IGNORECASE)
_PID = re.compile(r"[?&]pid=(\d{8})\d{2}")


def _article_url(article: str, lang: str) -> tuple[str, str]:
    match = _ARTICLE_ID.search(article.strip())
    if match is None:
        raise InvalidInput(
            say(
                "statcan_daily:get_article: give a Daily article URL or id such as "
                f"'dq261104a' (from statcan_daily_get_releases), got {article!r}.",
                "statcan_daily:get_article : donnez l'adresse ou l'identifiant d'un article du "
                "Quotidien, par exemple 'dq261104a' (voir statcan_daily_get_releases), "
                f"reçu {article!r}.",
            )
        )
    article_id = match.group(1).lower()
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.ARTICLE_URL_TEMPLATE.format(
        day=match.group(2), article_id=article_id, suffix=suffix
    )
    return article_id, url


def _clean(text: str) -> str:
    return " ".join(text.split())


def _table_id(digits: str) -> str:
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:8]}-01"


# Links in an article are root-relative ("/daily-quotidien/...", "/en/catalogue/...");
# on www150 those answer 301 to the same path under /n1/ (checked 2026-11-04 from the
# Azure server), so they are given in that final form.
_N1_PREFIXES = ("/daily-quotidien/", "/dai-quo/", "/en/", "/fr/", "/release-diffusion/")


def _absolute(url: str, href: str) -> str:
    absolute = urljoin(url, href)
    host = "https://www150.statcan.gc.ca"
    if absolute.startswith(host) and absolute[len(host) :].startswith(_N1_PREFIXES):
        return f"{host}/n1{absolute[len(host) :]}"
    return absolute


def _article_section(main: Tag) -> Tag | None:
    """The <section> holding the release nav and the text.

    Checked 2026-11-04 on articles from 2013, 2017, 2021 and 2024: an article that is
    no longer current carries an "Archived Content" notice first, as
    <section id="archived"> and <section id="archived-bnr">, and only then the article's
    own <section>; a current one has that section alone after the <h1>.
    """
    for section in main.find_all("section"):
        if section.find("div", class_="release_nav") or section.find("p", class_="sd-release-date"):
            return section
    return None


def _parse_article(html: str, url: str) -> dict[str, Any]:
    """Pull the article out of a Daily page (layout described in constants.py)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    heading = main.find("h1") if isinstance(main, Tag) else None
    body = _article_section(main) if isinstance(main, Tag) else None
    if not isinstance(main, Tag) or not isinstance(heading, Tag) or not isinstance(body, Tag):
        raise UpstreamError(
            say(
                f"statcan_daily:get_article: {url} has no article (no <h1> and <section> "
                "in <main>); StatCan may have changed the page layout.",
                f"statcan_daily:get_article : {url} ne contient pas d'article (pas de <h1> ni "
                "de <section> dans <main>) ; Statistique Canada a peut-être changé la page.",
            )
        )

    def meta(name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name})
        value = tag.get("content") if isinstance(tag, Tag) else None
        return _clean(str(value)) if value else None

    nav: dict[str, str] = {}
    release_nav = body.find("div", class_="release_nav")
    if isinstance(release_nav, Tag):
        for link in release_nav.find_all("a", href=True):
            href = _absolute(url, str(link["href"]))
            if href.endswith(".pdf"):
                nav["pdf"] = href
            elif "-cansim-" in href:
                nav["tables"] = href
            elif "-info-" in href:
                nav["info"] = href
            elif "/dai-quo/cal" in href:
                nav["schedule"] = href
            elif "/daily-quotidien/" in href and href.split("?")[0] != url:
                nav["previous"] = href

    sections: list[dict[str, Any]] = [{"heading": None, "parts": []}]
    charts: list[str] = []

    def add_text(element: Tag) -> None:
        if element.name in ("ul", "ol"):
            items = [_clean(item.get_text(" ")) for item in element.find_all("li")]
            text = "\n".join(f"- {item}" for item in items if item)
        else:
            text = _clean(element.get_text(" "))
        if text:
            sections[-1]["parts"].append(text)

    for child in body.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class") or []
        if child.name == "h2" and "chartt" not in classes:
            sections.append({"heading": _clean(child.get_text(" ")), "parts": []})
        elif child.name in ("p", "ul", "ol") and "sd-release-date" not in classes:
            add_text(child)
        elif child.name == "div" and "sd-noteuser" in classes:
            title = child.find(["h2", "h3"])
            note = _clean(title.get_text(" ")) if isinstance(title, Tag) else "Note to readers"
            sections.append({"heading": note, "parts": []})
            panel = child.find("div", class_="panel-body")
            for element in (panel if isinstance(panel, Tag) else child).find_all(
                ["p", "h3", "h4", "ul", "ol"], recursive=False
            ):
                if element.name in ("h3", "h4"):
                    sub = _clean(element.get_text(" "))
                    sections.append({"heading": f"{note}: {sub}", "parts": []})
                else:
                    add_text(element)
        elif child.name == "div":
            chart = child.find("h2", class_="chartt")
            if isinstance(chart, Tag):
                charts.append(_clean(chart.get_text(" ")))

    tables: dict[int, str] = {}
    links: dict[str, str] = {}
    nav_urls = set(nav.values())
    for link in body.find_all("a", href=True):
        href = str(link["href"])
        if href.startswith(("#", "mailto:")):
            continue
        absolute = _absolute(url, href)
        pid = _PID.search(absolute)
        if pid:
            tables.setdefault(int(pid.group(1)), _table_id(pid.group(1)))
            continue
        text = _clean(link.get_text(" "))
        # Chart thumbnails (cg-a001-eng.htm) carry no text; their titles are in `charts`.
        if not text or absolute in nav_urls or absolute.split("?")[0] == url:
            continue
        links.setdefault(absolute, text)

    issued = meta("dcterms.issued")
    try:
        release_date = date.fromisoformat(issued) if issued else None
    except ValueError:
        release_date = None
    built = [
        {"heading": section["heading"], "text": "\n\n".join(section["parts"])}
        for section in sections
        if section["parts"]
    ]
    return {
        "title": _clean(heading.get_text(" ")),
        "release_date": release_date,
        "archived": main.find("section", id="archived") is not None,
        "summary": meta("dcterms.description") or meta("description"),
        "sections": built,
        "charts": charts,
        "tables": [
            {"table_id": table_id, "product_id": product_id}
            for product_id, table_id in tables.items()
        ],
        "pdf_url": nav.get("pdf"),
        "tables_page_url": nav.get("tables"),
        "related_info_url": nav.get("info"),
        "previous_release_url": nav.get("previous"),
        "links": [{"text": text, "url": href} for href, text in links.items()],
        "word_count": sum(len(section["text"].split()) for section in built),
    }


async def get_article(article: str, *, lang: str = "en") -> DailyArticle:
    """Read one Daily article in full: its sections, tables, charts and PDF link."""
    use_lang(lang)
    article_id, url = _article_url(article, lang)

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise NotFound(
                    say(
                        f"statcan_daily:get_article: StatCan has no Daily article {article_id} "
                        f"({url}). Take the id from statcan_daily_get_releases or "
                        "statcan_daily_search_archive.",
                        "statcan_daily:get_article : Statistique Canada n'a pas d'article "
                        f"{article_id} dans Le Quotidien ({url}). Prenez l'identifiant dans "
                        "statcan_daily_get_releases ou statcan_daily_search_archive.",
                    )
                ) from exc
            raise UpstreamError(
                say(
                    f"statcan_daily:get_article returned HTTP {status} for {url}.",
                    f"statcan_daily:get_article a renvoyé HTTP {status} pour {url}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    "statcan_daily:get_article did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    "statcan_daily:get_article n'a pas répondu à temps (nouvelles tentatives "
                    "déjà faites). Réessayez sous peu.",
                )
            ) from exc
        return response.text

    html, was_cached = await cached_fetch(
        f"statcan-daily:article:{article_id}:{lang}", constants.CACHE_TTL_ARTICLE_SECONDS, fetch
    )
    parsed = _parse_article(html, url)
    return DailyArticle(
        url=url,
        article_id=article_id,
        **parsed,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.DailyArticle",
            limits=say(
                "Text only: charts and the release's own tables are listed by title and "
                "link, not reproduced. Read figures from the tables (wds_ tools) and cite them.",
                "Texte seulement : les graphiques et les tableaux du communiqué sont donnés par "
                "titre et lien, sans leur contenu. Lisez les chiffres dans les tableaux (outils "
                "wds_) et citez-les.",
            ),
            lang=lang,
        ),
    )


async def _two_weeks(lang: str) -> list[tuple[date, str, str | None]]:
    """The two-week page's releases as (date, title, period); empty if it cannot be read."""
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.UPCOMING_URL.format(suffix=suffix)
    try:
        html, _ = await _fetch_html(
            url,
            f"statcan-daily:upcoming:{suffix}",
            constants.CACHE_TTL_UPCOMING_SECONDS,
            "get_release_calendar",
            missing_ok=True,
        )
        _, releases, _ = _parse_upcoming(html or "", url) if html else ("", [], None)
    except (UpstreamError, UpstreamUnavailable):
        return []
    return [(r.release_date, r.title, r.reference_period) for r in releases]


async def _fetch_html(
    url: str, cache_key: str, ttl: int, tool: str, *, missing_ok: bool
) -> tuple[str | None, bool]:
    """Read one StatCan page; a 404 gives None when `missing_ok`, else NotFound."""

    async def fetch() -> str | None:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404 and missing_ok:
                return None
            if status == 404:
                raise NotFound(
                    say(
                        f"statcan_daily:{tool}: StatCan has no page at {url}.",
                        f"statcan_daily:{tool} : Statistique Canada n'a pas de page à {url}.",
                    )
                ) from exc
            raise UpstreamError(
                say(
                    f"statcan_daily:{tool} returned HTTP {status} for {url}.",
                    f"statcan_daily:{tool} a renvoyé HTTP {status} pour {url}.",
                )
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                say(
                    f"statcan_daily:{tool} did not respond in time "
                    "(already retried by shared/http.py). Try again shortly.",
                    f"statcan_daily:{tool} n'a pas répondu à temps (nouvelles tentatives "
                    "déjà faites). Réessayez sous peu.",
                )
            ) from exc
        return response.text

    return await cached_fetch(cache_key, ttl, fetch)


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}  # fmt: skip


def _day_month(text: str) -> tuple[int, int] | None:
    """'November 4' or '4 novembre' -> (11, 4); the day headings carry no year."""
    words = re.findall(r"\w+", _fold(text))
    month = next((_MONTHS[w] for w in words if w in _MONTHS), None)
    day = next((int(w) for w in words if w.isdigit() and 1 <= int(w) <= 31), None)
    return (month, day) if month and day else None


def _parse_upcoming(html: str, url: str) -> tuple[str, list[UpcomingRelease], str | None]:
    """The two-week list on cal2 (layout described in constants.py)."""
    soup = BeautifulSoup(html, "html.parser")
    block = soup.find("div", class_="upcoming")
    heading = block.find("h2") if isinstance(block, Tag) else None
    if not isinstance(block, Tag) or not isinstance(heading, Tag):
        raise UpstreamError(
            say(
                f"statcan_daily:get_upcoming_releases: {url} has no upcoming-release list "
                "(div.upcoming); StatCan may have changed the page.",
                f"statcan_daily:get_upcoming_releases : {url} n'a pas de liste des "
                "diffusions à venir (div.upcoming) ; Statistique Canada a peut-être changé "
                "la page.",
            )
        )
    period = _clean(heading.get_text(" "))
    years = re.findall(r"\b(20\d\d)\b", period)
    year = int(years[-1]) if years else datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).year

    days: list[tuple[tuple[int, int], Tag]] = []
    for day_heading in block.find_all("h3"):
        parsed = _day_month(day_heading.get_text(" "))
        listing = day_heading.find_next_sibling("ol")
        if parsed and isinstance(listing, Tag):
            days.append((parsed, listing))
    # A window can run over New Year ("December 28 to January 8, 2027"): the heading's
    # year is the last day's, so a month after the last day's month is the year before.
    last_month = days[-1][0][0] if days else 12
    releases: list[UpcomingRelease] = []
    for (month, day), listing in days:
        release_date = date(year - 1 if month > last_month else year, month, day)
        for item in listing.find_all("li", recursive=False):
            title_tag = item.find("div", class_="rtitle")
            if not isinstance(title_tag, Tag):
                continue
            refper_tag = title_tag.find("span", class_="refper")
            refper = None
            if isinstance(refper_tag, Tag):
                refper = _clean(refper_tag.get_text(" ")) or None
                refper_tag.extract()
            title = _clean(title_tag.get_text(" ")).rstrip(" ,")
            lockup_tag = item.find("div", class_="lockup")
            contact_tag = item.find("p", class_="contact")
            contact = phone = None
            if isinstance(contact_tag, Tag):
                phone_tag = contact_tag.find("span", class_="phone")
                if isinstance(phone_tag, Tag):
                    phone = _clean(phone_tag.get_text(" ")) or None
                    phone_tag.extract()
                contact = _clean(contact_tag.get_text(" ")).strip("() ,") or None
            releases.append(
                UpcomingRelease(
                    release_date=release_date,
                    title=title,
                    reference_period=refper,
                    lockup=isinstance(lockup_tag, Tag) and bool(lockup_tag.get_text(strip=True)),
                    contact=contact,
                    phone=phone,
                )
            )

    pdf = None
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if href.endswith(".pdf") and "upcoming" in href:
            pdf = _absolute(url, href)
            break
    return period, releases, pdf


def _parse_major_releases(html: str, url: str) -> tuple[str | None, str | None, list[str]]:
    """The year's PDF of planned dates and the indicator list on cal1."""
    soup = BeautifulSoup(html, "html.parser")
    pdf_url = label = None
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "/release-diffusion/" in href and href.endswith(".pdf"):
            pdf_url = _absolute(url, href)
            label = re.sub(r"\s*\([^)]*\b[kK][bBoO]\)\s*$", "", _clean(link.get_text(" ")))
            break
    picker = soup.find("select", id="select_keylist")
    indicators = (
        [_clean(option.get_text(" ")) for option in picker.find_all("option")]
        if isinstance(picker, Tag)
        else []
    )
    return pdf_url, label or None, [name for name in indicators if name]


async def get_upcoming_releases(query: str = "", *, lang: str = "en") -> UpcomingReleasesResult:
    """Every release scheduled in the next two weeks, plus the year's major-release PDF."""
    use_lang(lang)
    suffix = constants.LANG_TO_SUFFIX.get(lang, "eng")
    url = constants.UPCOMING_URL.format(suffix=suffix)
    html, was_cached = await _fetch_html(
        url,
        f"statcan-daily:upcoming:{suffix}",
        constants.CACHE_TTL_UPCOMING_SECONDS,
        "get_upcoming_releases",
        missing_ok=False,
    )
    period, releases, pdf_url = _parse_upcoming(html or "", url)

    major_url = constants.MAJOR_RELEASES_URL.format(suffix=suffix)
    # The annual PDF is a pointer, not the answer: a failure there leaves it out rather
    # than losing the two-week list.
    try:
        major_html, _ = await _fetch_html(
            major_url,
            f"statcan-daily:major-releases:{suffix}",
            constants.CACHE_TTL_ARCHIVE_SECONDS,
            "get_upcoming_releases",
            missing_ok=True,
        )
    except (UpstreamError, UpstreamUnavailable):
        major_html = None
    annual_pdf, annual_label, indicators = (
        _parse_major_releases(major_html, major_url) if major_html else (None, None, [])
    )

    words = _query_words(query)
    matched = [
        release
        for release in releases
        if all(word in _fold(f"{release.title} {release.reference_period or ''}") for word in words)
    ]
    history = None
    if query.strip() and not matched:
        today = datetime.now(ZoneInfo(constants.CALENDAR_TIMEZONE)).date()
        history = await _release_history(
            query, lang, today, [(r.release_date, r.title, r.reference_period) for r in releases]
        )
    return UpcomingReleasesResult(
        query=query,
        period=period,
        start_date=releases[0].release_date if releases else None,
        end_date=releases[-1].release_date if releases else None,
        releases=matched,
        returned_count=len(matched),
        total_in_window=len(releases),
        pdf_url=pdf_url,
        annual_schedule_pdf_url=annual_pdf,
        annual_schedule_label=annual_label,
        major_indicators=indicators,
        not_scheduled=history,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="statcan_daily.UpcomingReleasesResult",
            coverage=period,
            limits=say(
                "Two weeks ahead only, and StatCan compiles the list for planning: dates "
                "can move. For the major indicators further ahead (about six months) use "
                "statcan_daily_get_release_calendar, or the annual PDF.",
                "Deux semaines seulement, et Statistique Canada dresse la liste à des fins de "
                "planification : les dates peuvent changer. Pour les grands indicateurs plus "
                "loin (environ six mois), utilisez statcan_daily_get_release_calendar ou le "
                "PDF annuel.",
            ),
            lang=lang,
        ),
    )


_LEGACY_CANSIM = re.compile(r"/cansim/(\d{3}-\d{4})\b")
_LEGACY_CANSIM_LIST = re.compile(r"[?&]cansim=([\d,\-]+)")
_SDDS = re.compile(r"(?:SDDS=|imdb-bmdi/)(\d{3,4})\b", re.IGNORECASE)
_CATALOGUE = re.compile(r"/catalogue/(\d{2}-\d{3}-[A-Z])")
_PREVIOUS_TEXT = ("previous release", "communique precedent")


def _release_links(soup: BeautifulSoup, url: str) -> dict[str, Any]:
    """Links any layout of a Daily page carries: its tabs, PDF, tables, surveys, products.

    Reads every link in <main> (or <body> for the 2012 layout, which has no <main>),
    so the same code serves the tabs of a current release and the bare text of an old one.
    """
    root = soup.find("main") or soup.body or soup
    found: dict[str, Any] = {
        "tables": {},
        "legacy": {},
        "surveys": {},
        "products": {},
        "subjects": [],
    }
    own = _ARTICLE_ID.search(url)
    own_id = own.group(1).lower() if own else "\0"
    links = root.find_all("a", href=True) if isinstance(root, Tag) else []
    for link in links:
        href = str(link["href"])
        if href.startswith(("#", "mailto:")):
            continue
        absolute = _absolute(url, href)
        text = _clean(link.get_text(" "))
        if absolute.endswith(".pdf") and own_id in absolute:
            found.setdefault("pdf", absolute)
        elif "-cansim-" in absolute and own_id in absolute:
            found.setdefault("tables_page", absolute)
        elif "-info-" in absolute and own_id in absolute:
            found.setdefault("info_page", absolute)
        elif "/dai-quo/cal" in absolute and "sk=" in absolute:
            found.setdefault("schedule", absolute)
        elif _fold(text) in _PREVIOUS_TEXT and "/daily-quotidien/" in absolute:
            found.setdefault("previous", absolute)
        elif pid := _PID.search(absolute):
            found["tables"].setdefault(int(pid.group(1)), absolute)
        elif cansim := _LEGACY_CANSIM.search(absolute):
            found["legacy"].setdefault(cansim.group(1), absolute)
        elif many := _LEGACY_CANSIM_LIST.search(absolute):
            for number in many.group(1).split(","):
                if re.fullmatch(r"\d{3}-\d{4}", number):
                    found["legacy"].setdefault(number, absolute)
        elif sdds := _SDDS.search(absolute):
            # The Related information tab writes "1301 — Gross Domestic Product by
            # Industry"; a 2012 page links only "survey number 1301", which names nothing.
            name = re.sub(r"^\d+\s*[–—-]?\s*", "", text)
            if not name or sdds.group(1) in name:
                name = None
            found["surveys"].setdefault(int(sdds.group(1)), (name, absolute))
        elif catalogue := _CATALOGUE.search(absolute):
            number = catalogue.group(1)
            # Old pages link the number itself ("Catalogue number 13-010-X"): no title there.
            title = None if re.search(r"\d{2}-\d{3}-[A-Z]", text) else text or None
            known = found["products"].get(number)
            if known is None or (known[0] is None and title):
                found["products"][number] = (title, absolute)
        elif "/rel-com/theme" in absolute and text:
            found["subjects"].append(text)
    return found


def _tables_tab(html: str, url: str) -> list[ReleaseTable]:
    """Every table of a release, from its Tables tab (table#release-list)."""
    soup = BeautifulSoup(html, "html.parser")
    listing = soup.find("table", id="release-list")
    tables: list[ReleaseTable] = []
    links = listing.find_all("a", href=True) if isinstance(listing, Tag) else []
    for link in links:
        absolute = _absolute(url, str(link["href"]))
        heading = link.find("h3")
        frequency = None
        if isinstance(heading, Tag):
            frequency_tag = heading.find("span", class_="frq")
            if isinstance(frequency_tag, Tag):
                frequency = _clean(frequency_tag.get_text(" ")).strip("()") or None
                frequency_tag.extract()
        number_tag = link.find("p", class_="arrayid")
        number = _clean(number_tag.get_text(" ")).strip("()") if isinstance(number_tag, Tag) else ""
        pid = _PID.search(absolute)
        # 2015-2017 tabs list the old CANSIM number ("379-0031") and link a dead URL.
        legacy = number if re.fullmatch(r"\d{3}-\d{4}", number) else None
        tables.append(
            ReleaseTable(
                title=_clean(heading.get_text(" ")) if isinstance(heading, Tag) else None,
                frequency=frequency,
                table_id=_table_id(pid.group(1))
                if pid
                else (number or None if not legacy else None),
                product_id=int(pid.group(1)) if pid else None,
                legacy_cansim_id=legacy,
                url=absolute,
            )
        )
    return tables


async def _legacy_to_current(numbers: set[str]) -> dict[str, int]:
    """Map old CANSIM numbers to today's 8-digit product ids via the WDS table inventory."""
    if not numbers:
        return {}
    # Imported here: only a release citing old CANSIM numbers needs the WDS inventory.
    from maplestats_mcp.modules.statcan.wds.client import get_all_cubes_list

    try:
        inventory = await get_all_cubes_list(lite=True)
    except Exception:  # noqa: BLE001 -- the mapping is a convenience; the old numbers stay
        return {}
    wanted = {re.sub(r"\D", "", number): number for number in numbers}
    mapping: dict[str, int] = {}
    for cube in inventory.cubes:
        for old in re.split(r"[,;\s]+", cube.cansim_id or ""):
            number = wanted.get(re.sub(r"\D", "", old))
            if number:
                mapping.setdefault(number, cube.product_id)
    return mapping


async def _release_files(article_id: str, url: str, lang: str) -> tuple[ReleaseFiles, bool]:
    ttl = constants.CACHE_TTL_ARTICLE_SECONDS
    html, cached = await _fetch_html(
        url,
        f"statcan-daily:article:{article_id}:{lang}",
        ttl,
        "get_release_files",
        missing_ok=False,
    )
    soup = BeautifulSoup(html or "", "html.parser")
    found = _release_links(soup, url)
    heading = soup.find("h1")
    title = _clean(heading.get_text(" ")) if isinstance(heading, Tag) else article_id
    day = article_id[2:8]
    release_date = date(2000 + int(day[:2]), int(day[2:4]), int(day[4:6]))

    tables: list[ReleaseTable] = []
    if "tables_page" in found:
        tab_html, tab_cached = await _fetch_html(
            found["tables_page"],
            f"statcan-daily:tables:{article_id}:{lang}",
            ttl,
            "get_release_files",
            missing_ok=True,
        )
        cached &= tab_cached
        tables = _tables_tab(tab_html, found["tables_page"]) if tab_html else []
    if not tables:
        tables = [
            ReleaseTable(table_id=_table_id(str(pid)), product_id=pid, url=link)
            for pid, link in found["tables"].items()
        ] + [
            ReleaseTable(legacy_cansim_id=number, url=link)
            for number, link in found["legacy"].items()
        ]

    surveys = found["surveys"]
    subjects = found["subjects"]
    products = found["products"]
    if "info_page" in found:
        info_html, info_cached = await _fetch_html(
            found["info_page"],
            f"statcan-daily:info:{article_id}:{lang}",
            ttl,
            "get_release_files",
            missing_ok=True,
        )
        cached &= info_cached
        if info_html:
            info = _release_links(BeautifulSoup(info_html, "html.parser"), found["info_page"])
            # Keep whichever side names the survey or product; the tab usually does.
            for key, value in info["surveys"].items():
                if value[0] or key not in surveys:
                    surveys[key] = value
            for key, value in info["products"].items():
                if value[0] or key not in products:
                    products[key] = value
            subjects = info["subjects"] or subjects

    return (
        ReleaseFiles(
            article_id=article_id,
            url=url,
            title=title,
            release_date=release_date,
            pdf_url=found.get("pdf"),
            tables=tables,
            surveys=[
                ReleaseSurvey(sdds=sdds, name=name, url=link)
                for sdds, (name, link) in surveys.items()
            ],
            products=[
                ReleaseProduct(catalogue_number=number, title=product_title, url=link)
                for number, (product_title, link) in products.items()
            ],
            subjects=list(dict.fromkeys(subjects)),
            tables_page_url=found.get("tables_page"),
            related_info_url=found.get("info_page"),
            release_schedule_url=found.get("schedule"),
            previous_release_url=found.get("previous"),
        ),
        cached,
    )


async def get_release_files(
    article: str, *, lang: str = "en", previous: int = 0
) -> ReleaseFilesResult:
    """The tables, PDF, surveys and publications of a Daily release and its predecessors."""
    use_lang(lang)
    if previous < 0 or previous > constants.RELEASE_FILES_PREVIOUS_MAX:
        raise InvalidInput(
            say(
                "statcan_daily:get_release_files: previous must be between 0 and "
                f"{constants.RELEASE_FILES_PREVIOUS_MAX}, got {previous}.",
                "statcan_daily:get_release_files : previous doit être entre 0 et "
                f"{constants.RELEASE_FILES_PREVIOUS_MAX}, reçu {previous}.",
            )
        )
    article_id, url = _article_url(article, lang)
    releases: list[ReleaseFiles] = []
    all_cached = True
    seen: set[str] = set()
    next_url: str | None = url
    while next_url and len(releases) <= previous:
        current_id, current_url = _article_url(next_url, lang)
        if current_id in seen:
            break
        seen.add(current_id)
        files, cached = await _release_files(current_id, current_url, lang)
        releases.append(files)
        all_cached &= cached
        next_url = files.previous_release_url

    legacy = {t.legacy_cansim_id for r in releases for t in r.tables if t.legacy_cansim_id}
    mapping = await _legacy_to_current(legacy)
    for release in releases:
        for table in release.tables:
            pid = mapping.get(table.legacy_cansim_id or "")
            if pid and table.product_id is None:
                table.product_id = pid
                table.table_id = _table_id(str(pid))

    return ReleaseFilesResult(
        article=article_id,
        releases=releases,
        returned_count=len(releases),
        chain_ended=releases[-1].previous_release_url is None,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=all_cached,
            schema_name="statcan_daily.ReleaseFilesResult",
            limits=say(
                "Links only: read a table's figures with the wds_ tools (product_id), and "
                "the article text with statcan_daily_get_article. Old CANSIM numbers are "
                "matched to today's tables through the WDS inventory where StatCan kept "
                "the link; a table with only legacy_cansim_id was not matched.",
                "Liens seulement : lisez les chiffres d'un tableau avec les outils wds_ "
                "(product_id) et le texte avec statcan_daily_get_article. Les anciens numéros "
                "CANSIM sont associés aux tableaux actuels par l'inventaire WDS quand "
                "Statistique Canada a gardé le lien ; un tableau qui n'a que legacy_cansim_id "
                "n'a pas été associé.",
            ),
            lang=lang,
        ),
    )

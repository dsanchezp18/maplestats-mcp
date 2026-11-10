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

import asyncio
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
from bs4.element import NavigableString
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from maplestats_mcp.modules.statcan.daily import constants
from maplestats_mcp.modules.statcan.daily.schemas import (
    DailyArchiveEntry,
    DailyArchiveSearchResult,
    DailyArticle,
    DailyRelease,
    DailyReleaseList,
    DailyReleaseTableLink,
    ReleaseCalendarEntry,
    ReleaseCalendarResult,
    ReleaseFiles,
    ReleaseFilesResult,
    ReleaseHistory,
    ReleaseProduct,
    ReleaseSurvey,
    ReleaseTable,
    ReleaseTableData,
    ReleaseTableRow,
    ReleaseTablesResult,
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

    # Every word of the query, accents and case ignored, anywhere in the title or
    # reference period. A phrase match (before 2026-11-10) missed "gross domestic product
    # by industry provinces" against "Gross domestic product by industry: Provinces and
    # territories", and "provisional poverty estimates 2025", whose year is the period.
    words = _archive_words(query)
    scored: list[tuple[int, DailyArchiveEntry]] = []
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
        haystack = _fold(f"{title} {reference_period or ''}")
        score = sum(word in haystack for word in words)
        if words and not score:
            continue
        # Upcoming "meeting" entries carry url == "": no article yet, so no link
        # (prefixing the host would yield the bare home page).
        relative_url = item.get("url") or ""
        scored.append(
            (
                score,
                DailyArchiveEntry(
                    release_date=entry_date,
                    title=title,
                    reference_period=reference_period,
                    scheduled=entry_date >= today,
                    url=f"{_ARCHIVE_HOST}{relative_url}" if relative_url else None,
                ),
            )
        )

    best = max((score for score, _ in scored), default=0)
    note = None
    if best == len(words):
        matched = [entry for score, entry in scored if score == best]
    elif best >= max(2, (len(words) + 1) // 2):
        # No title holds every word: show the closest, and say so.
        matched = [entry for score, entry in scored if score == best]
        note = say(
            f"No release title holds every word of the query; these match {best} of "
            f"{len(words)}. Check the title is the release asked for.",
            f"Aucun titre de diffusion ne contient tous les mots de la requête ; ceux-ci en "
            f"contiennent {best} sur {len(words)}. Vérifiez que le titre est bien la "
            "diffusion demandée.",
        )
    else:
        matched = []
    matched.sort(key=lambda entry: entry.release_date, reverse=True)
    page = matched[:limit]
    return DailyArchiveSearchResult(
        query=query,
        entries=page,
        returned_count=len(page),
        total_matched=len(matched),
        note=note,
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
# Words a question adds that no Daily title carries ("When did StatCan publish ...?"),
# and short connecting words: an archive search matches the rest one by one.
_ARCHIVE_FILLER = frozenset(
    [
        "did",
        "does",
        "was",
        "were",
        "publish",
        "published",
        "statcan",
        "statistique",
        "statistics",
        "the",
        "of",
        "for",
        "in",
        "on",
        "and",
        "by",
        "a",
        "an",
        "to",
        "de",
        "du",
        "des",
        "la",
        "le",
        "les",
        "et",
        "en",
        "pour",
        "au",
        "aux",
        "d",
        "l",
    ]
)


def _query_words(query: str) -> list[str]:
    """The query's words, folded, without the ones that only ask the question."""
    return [w for w in re.findall(r"\w+", _fold(query)) if w not in _QUESTION_WORDS]


def _release_words(query: str) -> list[str]:
    """The words that name the release itself: no years, months or quarters."""
    return [w for w in _query_words(query) if not _YEAR.fullmatch(w) and w not in _PERIOD_WORDS]


def _archive_words(query: str) -> list[str]:
    """The words an archive entry's title or reference period must hold."""
    return [w for w in _query_words(query) if w not in _ARCHIVE_FILLER]


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


async def _archive_history(
    words: list[str],
    lang: str,
    today: date,
    start: date | None,
    end: date | None,
    seen: set[tuple[date, str]],
) -> list[ReleaseCalendarEntry]:
    """Past Daily releases matching every word, for the calendar's history mode.

    The schedule files hold the key indicators and catalogue products only. In the
    Maple Test (2026-11-10) "when were the provisional poverty estimates for 2025
    released" searched this calendar's history for "poverty" and found nothing,
    though The Daily released them on 2026-11-04: the archive has every release.
    """
    try:
        payload, _, _ = await _load_archive(lang)
    except (UpstreamError, UpstreamUnavailable):
        return []  # the schedule files' own matches stand without it
    entries: list[ReleaseCalendarEntry] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        when = _parse_archive_entry_date(item.get("date"))
        title = (item.get("title") or "").strip()
        if when is None or not title or (when, title) in seen:
            continue
        if (start is not None and when < start) or (end is not None and when > end):
            continue
        period = item.get("description") or None
        haystack = _fold(f"{title} {period or ''}")
        if not all(word in haystack for word in words):
            continue
        relative_url = item.get("url") or ""
        entries.append(
            ReleaseCalendarEntry(
                release_date=when,
                kind="daily_release",
                title=title,
                reference_period=period,
                scheduled=when >= today,
                url=f"{_ARCHIVE_HOST}{relative_url}" if relative_url else None,
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

    archive_words = _archive_words(query)
    if not upcoming_only and archive_words:
        seen = {(e.release_date, e.title) for e in matched}
        matched += await _archive_history(
            archive_words, lang, today, parsed_start, parsed_end, seen
        )
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


# Elements that separate words even when the HTML has no whitespace between them.
_BLOCK_TAGS = frozenset(
    {
        "br", "p", "div", "li", "ul", "ol", "tr", "td", "th", "table", "caption",
        "h1", "h2", "h3", "h4", "h5", "h6", "section", "header", "footer", "dt", "dd",
    }
)  # fmt: skip


_SCREEN_READER = frozenset({"wb-inv", "wb-invisible", "navaid"})
_INNER_PAREN_SPACE = re.compile(r"(?<=\() | (?=\))")


def _breaks(tag: Tag) -> bool:
    # Screen-reader text ("Catalogue number" before "71-001-X", in span.wb-inv,
    # span.wb-invisible or span.navaid depending on the year) is a separate phrase
    # with no space in the HTML around it.
    return tag.name in _BLOCK_TAGS or not _SCREEN_READER.isdisjoint(tag.get("class") or [])


def _text(element: Tag) -> str:
    """An element's text with inline markup joined as written, on one line.

    `get_text(" ")` puts a space at every tag boundary, and Daily articles wrap the
    sign and first digit of a negative number in <span class="nowrap">: the January
    2018 LFS release (dq180209a) has `(<span class="nowrap">-1</span>37,000)`, which
    came out as "( -1 37,000)". Checked on releases from 2013 to 2026, English and
    French: inline tags (span, sup, strong, a, abbr) never stand for a word break,
    and superscripts are typographic ("1<sup>er</sup>", "n<sup>o</sup>"), so they
    are joined as written; only block elements and <br> separate words. The Unicode
    minus (U+2212) is written as an ASCII hyphen-minus so a number reads the same
    whatever the page used. No-break spaces (French thousands, "5,9 %") become
    plain spaces, as before.
    """
    parts: list[str] = []
    for node in element.descendants:
        if isinstance(node, Tag):
            if _breaks(node):
                parts.append(" ")
        elif type(node) is NavigableString:
            # Text right after a closing block element ("</p>tail") is a new word too.
            before = node.previous_sibling
            if isinstance(before, Tag) and _breaks(before):
                parts.append(" ")
            parts.append(str(node))
    text = _clean("".join(parts).replace("\u2212", "-"))
    # A break at the edge of a parenthesis ("(<span class=wb-inv>...") is not a space.
    return _INNER_PAREN_SPACE.sub("", text)


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
            items = [_text(item) for item in element.find_all("li")]
            text = "\n".join(f"- {item}" for item in items if item)
        else:
            text = _text(element)
        if text:
            sections[-1]["parts"].append(text)

    for child in body.children:
        if not isinstance(child, Tag):
            continue
        classes = child.get("class") or []
        if child.name == "h2" and "chartt" not in classes:
            sections.append({"heading": _text(child), "parts": []})
        elif child.name in ("p", "ul", "ol") and "sd-release-date" not in classes:
            add_text(child)
        elif child.name == "div" and "sd-noteuser" in classes:
            title = child.find(["h2", "h3"])
            note = _text(title) if isinstance(title, Tag) else "Note to readers"
            sections.append({"heading": note, "parts": []})
            panel = child.find("div", class_="panel-body")
            for element in (panel if isinstance(panel, Tag) else child).find_all(
                ["p", "h3", "h4", "ul", "ol"], recursive=False
            ):
                if element.name in ("h3", "h4"):
                    sub = _text(element)
                    sections.append({"heading": f"{note}: {sub}", "parts": []})
                else:
                    add_text(element)
        elif child.name == "div":
            chart = child.find("h2", class_="chartt")
            if isinstance(chart, Tag):
                charts.append(_text(chart))

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
        text = _text(link)
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
        "title": _text(heading),
        "release_date": release_date,
        "archived": main.find("section", id="archived") is not None,
        "summary": meta("dcterms.description") or meta("description"),
        "sections": built,
        "charts": charts,
        "tables": [
            {"table_id": table_id, "product_id": product_id}
            for product_id, table_id in tables.items()
        ],
        "release_tables": _release_table_links(body, url),
        "pdf_url": nav.get("pdf"),
        "tables_page_url": nav.get("tables"),
        "related_info_url": nav.get("info"),
        "previous_release_url": nav.get("previous"),
        "links": [{"text": text, "url": href} for href, text in links.items()],
        "word_count": sum(len(section["text"].split()) for section in built),
    }


async def _article_html(article_id: str, url: str, tool: str) -> tuple[str, bool]:
    """The article page's HTML, cached; a 404 is NotFound naming the article."""

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise NotFound(
                    say(
                        f"statcan_daily:{tool}: StatCan has no Daily article {article_id} "
                        f"({url}). Take the id from statcan_daily_get_releases or "
                        "statcan_daily_search_archive.",
                        f"statcan_daily:{tool} : Statistique Canada n'a pas d'article "
                        f"{article_id} dans Le Quotidien ({url}). Prenez l'identifiant dans "
                        "statcan_daily_get_releases ou statcan_daily_search_archive.",
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

    lang = "fr" if url.endswith("-fra.htm") else "en"
    return await cached_fetch(
        f"statcan-daily:article:{article_id}:{lang}", constants.CACHE_TTL_ARTICLE_SECONDS, fetch
    )


async def get_article(article: str, *, lang: str = "en") -> DailyArticle:
    """Read one Daily article in full: its sections, tables, charts and PDF link."""
    use_lang(lang)
    article_id, url = _article_url(article, lang)
    html, was_cached = await _article_html(article_id, url, "get_article")
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
                "Text only: charts are listed by title. The release's own tables "
                "(release_tables) hold the values as first published: read their rows with "
                "statcan_daily_get_release_tables. For today's revised figures use the wds_ "
                "tools on the tables listed in `tables`.",
                "Texte seulement : les graphiques sont donnés par titre. Les tableaux du "
                "communiqué (release_tables) contiennent les valeurs telles que publiées ce "
                "jour-là : lisez leurs lignes avec statcan_daily_get_release_tables. Pour les "
                "chiffres révisés d'aujourd'hui, utilisez les outils wds_ sur les tableaux de "
                "`tables`.",
            ),
            lang=lang,
        ),
    )


# The release's own tables. Checked live 2026-11-07 on LFS, CPI and GDP releases from
# 2012, 2013, 2015, 2016, 2018, 2019, 2021, 2024 and 2026, English and French: the
# article links each one as a button (div.tablebtn, the label in span.sd-tablet,
# "Table 3<br>Title"); the file is t001a-eng.htm from about 2014 and
# t131206a001-eng.htm (day, article letter, number) before. Each table page has one
# <h1> ("Table 3<br>Title") and one <table>: a header row of <th id="hd...">, then in
# <tbody> a units row of <th id="uom..."> (colspan in 2012), then one row per line with
# a stub <th class="stubN"> (N = indent level) and data cells whose `headers` attribute
# names the stub, column and unit ids. A line with no values is a heading for the
# lines below ("Alberta" in LFS Table 3). In 2012 the first data cells of a row are
# <th class="data">, and the page has no <main>. Negative values are written with an
# ASCII hyphen; French uses no-break spaces for thousands and a decimal comma. Under
# the table, div.tableft-end lists the symbol legend ("..." not applicable), Note(s)
# and Source(s); numbered notes sit there too (2012) or in <section id="fn01"> pop-ups
# (2013 on). Pages from about 2014 on also link a CSV of the same table.
_RELEASE_TABLE_FILE = re.compile(r"(?:^|/)t(?:\d{3}[a-z]+|\d{6}[a-z]+\d{3})-(?:eng|fra)\.htm$")
_TABLE_NUMBER = re.compile(r"^((?:Table|Tableau)\s*\d+[A-Za-z]?)\b\s*(.*)$", re.DOTALL)
_STUB_LEVEL = re.compile(r"^stub(\d+)$")
_NUMBER_EN = re.compile(r"([+-]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*%?\s*[A-Za-z]{0,2}")
_NUMBER_FR = re.compile(r"([+-]?)(\d{1,3}(?: \d{3})+|\d+)(,\d+)?\s*%?\s*[A-Za-z]{0,2}")


def _release_table_links(container: Tag, url: str) -> list[dict[str, Any]]:
    """The release's own table pages an article links, in page order."""
    found: dict[str, dict[str, Any]] = {}
    for link in container.find_all("a", href=True):
        href = str(link["href"]).split("?")[0].split("#")[0]
        if not _RELEASE_TABLE_FILE.search(href):
            continue
        absolute = _absolute(url, href)
        if absolute in found:
            continue
        label = link.find("span", class_="sd-tablet")
        source = label if isinstance(label, Tag) else link
        # Footnote markers in the label ("NAICS<sup>1</sup>") are not part of the title.
        text = _text(_without_sups(source))
        match = _TABLE_NUMBER.match(text)
        number, title = (match.group(1), match.group(2).strip()) if match else (None, text)
        found[absolute] = {"number": number, "title": title or text, "url": absolute}
    return list(found.values())


def _without_sups(element: Tag) -> Tag:
    copy = BeautifulSoup(str(element), "html.parser")
    for sup in copy.find_all("sup"):
        sup.extract()
    return copy


def _number(text: str, lang: str) -> float | None:
    pattern = _NUMBER_FR if lang == "fr" else _NUMBER_EN
    match = pattern.fullmatch(text)
    if match is None:
        return None
    sign, whole, fraction = match.groups()
    whole = whole.replace(",", "").replace(" ", "")
    fraction = (fraction or "").replace(",", ".")
    return float(f"{sign}{whole}{fraction}")


def _note_refs(element: Tag) -> list[str]:
    """Take footnote markers out of a cell or heading and return their numbers."""
    refs: list[str] = []
    for marker in element.find_all(["sup", "a"]):
        if not isinstance(marker, Tag) or marker.decomposed or marker.parent is None:
            continue
        classes = marker.get("class") or []
        href = str(marker.get("href") or "")
        if marker.name == "sup" or "sd-tablefnref" in classes or href.startswith("#"):
            ref = _text(marker).strip(".")
            if ref:
                refs.append(ref)
            marker.extract()
    return refs


def _table_notes(root: Tag) -> list[str]:
    colon = say(":", " :")
    notes: list[str] = []
    footer = root.find("div", class_="tableft-end")
    if isinstance(footer, Tag):
        for item in footer.find_all("div", class_="tableft-item"):
            parts = [
                text for part in item.find_all("div", recursive=False) if (text := _text(part))
            ]
            if not parts:
                continue
            head, rest = parts[0], " ".join(parts[1:])
            if rest and not head.endswith((":", ".")):
                head = f"{head}{colon}"
            notes.append(f"{head} {rest}".strip())
    for section in root.find_all("section", id=re.compile(r"^fn\d+")):
        title_tag = section.find(["h2", "h3"])
        name = _text(title_tag) if isinstance(title_tag, Tag) else str(section["id"])
        if isinstance(title_tag, Tag):
            title_tag.extract()
        text = _text(section)
        if text:
            notes.append(f"{name}{colon} {text}")
    return notes


def _parse_release_table(html: str, url: str, lang: str) -> dict[str, Any]:
    """One release table page as metadata and tidy rows (layout described above)."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all(["script", "style"]):
        script.extract()
    root = soup.find("main") or soup.body or soup
    table = root.find("table") if isinstance(root, Tag) else None
    if not isinstance(root, Tag) or not isinstance(table, Tag):
        raise UpstreamError(
            say(
                f"statcan_daily:get_release_tables: {url} has no table; StatCan may have "
                "changed the page layout.",
                f"statcan_daily:get_release_tables : {url} ne contient pas de tableau ; "
                "Statistique Canada a peut-être changé la page.",
            )
        )

    heading = root.find("h1")
    number, title = None, ""
    if isinstance(heading, Tag):
        _note_refs(heading)
        match = _TABLE_NUMBER.match(_text(heading))
        number = match.group(1) if match else None
        title = match.group(2).strip() if match else _text(heading)
    caption = table.find(class_="CaptionTitle") or table.find("caption")
    if isinstance(caption, Tag):
        _note_refs(caption)
        title = _text(caption) or title
    csv_url = next(
        (
            _absolute(url, str(link["href"]))
            for link in root.find_all("a", href=True)
            if str(link["href"]).split("?")[0].endswith(".csv")
        ),
        None,
    )

    # Every heading cell by id: columns (hd...), units (uom...) and row stubs.
    labels: dict[str, tuple[str, list[str]]] = {}
    for cell in table.find_all(["th", "td"], id=True):
        if not cell.get("headers"):
            refs = _note_refs(cell)
            labels[str(cell["id"])] = (_text(cell), refs)
    head_rows = table.thead.find_all("tr") if isinstance(table.thead, Tag) else []
    positional = [_text(cell) for cell in (head_rows[-1].find_all("th")[1:] if head_rows else [])]
    columns = list(dict.fromkeys(text for key, (text, _) in labels.items() if key.startswith("hd")))
    units = list(
        dict.fromkeys(text for key, (text, _) in labels.items() if key.startswith("uom") and text)
    )

    rows: list[dict[str, Any]] = []
    group: str | None = None
    stack: list[tuple[int, str]] = []
    body = table.find("tbody")
    for tr in (body if isinstance(body, Tag) else table).find_all("tr"):
        if tr.find_parent("thead") is not None:
            continue
        cells = [
            cell
            for cell in tr.find_all(["td", "th"], recursive=False)
            if cell.get("headers") or cell.name == "td" or "data" in (cell.get("class") or [])
        ]
        stub = next(
            (cell for cell in tr.find_all("th", recursive=False) if cell not in cells), None
        )
        if not cells or not isinstance(stub, Tag):
            continue  # the units row
        stub_refs = _note_refs(stub)
        label = _text(stub)
        values = [(cell, _note_refs(cell)) for cell in cells]
        texts = [_text(cell) for cell, _ in values]
        if not label:
            continue
        if not any(texts):
            group, stack = label, []
            continue
        level = next(
            (
                int(found.group(1))
                for cls in stub.get("class") or []
                if (found := _STUB_LEVEL.match(str(cls)))
            ),
            1,
        )
        while stack and stack[-1][0] >= level:
            stack.pop()
        parents = [text for _, text in stack]
        stack.append((level, label))
        for index, ((cell, refs), text) in enumerate(zip(values, texts, strict=True)):
            if not text:
                continue
            ids = cell.get_attribute_list("headers")
            column_parts = [labels[i] for i in ids if i.startswith("hd") and i in labels]
            unit_parts = [labels[i][0] for i in ids if i.startswith("uom") and i in labels]
            column = " - ".join(part for part, _ in column_parts) or (
                positional[index] if index < len(positional) else ""
            )
            column_refs = [ref for _, part_refs in column_parts for ref in part_refs]
            rows.append(
                {
                    "group": group,
                    "parents": parents,
                    "row": label,
                    "column": column,
                    "unit": " - ".join(part for part in unit_parts if part) or None,
                    "value_text": text,
                    "value": _number(text, lang),
                    "note_refs": list(dict.fromkeys(stub_refs + column_refs + refs)),
                }
            )

    return {
        "number": number,
        "title": title,
        "url": url,
        "csv_url": csv_url,
        "units": units,
        "columns": columns or positional,
        "notes": _table_notes(root),
        "rows": rows,
    }


def _row_matches(row: dict[str, Any], words: list[str]) -> bool:
    """Every query word starts a word of the labels ('employment' is not 'unemployment')."""
    fields = [row["group"] or "", *row["parents"], row["row"], row["column"], row["unit"] or ""]
    labels = re.findall(r"\w+", _fold(" ".join(fields)))
    return all(any(label.startswith(word) for label in labels) for word in words)


def _table_position(link: dict[str, Any], position: int) -> int:
    found = re.search(r"\d+", link["number"] or "")
    return int(found.group(0)) if found else position


async def get_release_tables(
    article: str,
    *,
    lang: str = "en",
    tables: list[int] | None = None,
    search: str = "",
    limit: int = constants.RELEASE_TABLE_ROWS_DEFAULT,
) -> ReleaseTablesResult:
    """Read a Daily release's own tables (values as first published) as tidy rows."""
    use_lang(lang)
    if limit < 1 or limit > constants.RELEASE_TABLE_ROWS_MAX:
        raise InvalidInput(
            say(
                "statcan_daily:get_release_tables: limit must be 1 to "
                f"{constants.RELEASE_TABLE_ROWS_MAX}, got {limit}.",
                "statcan_daily:get_release_tables : limit doit être entre 1 et "
                f"{constants.RELEASE_TABLE_ROWS_MAX}, reçu {limit}.",
            )
        )
    article_id, url = _article_url(article, lang)
    html, article_cached = await _article_html(article_id, url, "get_release_tables")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("main") or soup.body or soup
    links = _release_table_links(root, url) if isinstance(root, Tag) else []
    heading = root.find("h1") if isinstance(root, Tag) else None
    issued = soup.find("meta", attrs={"name": "dcterms.issued"})
    try:
        release_date = (
            date.fromisoformat(str(issued.get("content")).strip())
            if isinstance(issued, Tag)
            else None
        )
    except ValueError:
        release_date = None

    chosen = links
    if tables:
        wanted = set(tables)
        chosen = [
            link
            for position, link in enumerate(links, start=1)
            if _table_position(link, position) in wanted
        ]
        if not chosen:
            available = ", ".join(link["number"] or link["title"] for link in links) or "-"
            raise NotFound(
                say(
                    f"statcan_daily:get_release_tables: {article_id} has no table "
                    f"{sorted(wanted)}; its tables are: {available}.",
                    f"statcan_daily:get_release_tables : {article_id} n'a pas de tableau "
                    f"{sorted(wanted)} ; ses tableaux sont : {available}.",
                )
            )

    async def read(link: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        day, name = link["url"].rsplit("/", 2)[-2:]
        page, cached = await _fetch_html(
            link["url"],
            f"statcan-daily:release-table:{day}:{name}",
            constants.CACHE_TTL_ARTICLE_SECONDS,
            "get_release_tables",
            missing_ok=False,
        )
        parsed = _parse_release_table(page or "", link["url"], lang)
        parsed["number"] = parsed["number"] or link["number"]
        parsed["title"] = parsed["title"] or link["title"]
        return parsed, cached

    read_tables = await asyncio.gather(*(read(link) for link in chosen))
    words = re.findall(r"\w+", _fold(search))
    budget = limit
    total = 0
    built: list[ReleaseTableData] = []
    for parsed, _ in read_tables:
        matched = [row for row in parsed.pop("rows") if _row_matches(row, words)]
        kept = matched[:budget]
        budget -= len(kept)
        total += len(matched)
        built.append(
            ReleaseTableData(
                **parsed,
                total_rows=len(matched),
                returned_count=len(kept),
                rows=[ReleaseTableRow(**row) for row in kept],
            )
        )
    returned = sum(table.returned_count for table in built)
    truncated = returned < total
    note = None
    if not links:
        note = say(
            "This release links no tables of its own; for its data use "
            "statcan_daily_get_release_files and the wds_ tools.",
            "Ce communiqué ne renvoie à aucun tableau qui lui soit propre ; pour ses données, "
            "utilisez statcan_daily_get_release_files et les outils wds_.",
        )
    elif truncated:
        note = say(
            f"Showing {returned} of {total} values (limit={limit}). Narrow with tables=[n] "
            "or search (e.g. 'Alberta employment'), or raise limit.",
            f"{returned} valeurs sur {total} (limit={limit}). Précisez avec tables=[n] ou "
            "search (p. ex. « Alberta emploi »), ou augmentez limit.",
        )
    elif total == 0 and words:
        note = say(
            f"No row, column or heading matches {search!r}.",
            f"Aucune ligne, colonne ni rubrique ne correspond à {search!r}.",
        )
    return ReleaseTablesResult(
        article_id=article_id,
        article_url=url,
        title=_text(heading) if isinstance(heading, Tag) else None,
        release_date=release_date,
        available_tables=[DailyReleaseTableLink(**link) for link in links],
        tables=built,
        total_rows=total,
        returned_count=returned,
        truncated=truncated,
        note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=chosen[0]["url"] if len(chosen) == 1 else url,
            cached=article_cached and all(cached for _, cached in read_tables),
            schema_name="statcan_daily.ReleaseTablesResult",
            limits=say(
                "Values as StatCan first published them in this release, before later "
                "revisions, rounded as on the page; for current figures use the wds_ tools.",
                "Valeurs telles que Statistique Canada les a publiées dans ce communiqué, avant "
                "les révisions ultérieures, arrondies comme dans la page ; pour les chiffres "
                "actuels, utilisez les outils wds_.",
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

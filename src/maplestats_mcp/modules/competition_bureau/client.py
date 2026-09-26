"""Client for the Competition Bureau's merger-review reports.

Checked live 2026-09-25: both reports are single HTML tables with every
row in the page (no script, no pagination):

1. The weekly report has 5 columns (parties, opened date, concluded date
   or "Ongoing", NAICS, outcome); the archive has 4 (parties, NAICS,
   result, month as YYYY-MM). Every date, NAICS and outcome cell matched
   its expected pattern; the table's last row is a one-cell footnote.
2. The French pages hold the same rows with French outcome codes (CDP for
   ARC, "en cours" for Ongoing), so codes are read from the English pages
   and only the labels are translated.
3. Neither page covers May-October 2023: the archive ends at 2023-04 and
   the weekly report starts with reviews opened in November 2023.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import date

import httpx
from bs4 import BeautifulSoup

from maplestats_mcp.modules.competition_bureau import constants
from maplestats_mcp.modules.competition_bureau.schemas import MergerReview, MergerSearchResult
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _label(outcome: str, lang: str) -> str:
    english, french = constants.OUTCOMES.get(outcome, (outcome, outcome))
    return french if lang == "fr" else english


def _rows(page: str) -> list[list[str]]:
    soup = BeautifulSoup(page, "html.parser")
    table = soup.find("table")
    if table is None:
        raise UpstreamError("competition_bureau: the merger report no longer has its table.")
    rows = []
    for tr in table.find_all("tr"):
        cells = [" ".join(c.get_text(" ").split()) for c in tr.find_all(["td", "th"])]
        if len(cells) >= 4 and cells[0] and not cells[0].startswith("Parties"):
            rows.append(cells)
    return rows


def parse_current(page: str) -> list[MergerReview]:
    reviews = []
    for parties, opened, concluded, naics, outcome in (r[:5] for r in _rows(page)):
        reviews.append(
            MergerReview(
                parties=parties,
                opened=date.fromisoformat(opened) if _DAY.match(opened) else None,
                concluded=date.fromisoformat(concluded) if _DAY.match(concluded) else None,
                concluded_month=concluded[:7] if _DAY.match(concluded) else None,
                naics=naics or None,
                outcome=outcome,
                outcome_label=_label(outcome, "en"),
                report="current",
            )
        )
    return reviews


def parse_archive(page: str) -> list[MergerReview]:
    return [
        MergerReview(
            parties=parties,
            concluded_month=month or None,
            naics=naics or None,
            outcome=outcome,
            outcome_label=_label(outcome, "en"),
            report="archive",
        )
        for parties, naics, outcome, month in (r[:4] for r in _rows(page))
    ]


async def _page(url: str) -> str:
    await _LIMITER.acquire()
    try:
        response = await get_raw(url, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(
            f"competition_bureau: {url} returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"competition_bureau: {url} did not respond in time.") from exc
    if len(response.content) > constants.MAX_PAGE_BYTES:
        raise UpstreamError(f"competition_bureau: {url} is larger than expected.")
    return response.text


async def _all_reviews() -> tuple[list[MergerReview], bool]:
    async def fetch() -> list[MergerReview]:
        current, archive = await asyncio.gather(
            _page(constants.CURRENT_URL), _page(constants.ARCHIVE_URL)
        )
        return parse_current(current) + parse_archive(archive)

    return await cached_fetch("competition-bureau:reviews", constants.CACHE_TTL_SECONDS, fetch)


async def search_mergers(
    party: str = "",
    *,
    naics: str | None = None,
    outcome: str | None = None,
    concluded_from: str | None = None,
    concluded_to: str | None = None,
    include_ongoing: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> MergerSearchResult:
    """Merger reviews matching every word of `party` and the other filters."""
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(
            f"competition_bureau: limit must be between 1 and {constants.LIMIT_MAX}, got {limit}."
        )
    if outcome is not None and outcome not in constants.OUTCOMES:
        raise InvalidInput(
            f"competition_bureau: outcome must be one of {list(constants.OUTCOMES)}, got {outcome!r}."
        )
    for name, value in (("concluded_from", concluded_from), ("concluded_to", concluded_to)):
        if value is not None and not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", value):
            raise InvalidInput(f"competition_bureau: {name} must be YYYY-MM or YYYY-MM-DD.")
    reviews, cached = await _all_reviews()
    words = party.lower().split()
    prefix = (naics or "").strip()
    # Bounds compare months: the archive has no day, so a day is ignored.
    start = (concluded_from or "")[:7]
    end = (concluded_to or "")[:7]
    matched = [
        r
        for r in reviews
        if all(w in r.parties.lower() for w in words)
        and (not prefix or (r.naics or "").startswith(prefix))
        and (outcome is None or r.outcome == outcome)
        and (include_ongoing or r.outcome != "Ongoing")
        and (not start or (r.concluded_month or "") >= start)
        and (not end or (r.concluded_month is not None and r.concluded_month <= end))
    ]
    # Newest first: ongoing reviews by opened date, concluded ones by month.
    matched.sort(key=lambda r: (r.concluded_month or "9999", r.opened or date.min), reverse=True)
    shown = [r.model_copy(update={"outcome_label": _label(r.outcome, lang)}) for r in matched]
    return MergerSearchResult(
        reviews=shown[:limit],
        returned_count=min(limit, len(shown)),
        total_matched=len(matched),
        outcome_counts=dict(Counter(r.outcome for r in matched)),
        outcome_legend={code: _label(code, lang) for code in constants.OUTCOMES},
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.CURRENT_URL if lang == "en" else constants.FR_URLS["current"],
            cached=cached,
            schema_name="competition_bureau.MergerSearchResult",
            freshness="weekly report updated on or after each Tuesday; archive fixed",
            coverage="reviews opened since 2023-11 (weekly) and concluded 2015-01 to 2023-04",
            limits=(
                "Parties may ask the Bureau to delay or omit publication; "
                "May-October 2023 is covered by neither report."
            ),
        ),
    )

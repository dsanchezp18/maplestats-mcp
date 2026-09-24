"""Client for Senate of Canada votes, parsed from sencanada.ca HTML."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

import httpx
from bs4 import BeautifulSoup, Tag

from maple_data_mcp.modules.senate import constants
from maple_data_mcp.modules.senate.schemas import (
    SenateVote,
    SenateVoteList,
    SenateVoteSummary,
    SenatorBallot,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import get_raw
from maple_data_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SESSION = re.compile(r"^\d{2}-\d$")
_BILL = re.compile(r"\b([CS]-\d{1,4}[A-Z]?)\b")
_COUNT = re.compile(r"(Yeas|Nays|Abstentions|Pour|Contre|Abstentions?)\s*:\s*(\d+)", re.IGNORECASE)
_FRESHNESS = "sencanada.ca, updated after each sitting; cached 1 hour"


async def _page(path: str) -> tuple[str, bool]:
    url = f"{constants.BASE_URL}{path}"

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"senate: no page at {url}.") from exc
            raise UpstreamError(f"senate: {url} returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"senate: {url} could not be reached.") from exc
        return response.text

    return await cached_fetch(f"senate:{path}", constants.CACHE_TTL_SECONDS, fetch)


def _clean(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ").split()) if tag else ""


def _check_session(session: str) -> str:
    if not _SESSION.match(session.strip()):
        raise InvalidInput(f"session must look like '45-1', got {session!r}.")
    return session.strip()


def parse_vote_list(
    html: str, session: str, lang: Lang
) -> tuple[list[SenateVoteSummary], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    list_path = constants.LIST_PATHS[lang]
    hrefs = [str(a["href"]) for a in soup.find_all("a", href=True) if isinstance(a, Tag)]
    tails = [h.rstrip("/").rsplit("/", 1)[-1] for h in hrefs if h.startswith(list_path)]
    sessions = sorted({tail for tail in tails if _SESSION.match(tail)})
    table = soup.find("table", id="votes-table")
    if not isinstance(table, Tag):
        raise UpstreamError("senate: votes page has no votes table; the layout may have changed.")
    votes = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        link = row.select_one("a.vote-web-title-link")
        if len(cells) < 4 or link is None:
            continue
        href = str(link["href"])
        counts = {k.lower(): int(v) for k, v in _COUNT.findall(_clean(cells[1]))}
        title = _clean(link)
        bill = _clean(cells[2]) or None
        try:
            day = date.fromisoformat(_clean(cells[0])[:10])
        except ValueError:
            day = None
        votes.append(
            SenateVoteSummary(
                vote_id=int(href.rstrip("/").split("/")[-2]),
                session=session,
                date=day,
                title=title,
                bill=bill,
                result=_clean(cells[3]) or None,
                yeas=counts.get("yeas", counts.get("pour")),
                nays=counts.get("nays", counts.get("contre")),
                abstentions=counts.get("abstentions"),
                url=f"{constants.BASE_URL}{href}",
            )
        )
    votes.sort(key=lambda v: (v.date or date.min, v.vote_id), reverse=True)
    return votes, sessions


async def list_votes(
    *,
    session: str | None = None,
    keyword: str | None = None,
    bill: str | None = None,
    lang: Lang = "en",
    limit: int = 50,
) -> SenateVoteList:
    if limit < 1 or limit > 500:
        raise InvalidInput(f"limit must be between 1 and 500, got {limit}.")
    list_path = constants.LIST_PATHS[lang]
    path = f"{list_path}{_check_session(session)}" if session else list_path
    html, cached = await _page(path)
    votes, sessions = parse_vote_list(html, session or "", lang)
    current = session or (sessions[-1] if sessions else "")
    for vote in votes:
        vote.session = current
    if keyword:
        needle = keyword.strip().lower()
        votes = [v for v in votes if needle in v.title.lower()]
    if bill:
        wanted = bill.strip().upper()
        votes = [v for v in votes if (v.bill or "").upper() == wanted]
    kept = votes[:limit]
    return SenateVoteList(
        session=current,
        votes=kept,
        total_matches=len(votes),
        returned_count=len(kept),
        sessions_available=sessions,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.BASE_URL}{path}",
            cached=cached,
            schema_name="senate.SenateVoteList",
            freshness=_FRESHNESS,
        ),
    )


_VOTE_COLUMNS = {"en": ("Yea", "Nay", "Abstention"), "fr": ("Pour", "Contre", "Abstention")}


def parse_vote(
    html: str, vote_id: int, session: str, url: str, lang: Lang, cached: bool = False
) -> SenateVote:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="sc-vote-details-table")
    if not isinstance(table, Tag):
        raise NotFound(f"senate: vote {vote_id} in {session} has no senator table.")
    labels = _VOTE_COLUMNS[lang]
    ballots = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        # The marked column sorts first: data-order="aaa" (confirmed live).
        marks = [c.get("data-order") == "aaa" for c in cells[3:6]]
        vote = next((label for label, marked in zip(labels, marks, strict=True) if marked), "")
        ballots.append(
            SenatorBallot(
                senator=_clean(cells[0]),
                affiliation=_clean(cells[1]) or None,
                province=_clean(cells[2]) or None,
                vote=vote,
            )
        )
    title = _clean(soup.select_one(".sc-vote-details-box-title"))
    bill_match = _BILL.search(_clean(soup.select_one(".sc-vote-details-box-related")) or title)
    return SenateVote(
        vote_id=vote_id,
        session=session,
        # "45<sup>th</sup>" would otherwise read "45 th".
        date_text=re.sub(
            r"(\d) (st|nd|rd|th|e|re)\b",
            r"\1\2",
            _clean(soup.select_one(".sc-vote-details-box-date")),
        )
        or None,
        title=title,
        bill=bill_match.group(1) if bill_match else None,
        yeas=sum(b.vote == labels[0] for b in ballots),
        nays=sum(b.vote == labels[1] for b in ballots),
        abstentions=sum(b.vote == labels[2] for b in ballots),
        ballots=ballots,
        url=url,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="senate.SenateVote",
            freshness=_FRESHNESS,
        ),
    )


async def get_vote(vote_id: int, session: str, *, lang: Lang = "en") -> SenateVote:
    if vote_id < 1:
        raise InvalidInput(f"vote_id must be positive, got {vote_id}.")
    path = f"{constants.DETAIL_PATHS[lang]}{vote_id}/{_check_session(session)}"
    html, cached = await _page(path)
    return parse_vote(html, vote_id, session, f"{constants.BASE_URL}{path}", lang, cached)

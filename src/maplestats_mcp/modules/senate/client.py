"""Client for Senate of Canada votes, parsed from sencanada.ca HTML."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Literal

import httpx
from bs4 import BeautifulSoup, Tag

from maplestats_mcp.modules.senate import constants
from maplestats_mcp.modules.senate.schemas import (
    SenateVote,
    SenateVoteList,
    SenateVoteSummary,
    SenatorBallot,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import fr_or_en, lang_error
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SESSION = re.compile(r"^\d{2}-\d$")
_BILL = re.compile(r"\b([CS]-\d{1,4}[A-Z]?)\b")
_COUNT = re.compile(r"(Yeas|Nays|Pour|Contre|Abstentions?)\s*:\s*(\d+)", re.IGNORECASE)
_FRESHNESS = "sencanada.ca, updated after each sitting; cached 1 hour"
_FRESHNESS_FR = "sencanada.ca, mis à jour après chaque séance ; mis en cache 1 heure"


async def _page(path: str, lang: str = "en") -> tuple[str, bool]:
    url = f"{constants.BASE_URL}{path}"

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise lang_error(
                    NotFound, lang, f"senate: no page at {url}.", f"senate : aucune page à {url}."
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"senate: {url} returned HTTP {status}.",
                f"senate : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"senate: {url} could not be reached.",
                f"senate : {url} est injoignable.",
            ) from exc
        return response.text

    return await cached_fetch(f"senate:{path}", constants.CACHE_TTL_SECONDS, fetch)


def _clean(tag: Tag | None) -> str:
    return " ".join(tag.get_text(" ").split()) if tag else ""


def _fold(text: str) -> str:
    """Lower-case and drop accents, so "troisieme" finds "Troisième"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _session_key(session: str) -> tuple[int, int]:
    parliament, number = session.split("-")
    return int(parliament), int(number)


def _check_session(session: str, lang: str = "en") -> str:
    if not _SESSION.match(session.strip()):
        raise lang_error(
            InvalidInput,
            lang,
            f"session must look like '45-1', got {session!r}.",
            f"session doit avoir la forme « 45-1 » ; reçu {session!r}.",
        )
    return session.strip()


def parse_vote_list(
    html: str, session: str, lang: Lang
) -> tuple[list[SenateVoteSummary], list[str]]:
    """Votes and the sessions linked from the page.

    Confirmed live 2026-10-03: a session the site has no votes list for
    (41-2 and earlier) still answers HTTP 200 with the session links but
    no table (it even links itself), so a missing table on a session
    before constants.FIRST_SESSION is a bad session, not a layout change.
    """
    soup = BeautifulSoup(html, "html.parser")
    list_path = constants.LIST_PATHS[lang]
    hrefs = [str(a["href"]) for a in soup.find_all("a", href=True) if isinstance(a, Tag)]
    tails = [h.rstrip("/").rsplit("/", 1)[-1] for h in hrefs if h.startswith(list_path)]
    sessions = sorted({tail for tail in tails if _SESSION.match(tail)})
    table = soup.find("table", id="votes-table")
    if not isinstance(table, Tag):
        if session and _session_key(session) < _session_key(constants.FIRST_SESSION):
            first = _session_key(constants.FIRST_SESSION)
            listed = [s for s in sessions if _session_key(s) >= first]
            raise lang_error(
                InvalidInput,
                lang,
                f"senate: sencanada.ca has no votes list for session {session}; "
                f"sessions with votes: {', '.join(listed) or constants.FIRST_SESSION + ' on'}.",
                f"senate : sencanada.ca n'a pas de liste des votes pour la session {session} ; "
                "sessions avec des votes : "
                f"{', '.join(listed) or 'à partir de ' + constants.FIRST_SESSION}.",
            )
        raise lang_error(
            UpstreamError,
            lang,
            "senate: votes page has no votes table; the layout may have changed.",
            "senate : la page des votes n'a pas de tableau des votes ; la présentation a "
            "peut-être changé.",
        )
    votes = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        link = row.select_one("a.vote-web-title-link")
        if len(cells) < 4 or link is None:
            continue
        href = str(link["href"])
        # The French cell says "Abstention: 3" (singular, confirmed live
        # 2026-10-03), the English one "Abstentions: 3".
        counts = {k.lower().removesuffix("s"): int(v) for k, v in _COUNT.findall(_clean(cells[1]))}
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
                yeas=counts.get("yea", counts.get("pour")),
                nays=counts.get("nay", counts.get("contre")),
                abstentions=counts.get("abstention"),
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
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and 500, got {limit}.",
            f"limit doit être compris entre 1 et 500 ; reçu {limit}.",
        )
    list_path = constants.LIST_PATHS[lang]
    path = f"{list_path}{_check_session(session, lang)}" if session else list_path
    html, cached = await _page(path, lang)
    votes, sessions = parse_vote_list(html, session or "", lang)
    current = session or (sessions[-1] if sessions else "")
    for vote in votes:
        vote.session = current
    if keyword:
        needle = _fold(keyword.strip())
        votes = [v for v in votes if needle in _fold(v.title)]
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
            freshness=fr_or_en(lang, _FRESHNESS, _FRESHNESS_FR),
            lang=lang,
        ),
    )


_VOTE_COLUMNS = {"en": ("Yea", "Nay", "Abstention"), "fr": ("Pour", "Contre", "Abstention")}


def parse_vote(
    html: str, vote_id: int, session: str, url: str, lang: Lang, cached: bool = False
) -> SenateVote:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="sc-vote-details-table")
    if not isinstance(table, Tag):
        raise lang_error(
            NotFound,
            lang,
            f"senate: vote {vote_id} in {session} has no senator table.",
            f"senate : le vote {vote_id} de la session {session} n'a pas de tableau des sénateurs.",
        )
    labels = _VOTE_COLUMNS[lang]
    ballots = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        # The marked column sorts first: data-order="aaa" (confirmed live).
        marks = [c.get("data-order") == "aaa" for c in cells[3:6]]
        vote = next((label for label, marked in zip(labels, marks, strict=True) if marked), None)
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
            freshness=fr_or_en(lang, _FRESHNESS, _FRESHNESS_FR),
            lang=lang,
        ),
    )


async def get_vote(vote_id: int, session: str, *, lang: Lang = "en") -> SenateVote:
    if vote_id < 1:
        raise lang_error(
            InvalidInput,
            lang,
            f"vote_id must be positive, got {vote_id}.",
            f"vote_id doit être positif ; reçu {vote_id}.",
        )
    session = _check_session(session, lang)
    # sencanada.ca renders any id/session pair and prints the session from
    # the URL (confirmed live 2026-10-03: vote 702799, a 45-1 vote, came back
    # as "44th Parliament, 1st Session" under 44-1), so the pairing is
    # checked against the session's own votes list.
    list_html, _ = await _page(f"{constants.LIST_PATHS[lang]}{session}", lang)
    listed, _sessions = parse_vote_list(list_html, session, lang)
    if not any(v.vote_id == vote_id for v in listed):
        raise lang_error(
            NotFound,
            lang,
            f"senate: vote {vote_id} is not in session {session}'s votes list; take the "
            "vote_id and session together from senate_list_votes.",
            f"senate : le vote {vote_id} n'est pas dans la liste des votes de la session "
            f"{session} ; prenez vote_id et session ensemble dans senate_list_votes.",
        )
    path = f"{constants.DETAIL_PATHS[lang]}{vote_id}/{session}"
    html, cached = await _page(path, lang)
    return parse_vote(html, vote_id, session, f"{constants.BASE_URL}{path}", lang, cached)

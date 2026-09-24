"""Client for the OpenParliament.ca API.

The API has no keyword search on bills or MPs (`q` is silently
ignored, and `name=` needs the exact full name; both confirmed live
2026-09-24), so those searches page through a session's bills or the
MP roster once, cache it, and filter here.
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any, Literal

import httpx

from maple_data_mcp.modules.openparliament import constants
from maple_data_mcp.modules.openparliament.schemas import (
    Ballot,
    Bill,
    BillSearchResult,
    BillSummary,
    Membership,
    PartyVote,
    Politician,
    PoliticianSearchResult,
    PoliticianSummary,
    Speech,
    SpeechSearchResult,
    Vote,
    VoteSearchResult,
    VoteSummary,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.models import Provenance
from maple_data_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_SESSION = re.compile(r"^\d{1,2}-\d$")
_BILL = re.compile(r"^[CS]-\d{1,4}[A-Z]?$")
_SLUG = re.compile(r"^[a-z0-9-]+$")
_TAG = re.compile(r"<[^>]+>")
_FRESHNESS = "updated daily from House of Commons sources; cached 15 min"
_NOTE = "OpenParliament.ca is unofficial; confirm key facts on parl.ca or ourcommons.ca."


async def _get(path: str, params: dict[str, Any] | None = None, ttl: int = 0) -> tuple[Any, bool]:
    url = f"{constants.BASE_URL}{path}"

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, headers=constants.HEADERS, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise NotFound(f"openparliament: nothing at {path}.") from exc
            raise UpstreamError(
                f"openparliament: {url} returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.DecodingError as exc:
            raise UpstreamError(f"openparliament: {url} did not return JSON.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"openparliament: {url} could not be reached.") from exc

    key = f"openparliament:{path}:{sorted((params or {}).items())}"
    return await cached_fetch(key, ttl or constants.CACHE_TTL_SECONDS, fetch)


async def _get_all(
    path: str, params: dict[str, Any], ttl: int = 0
) -> tuple[list[dict[str, Any]], bool]:
    """Every object from a list endpoint, following offsets up to MAX_ROWS."""
    rows: list[dict[str, Any]] = []
    all_cached = True
    offset = 0
    while offset < constants.MAX_ROWS:
        page, cached = await _get(
            path, {**params, "limit": constants.PAGE_SIZE, "offset": offset}, ttl
        )
        all_cached = all_cached and cached
        objects = page.get("objects") or []
        rows.extend(objects)
        if not (page.get("pagination") or {}).get("next_url") or not objects:
            break
        offset += len(objects)
    return rows, all_cached


def _text(value: Any, lang: Lang) -> str | None:
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or None
    return value or None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _slug(url: str | None) -> str | None:
    return url.rstrip("/").rsplit("/", 1)[-1] if url else None


def _plain(fragment: str | None) -> str:
    if not fragment:
        return ""
    text = re.sub(r"</p>\s*", "\n", fragment)
    return html.unescape(_TAG.sub("", text)).strip()


def _check_session(session: str) -> str:
    if not _SESSION.match(session.strip()):
        raise InvalidInput(f"session must look like '45-1', got {session!r}.")
    return session.strip()


def _check_bill(number: str) -> str:
    cleaned = number.strip().upper()
    if not _BILL.match(cleaned):
        raise InvalidInput(f"bill number must look like 'C-2' or 'S-209', got {number!r}.")
    return cleaned


def _check_slug(slug: str) -> str:
    cleaned = slug.strip().strip("/").rsplit("/", 1)[-1].lower()
    if not _SLUG.match(cleaned):
        raise InvalidInput(f"politician must be a slug like 'mark-carney', got {slug!r}.")
    return cleaned


def _check_limit(limit: int) -> None:
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.")


def _date_param(value: str, name: str) -> str:
    parsed = _date(value.strip())
    if parsed is None:
        raise InvalidInput(f"{name} must be YYYY-MM-DD, got {value!r}.")
    return parsed.isoformat()


def _provenance(path: str, params: dict[str, Any], cached: bool, schema: str) -> Provenance:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=str(httpx.URL(f"{constants.BASE_URL}{path}", params=params)),
        cached=cached,
        schema_name=f"openparliament.{schema}",
        freshness=_FRESHNESS,
        limits=_NOTE,
    )


async def current_session() -> str:
    """The session of the most recent recorded vote."""
    page, _ = await _get("/votes/", {"limit": 1})
    objects = page.get("objects") or []
    if not objects:
        raise UpstreamError("openparliament: could not determine the current session.")
    return objects[0]["session"]


async def search_bills(
    *,
    session: str | None = None,
    keyword: str | None = None,
    sponsor: str | None = None,
    private_member: bool | None = None,
    introduced_from: str | None = None,
    lang: Lang = "en",
    limit: int = constants.LIMIT_DEFAULT,
) -> BillSearchResult:
    _check_limit(limit)
    params: dict[str, Any] = {
        "session": _check_session(session) if session else await current_session()
    }
    if sponsor:
        params["sponsor_politician"] = f"/politicians/{_check_slug(sponsor)}/"
    if private_member is not None:
        params["private_member_bill"] = str(private_member)
    if introduced_from:
        params["introduced__gte"] = _date_param(introduced_from, "introduced_from")
    rows, cached = await _get_all("/bills/", params)
    needle = (keyword or "").strip().lower()
    bills = [
        BillSummary(
            session=row["session"],
            number=row["number"],
            name=_text(row.get("name"), lang) or "",
            introduced=_date(row.get("introduced")),
            url=f"{constants.SITE_URL}{row['url']}",
        )
        for row in rows
        if not needle
        or needle in row.get("number", "").lower()
        or any(needle in (v or "").lower() for v in (row.get("name") or {}).values())
    ]
    bills.sort(key=lambda b: b.introduced or date.min, reverse=True)
    kept = bills[:limit]
    return BillSearchResult(
        bills=kept,
        total_matches=len(bills),
        returned_count=len(kept),
        provenance=_provenance("/bills/", params, cached, "BillSearchResult"),
    )


def _vote_summary(row: dict[str, Any], lang: Lang) -> VoteSummary:
    return VoteSummary(
        session=row["session"],
        number=int(row["number"]),
        date=_date(row.get("date")),
        description=_text(row.get("description"), lang) or "",
        result=row.get("result"),
        yea_total=row.get("yea_total"),
        nay_total=row.get("nay_total"),
        paired_total=row.get("paired_total"),
        bill=_slug(row.get("bill_url")),
        url=f"{constants.SITE_URL}{row['url']}",
    )


async def get_bill(session: str, number: str, *, lang: Lang = "en") -> Bill:
    path = f"/bills/{_check_session(session)}/{_check_bill(number)}/"
    row, cached = await _get(path)
    votes, _ = await _get_all("/votes/", {"bill": path})
    return Bill(
        session=row["session"],
        number=row["number"],
        name=_text(row.get("name"), lang) or "",
        short_title=_text(row.get("short_title"), lang),
        introduced=_date(row.get("introduced")),
        status=_text(row.get("status"), lang),
        status_code=row.get("status_code"),
        home_chamber=row.get("home_chamber"),
        private_member_bill=row.get("private_member_bill"),
        became_law=row.get("law"),
        sponsor=_slug(row.get("sponsor_politician_url")),
        text_url=row.get("text_url"),
        legisinfo_url=row.get("legisinfo_url"),
        votes=[_vote_summary(v, lang) for v in votes],
        url=f"{constants.SITE_URL}{path}",
        provenance=_provenance(path, {}, cached, "Bill"),
    )


async def search_votes(
    *,
    session: str | None = None,
    bill: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    result: str | None = None,
    lang: Lang = "en",
    limit: int = constants.LIMIT_DEFAULT,
) -> VoteSearchResult:
    _check_limit(limit)
    params: dict[str, Any] = {}
    if session:
        params["session"] = _check_session(session)
    if bill:
        if not session:
            raise InvalidInput("bill needs session too, e.g. session='45-1', bill='C-2'.")
        params["bill"] = f"/bills/{params['session']}/{_check_bill(bill)}/"
    if date_from:
        params["date__gte"] = _date_param(date_from, "date_from")
    if date_to:
        params["date__lte"] = _date_param(date_to, "date_to")
    if result:
        if result not in ("Passed", "Failed", "Tie"):
            raise InvalidInput("result must be 'Passed', 'Failed' or 'Tie'.")
        params["result"] = result
    page, cached = await _get("/votes/", {**params, "limit": limit})
    votes = [_vote_summary(row, lang) for row in page.get("objects") or []]
    return VoteSearchResult(
        votes=votes,
        returned_count=len(votes),
        has_more=bool((page.get("pagination") or {}).get("next_url")),
        provenance=_provenance("/votes/", params, cached, "VoteSearchResult"),
    )


async def get_vote(
    session: str, number: int, *, include_ballots: bool = False, lang: Lang = "en"
) -> Vote:
    if number < 1:
        raise InvalidInput(f"vote number must be positive, got {number}.")
    path = f"/votes/{_check_session(session)}/{number}/"
    row, cached = await _get(path)
    ballots: list[Ballot] = []
    if include_ballots:
        rows, _ = await _get_all("/votes/ballots/", {"vote": path})
        ballots = [
            Ballot(politician=_slug(b.get("politician_url")) or "", ballot=b.get("ballot", ""))
            for b in rows
        ]
    return Vote(
        vote=_vote_summary(row, lang),
        party_votes=[
            PartyVote(
                party=_text((p.get("party") or {}).get("short_name"), lang) or "",
                vote=p.get("vote", ""),
                disagreement=p.get("disagreement"),
            )
            for p in row.get("party_votes") or []
        ],
        ballots=ballots,
        provenance=_provenance(path, {}, cached, "Vote"),
    )


async def search_politicians(
    *,
    name: str | None = None,
    province: str | None = None,
    party: str | None = None,
    include_former: bool = False,
    limit: int = constants.LIMIT_DEFAULT,
) -> PoliticianSearchResult:
    _check_limit(limit)
    current, cached = await _get_all("/politicians/", {}, constants.ROSTER_TTL_SECONDS)
    rows = [(row, True) for row in current]
    if include_former:
        # Former MPs come back with only name and url (confirmed live).
        former, former_cached = await _get_all(
            "/politicians/", {"include": "former"}, constants.ROSTER_TTL_SECONDS
        )
        rows += [(row, False) for row in former]
        cached = cached and former_cached
    people = []
    for row, is_current in rows:
        riding = row.get("current_riding") or {}
        person = PoliticianSummary(
            slug=_slug(row.get("url")) or "",
            name=row.get("name", ""),
            party=_text((row.get("current_party") or {}).get("short_name"), "en"),
            riding=_text(riding.get("name"), "en"),
            province=riding.get("province"),
            current=is_current,
        )
        if name and name.strip().lower() not in person.name.lower():
            continue
        if province and (person.province or "").upper() != province.strip().upper():
            continue
        if party and party.strip().lower() not in (person.party or "").lower():
            continue
        people.append(person)
    kept = people[:limit]
    return PoliticianSearchResult(
        politicians=kept,
        total_matches=len(people),
        returned_count=len(kept),
        provenance=_provenance("/politicians/", {}, cached, "PoliticianSearchResult"),
    )


async def get_politician(slug: str, *, lang: Lang = "en") -> Politician:
    path = f"/politicians/{_check_slug(slug)}/"
    row, cached = await _get(path)
    memberships = [
        Membership(
            start_date=_date(m.get("start_date")),
            end_date=_date(m.get("end_date")),
            party=_text((m.get("party") or {}).get("short_name"), lang),
            riding=_text((m.get("riding") or {}).get("name"), lang),
            province=(m.get("riding") or {}).get("province"),
        )
        for m in row.get("memberships") or []
    ]
    memberships.sort(key=lambda m: m.start_date or date.min, reverse=True)
    return Politician(
        slug=_slug(row.get("url")) or "",
        name=row.get("name", ""),
        email=row.get("email"),
        phone=row.get("voice"),
        memberships=memberships,
        links=[link["url"] for link in row.get("links") or [] if link.get("url")],
        url=f"{constants.SITE_URL}{path}",
        provenance=_provenance(path, {}, cached, "Politician"),
    )


async def search_speeches(
    *,
    politician: str | None = None,
    debate_date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    lang: Lang = "en",
    limit: int = constants.LIMIT_DEFAULT,
) -> SpeechSearchResult:
    _check_limit(limit)
    params: dict[str, Any] = {}
    if politician:
        params["politician"] = f"/politicians/{_check_slug(politician)}/"
    if debate_date:
        day = _date(debate_date.strip())
        if day is None:
            raise InvalidInput(f"debate_date must be YYYY-MM-DD, got {debate_date!r}.")
        # Debate URLs drop leading zeros (/debates/2026/9/23/), confirmed live.
        params["document"] = f"/debates/{day.year}/{day.month}/{day.day}/"
    if date_from:
        params["time__gte"] = _date_param(date_from, "date_from")
    if date_to:
        params["time__lt"] = f"{_date_param(date_to, 'date_to')} 23:59:59"
    if not params:
        raise InvalidInput("Give politician, debate_date, or a date range.")
    page, cached = await _get("/speeches/", {**params, "limit": limit})
    speeches = [
        Speech(
            time=row.get("time"),
            speaker=_text(row.get("attribution"), lang),
            politician=_slug(row.get("politician_url")),
            text=_plain(_text(row.get("content"), lang)),
            procedural=row.get("procedural"),
            document=row.get("document_url"),
            url=f"{constants.SITE_URL}{row['url']}",
        )
        for row in page.get("objects") or []
    ]
    return SpeechSearchResult(
        speeches=speeches,
        returned_count=len(speeches),
        has_more=bool((page.get("pagination") or {}).get("next_url")),
        provenance=_provenance("/speeches/", params, cached, "SpeechSearchResult"),
    )

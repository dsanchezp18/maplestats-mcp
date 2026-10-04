"""Shared pieces for the province readers: a district model and one fetch helper."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import httpx

from maplestats_mcp.modules.elections_provincial import constants
from maplestats_mcp.shared.errors import NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.rate_limiter import TokenBucket, get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)


@dataclass
class Candidate:
    name: str | None
    party: str | None
    votes: int
    share: float | None
    party_code: str | None = None
    elected: bool = False


@dataclass
class District:
    name: str
    number: str | None
    candidates: list[Candidate] = field(default_factory=list)
    electors: int | None = None
    valid_votes: int | None = None
    rejected_ballots: int | None = None
    turnout: float | None = None


def fold(text: str) -> str:
    """Lower-case text without accents, for accent-insensitive matching."""
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).casefold().strip()


def mark_winners(district: District) -> None:
    """Flag the candidate with the most votes (the first of any tie)."""
    if not district.candidates:
        return
    top = max(district.candidates, key=lambda c: c.votes)
    top.elected = True


def finish_shares(district: District) -> None:
    """Fill valid votes and vote shares from the candidates when the source gives none."""
    total = sum(c.votes for c in district.candidates)
    if district.valid_votes is None:
        district.valid_votes = total
    for candidate in district.candidates:
        if candidate.share is None and total:
            candidate.share = round(100 * candidate.votes / total, 2)


async def fetch_bytes(
    url: str,
    *,
    context: str,
    max_bytes: int | None = None,
    limiter: TokenBucket | None = None,
) -> bytes:
    """One paced GET of a file, with upstream failures turned into typed errors.

    `limiter` replaces the module's 10 second pacing for a source that asks for none.
    """
    await (limiter or _LIMITER).acquire()
    try:
        response = await get_raw(url, timeout=120.0)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(f"{context}: no file at {url}.") from exc
        raise UpstreamError(f"{context}: {url} returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"{context}: {url} did not respond in time.") from exc
    if max_bytes is not None and len(response.content) > max_bytes:
        raise UpstreamError(f"{context}: {url} is larger than this tool reads.")
    return response.content

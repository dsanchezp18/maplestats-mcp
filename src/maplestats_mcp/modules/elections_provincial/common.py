"""Shared pieces for the province readers: a district model and one fetch helper."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from maplestats_mcp.modules.elections_provincial import constants
from maplestats_mcp.shared import file_download
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
    share_computed: bool = False


@dataclass
class District:
    name: str
    number: str | None
    candidates: list[Candidate] = field(default_factory=list)
    electors: int | None = None
    valid_votes: int | None = None
    rejected_ballots: int | None = None
    turnout: float | None = None
    valid_votes_computed: bool = False
    turnout_computed: bool = False


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
    """Fill valid votes and vote shares from the candidates when the source gives none.

    Each filled figure is flagged as computed, so the response can tell a
    published share from one MapleStats worked out.
    """
    total = sum(c.votes for c in district.candidates)
    if district.valid_votes is None:
        district.valid_votes = total
        district.valid_votes_computed = True
    for candidate in district.candidates:
        if candidate.share is None and total:
            candidate.share = round(100 * candidate.votes / total, 2)
            candidate.share_computed = True


async def fetch_bytes(
    url: str,
    *,
    context: str,
    max_bytes: int | None = None,
    limiter: TokenBucket | None = None,
) -> bytes:
    """One paced GET of a file, with upstream failures turned into typed errors.

    The body is streamed and refused at `max_bytes` (from its Content-Length or
    mid-stream, never after it is all in memory), and a redirect may only reach
    the provinces' own hosts (constants.DOWNLOAD_HOSTS). `limiter` replaces the
    module's 10 second pacing for a source that asks for none.
    """
    downloaded = await file_download.download(
        url,
        allow_host=lambda host: host in constants.DOWNLOAD_HOSTS,
        limiter_for=lambda _host: limiter or _LIMITER,
        max_bytes=constants.DEFAULT_MAX_BYTES if max_bytes is None else max_bytes,
        context=context,
        timeout=120.0,
    )
    return downloaded.body

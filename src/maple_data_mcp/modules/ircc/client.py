"""HTTP client for IRCC's Express Entry rounds-of-invitations JSON feed.

Two real quirks confirmed live 2026-09-18, both handled below:

1. Neither feed declares a charset (`Content-Type: application/json` with
   no `charset` parameter). The English feed is plain ASCII and decodes
   correctly as UTF-8, but the French feed's bytes are actually
   Windows-1252 -- decoding them as UTF-8 does not raise (the bytes
   happen to form valid, just wrong, UTF-8 sequences), it silently
   mangles every accented character (e.g. "supérieurs" becomes
   "sup�rieurs"-style mojibake). `get_raw` is used instead of
   `api_get` so the raw bytes are available to decode explicitly per
   language rather than trusting httpx's default UTF-8 `.json()`.
2. Numeric fields use a locale-specific thousands separator: a comma in
   the English feed ("20,784") and a literal ASCII space in the French
   feed ("20 784", confirmed to be U+0020, not a non-breaking space).
   `_parse_int` strips both.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

from maple_data_mcp.modules.ircc import constants
from maple_data_mcp.modules.ircc.schemas import (
    CrsScoreDistribution,
    ExpressEntryRound,
    ExpressEntryRoundDetail,
    ExpressEntryRoundsResult,
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

_URL_BY_LANG: dict[str, str] = {"en": constants.BASE_URL_EN, "fr": constants.BASE_URL_FR}
_ENCODING_BY_LANG: dict[str, str] = {"en": "utf-8", "fr": "cp1252"}

# dd1-dd18 -> CrsScoreDistribution field order, confirmed live (see
# schemas.py's CrsScoreDistribution docstring for the verification method).
_DISTRIBUTION_FIELDS: list[tuple[str, str]] = [
    ("dd1", "band_601_1200"),
    ("dd2", "band_501_600"),
    ("dd3", "band_451_500"),
    ("dd4", "band_491_500"),
    ("dd5", "band_481_490"),
    ("dd6", "band_471_480"),
    ("dd7", "band_461_470"),
    ("dd8", "band_451_460"),
    ("dd9", "band_401_450"),
    ("dd10", "band_441_450"),
    ("dd11", "band_431_440"),
    ("dd12", "band_421_430"),
    ("dd13", "band_411_420"),
    ("dd14", "band_401_410"),
    ("dd15", "band_351_400"),
    ("dd16", "band_301_350"),
    ("dd17", "band_0_300"),
    ("dd18", "total"),
]

_HREF_RE = re.compile(r"href='([^']+)'")


def _parse_int(value: str) -> int:
    cleaned = value.replace(",", "").replace(" ", "").strip()
    return int(cleaned) if cleaned else 0


def _parse_details_url(draw_number_url: str) -> str:
    match = _HREF_RE.search(draw_number_url)
    href = match.group(1) if match else ""
    # Recent rounds' hrefs carry an internal "/content/canadasite" CMS
    # prefix; older rounds omit it. Both forms 200 to the same canonical
    # page once joined with the public host, confirmed live for rounds
    # spanning the whole feed (1, 94, 194, 294, 444) -- stripping the
    # prefix normalizes every era to one working URL shape.
    href = href.removeprefix("/content/canadasite")
    return urljoin(constants.DETAILS_URL_PREFIX, href)


def _round_from_json(obj: dict[str, Any]) -> ExpressEntryRound:
    distribution = CrsScoreDistribution(
        **{
            field_name: _parse_int(obj.get(dd_key, "0"))
            for dd_key, field_name in _DISTRIBUTION_FIELDS
        }
    )
    cutoff_text = (obj.get("drawCutOff") or "").strip()
    return ExpressEntryRound(
        draw_number=obj["drawNumber"].strip(),
        draw_date=date.fromisoformat(obj["drawDate"].strip()),
        draw_name=obj["drawName"].strip(),
        program=obj["drawText2"].strip(),
        invitations_issued=_parse_int(obj["drawSize"]),
        crs_cutoff=_parse_int(obj["drawCRS"]),
        pool_distribution_as_of=obj["drawDistributionAsOn"].strip(),
        eligibility_cutoff=cutoff_text or None,
        crs_distribution=distribution,
        details_url=_parse_details_url(obj["drawNumberURL"]),
    )


def _parse_feed(raw_bytes: bytes, lang: str) -> list[ExpressEntryRound]:
    try:
        text = raw_bytes.decode(_ENCODING_BY_LANG[lang])
        payload = json.loads(text)
        rounds = payload["rounds"]
        return [_round_from_json(obj) for obj in rounds]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise UpstreamError(
            f"IRCC Express Entry feed ({lang}) was not shaped as documented: {exc}"
        ) from exc


async def _fetch_rounds(lang: str) -> tuple[list[ExpressEntryRound], bool]:
    url = _URL_BY_LANG[lang]

    async def fetch() -> list[ExpressEntryRound]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise NotFound(f"IRCC Express Entry feed not found at {url}.") from exc
            raise UpstreamError(f"IRCC Express Entry feed returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "IRCC's Express Entry feed did not respond in time after the "
                "shared HTTP retries. Try again shortly."
            ) from exc
        return _parse_feed(response.content, lang)

    return await cached_fetch(f"ircc:express-entry:{lang}", constants.CACHE_TTL_SECONDS, fetch)


def _matches_program(round_: ExpressEntryRound, needle: str) -> bool:
    haystack = f"{round_.draw_name} {round_.program}".casefold()
    return needle in haystack


async def list_express_entry_rounds(
    program: str | None = None,
    since: date | None = None,
    limit: int = constants.ROUNDS_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> ExpressEntryRoundsResult:
    if limit < 1 or limit > constants.ROUNDS_LIMIT_MAX:
        raise InvalidInput(
            f"limit must be between 1 and {constants.ROUNDS_LIMIT_MAX}, got {limit}."
        )

    rounds, was_cached = await _fetch_rounds(lang)
    matching = rounds
    if program is not None:
        needle = program.strip().casefold()
        if not needle:
            raise InvalidInput("program must not be empty when provided.")
        matching = [r for r in matching if _matches_program(r, needle)]
    if since is not None:
        matching = [r for r in matching if r.draw_date >= since]

    page = matching[:limit]
    return ExpressEntryRoundsResult(
        rounds=page,
        total_matching=len(matching),
        returned_count=len(page),
        limit=limit,
        program=program,
        since=since,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=_URL_BY_LANG[lang],
            cached=was_cached,
            schema_name="ircc.ExpressEntryRoundsResult",
            coverage=f"{len(page)} of {len(matching)} matching rounds returned, "
            f"newest first, out of {len(rounds)} rounds in the feed",
            freshness="the underlying feed is updated by IRCC roughly weekly; "
            f"MapleData caches it for {constants.CACHE_TTL_SECONDS // 3600} hours",
        ),
    )


async def get_express_entry_round(draw_number: str, lang: Lang = "en") -> ExpressEntryRoundDetail:
    draw_number = draw_number.strip()
    if not draw_number:
        raise InvalidInput("draw_number must not be empty.")
    rounds, was_cached = await _fetch_rounds(lang)
    for round_ in rounds:
        if round_.draw_number == draw_number:
            return ExpressEntryRoundDetail(
                round=round_,
                provenance=make_provenance(
                    source=constants.RATE_LIMIT_SOURCE,
                    url=_URL_BY_LANG[lang],
                    cached=was_cached,
                    schema_name="ircc.ExpressEntryRoundDetail",
                ),
            )
    raise NotFound(f"IRCC Express Entry round #{draw_number} was not found.")


async def get_latest_express_entry_round(lang: Lang = "en") -> ExpressEntryRoundDetail:
    rounds, was_cached = await _fetch_rounds(lang)
    if not rounds:
        raise UpstreamError("IRCC Express Entry feed returned no rounds.")
    return ExpressEntryRoundDetail(
        round=rounds[0],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=_URL_BY_LANG[lang],
            cached=was_cached,
            schema_name="ircc.ExpressEntryRoundDetail",
            freshness="the underlying feed is updated by IRCC roughly weekly; "
            f"MapleData caches it for {constants.CACHE_TTL_SECONDS // 3600} hours",
        ),
    )

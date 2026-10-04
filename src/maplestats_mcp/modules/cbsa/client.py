"""Client for CBSA's current border wait times CSV.

Checked live 2026-10-03, English and French files:

1. Fields are separated by ";;" followed by a space, and every line,
   the header included, ends with ";; " (so a split leaves an empty last
   field); the file ends with a blank line. It is not a CSV a standard
   reader can parse, so lines are split by hand.
2. Both files are UTF-8 with a BOM.
3. Columns, in this order: office, location ("Fort Erie, ON/Buffalo, NY"),
   last updated ("2026-10-03 13:20 EDT"; French zones are HAE, HAA, HAC,
   HNC, HAR, HAP), then commercial Canada-bound, commercial U.S.-bound,
   travellers Canada-bound, travellers U.S.-bound.
4. Values are "No Delay" / "Aucun délai", "5 minutes", "1 minute",
   "Not Applicable" / "Ne s'applique pas" and "--" (every U.S.-bound lane
   read "--" that day: CBSA posts Canada-bound waits only). "Closed" /
   "Fermé" appears when a crossing is shut.
5. 30 crossings, from St. Stephen NB to Boundary Bay BC; Saskatchewan's
   North Portal says CST all year. Office names are translated in the
   French file ("Pont Peace"), locations are not.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx

from maplestats_mcp.modules.cbsa import constants
from maplestats_mcp.modules.cbsa.schemas import BorderCrossing, BorderWaitTimes, WaitTime
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
_MINUTES = re.compile(r"^(\d+)\s*min", re.IGNORECASE)
_SIDES = re.compile(r",\s*([A-Z]{2})\s*/.*,\s*([A-Z]{2})\s*$")
_UPDATED = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*([A-Z]{3})?$")
_LANES = (
    "commercial_canada_bound",
    "commercial_us_bound",
    "travellers_canada_bound",
    "travellers_us_bound",
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def parse_wait(text: str) -> WaitTime:
    value = " ".join(text.split())
    folded = _fold(value)
    if match := _MINUTES.match(folded):
        return WaitTime(status="minutes", minutes=int(match.group(1)), text=value)
    if folded in ("no delay", "aucun delai"):
        return WaitTime(status="no_delay", minutes=0, text=value)
    if folded in ("not applicable", "ne s'applique pas", "n/a", "s.o."):
        return WaitTime(status="not_applicable", text=value)
    if folded in ("--", "-", ""):
        return WaitTime(status="not_reported", text=value)
    if folded.startswith(("closed", "ferme")):
        return WaitTime(status="closed", text=value)
    return WaitTime(status="other", text=value)


def parse_updated(text: str) -> datetime | None:
    match = _UPDATED.match(" ".join(text.split()))
    if not match or match.group(3) not in constants.ZONES:
        return None
    offset = timezone(timedelta(hours=constants.ZONES[match.group(3)]))
    return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M").replace(
        tzinfo=offset
    )


def parse_file(text: str) -> list[BorderCrossing]:
    lines = [line for line in text.lstrip("﻿").splitlines() if line.strip()]
    if not lines or ";;" not in lines[0]:
        raise UpstreamError("cbsa: the wait times file has no ';;' header; its format changed.")
    crossings: list[BorderCrossing] = []
    for line in lines[1:]:
        fields = [f.strip() for f in line.split(";;")]
        if len(fields) < 7 or not fields[0]:
            continue
        sides = _SIDES.search(fields[1])
        waits = {lane: parse_wait(value) for lane, value in zip(_LANES, fields[3:7], strict=True)}
        crossings.append(
            BorderCrossing(
                office=fields[0],
                location=fields[1],
                province=sides.group(1) if sides else None,
                us_state=sides.group(2) if sides else None,
                updated=fields[2],
                updated_at=parse_updated(fields[2]),
                **waits,
            )
        )
    if not crossings:
        raise UpstreamError("cbsa: the wait times file lists no crossing; its format changed.")
    return crossings


async def _crossings(lang: str) -> tuple[list[BorderCrossing], bool]:
    url = constants.CSV_URL[lang]

    async def fetch() -> list[BorderCrossing]:
        await _LIMITER.acquire()
        try:
            response = await get_raw(url, timeout=30.0)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(f"cbsa: {url} returned HTTP {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"cbsa: {url} did not respond in time.") from exc
        if len(response.content) > constants.MAX_FILE_BYTES:
            raise UpstreamError(f"cbsa: {url} is much larger than expected; it changed.")
        return parse_file(response.content.decode("utf-8-sig", errors="replace"))

    return await cached_fetch(f"cbsa:bwt:{lang}", constants.CACHE_TTL_SECONDS, fetch)


def _province_code(province: str) -> str:
    wanted = _fold(province)
    for code, names in constants.PROVINCES.items():
        if wanted in (code.casefold(), *(_fold(n) for n in names)):
            return code
    raise InvalidInput(
        f"cbsa: unknown province {province!r}; use a code like ON, QC, BC "
        f"({', '.join(constants.PROVINCES)})."
    )


async def border_wait_times(
    *,
    province: str = "",
    crossing: str = "",
    direction: str = "both",
    lang: str = "en",
) -> BorderWaitTimes:
    """Current waits, filtered by province of the Canadian side, crossing name and direction."""
    if direction not in ("both", "canada_bound", "us_bound"):
        raise InvalidInput("cbsa: direction must be both, canada_bound or us_bound.")
    code = _province_code(province) if province.strip() else None
    crossings, cached = await _crossings(lang)
    words = _fold(crossing).split()
    chosen: list[BorderCrossing] = []
    for item in crossings:
        if code and item.province != code:
            continue
        if words and not all(w in _fold(f"{item.office} {item.location}") for w in words):
            continue
        shown = item.model_copy()
        if direction == "canada_bound":
            shown.commercial_us_bound = shown.travellers_us_bound = None
        elif direction == "us_bound":
            shown.commercial_canada_bound = shown.travellers_canada_bound = None
        chosen.append(shown)

    def travellers(item: BorderCrossing) -> int:
        waits = [item.travellers_canada_bound, item.travellers_us_bound]
        return max((w.minutes or 0 for w in waits if w and w.status == "minutes"), default=0)

    longest = max(chosen, key=travellers, default=None)
    land = f"https://open.canada.ca/data/{lang}/dataset/{constants.HISTORICAL_LAND_DATASET}"
    air = f"https://open.canada.ca/data/{lang}/dataset/{constants.HISTORICAL_AIR_DATASET}"
    history = (
        f"Historique : postes terrestres {land} (2010 et après), aéroports {air}; lisibles "
        "avec ckan_read_resource (portal='federal')."
        if lang == "fr"
        else f"Historical files: land crossings {land} (2010 onward), airports {air}; "
        "readable with ckan_read_resource (portal='federal')."
    )
    return BorderWaitTimes(
        crossings=chosen,
        total_crossings=len(crossings),
        returned_count=len(chosen),
        longest_travellers_wait=(
            longest.office if longest is not None and travellers(longest) > 0 else None
        ),
        historical_data=history,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.CSV_URL[lang],
            cached=cached,
            schema_name="cbsa.BorderWaitTimes",
            freshness="file rewritten every few minutes; each crossing has its own update time",
            coverage="about 30 land crossings; most U.S.-bound lanes are not reported ('--')",
            licence=constants.LICENCE,
            lang=lang,
        ),
    )

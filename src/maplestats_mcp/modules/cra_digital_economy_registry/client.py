"""Client for CRA's simplified GST/HST digital economy registry page.

Confirmed live 2026-09-21: a plain unauthenticated GET of the page
returns the *entire* registry (2,347 rows the day this was built)
server-rendered inside one `<table class="wb-tables">` -- diffed the raw
response body directly against the live, JS-modified DOM to confirm this;
the jQuery DataTables widget only paginates what is *displayed*, it does
not lazily fetch rows. No session, cookies, or pagination handling is
needed, unlike `modules/elections_financial_returns/`.

Each row's "Operating or trade name(s)" and "Effective de-registration
date" cells hold a WET-BOEW `<span class="wb-inv">-</span>` (a
screen-reader-only "no value" marker) instead of being empty when a
business has no trade name or has not de-registered -- parsed to `None`
here rather than kept as the literal "-" string. A business that has
re-registered appears as more than one row sharing the same legal name
but a different business-number suffix (RT0001 vs RT9999) and date
range -- rows are kept distinct, not deduplicated by name.

Confirmed live 2026-09-21: `shared/http.py`'s shared client cannot be
used here. This ~470KB page reliably fails with an HTTP/2
`RemoteProtocolError` (`StreamReset ... remote_reset:True`) over
`shared/http.py`'s `http2=True` connection -- reproduced consistently,
not a one-off -- while a plain `curl --http1.1` and a standalone
`httpx.AsyncClient(http2=False)` both fetch the exact same URL cleanly.
This is the mirror image of the ALPN quirk AGENTS.md documents for
StatCan (which *needs* HTTP/2 offered): here, canada.ca's edge appears
to reset an HTTP/2 stream for a response this large rather than reject
the connection outright, so this module keeps its own small
`http2=False` client instead of forcing every other module's shared
transport to give up the StatCan fix to accommodate one large page.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from maplestats_mcp.modules.cra_digital_economy_registry import constants
from maplestats_mcp.modules.cra_digital_economy_registry.schemas import (
    DigitalEconomyRegistrant,
    DigitalEconomyRegistryResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# See module docstring: canada.ca resets an HTTP/2 stream for this
# specific large page, confirmed reproducible -- this client
# deliberately does NOT use shared/http.py's http2=True singleton.
_client = new_client(timeout=45.0, http2=False)


@retry(
    retry=retry_if_exception_type(
        (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def _get(url: str) -> httpx.Response:
    # Confirmed live 2026-09-21: this ~470KB page occasionally hits a
    # transient HTTP/2-stream reset or read timeout even over the
    # http2=False client above -- both resolved on a same-second retry,
    # not a persistent failure -- so this wraps the GET in the same
    # exponential-backoff retry shared/http.py applies to every other
    # module's requests, which this module's dedicated client otherwise
    # bypasses.
    response = await _client.get(url)
    response.raise_for_status()
    return response


def _cell_text(cell) -> str | None:
    text = cell.get_text(strip=True)
    return None if text in ("", "-") else text


def _parse_registrants(html: str) -> list[DigitalEconomyRegistrant]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wb-tables")
    if table is None:
        raise UpstreamError(
            "cra_digital_economy_registry: expected response shape not found "
            "(missing table.wb-tables)."
        )
    registrants: list[DigitalEconomyRegistrant] = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        legal_name = _cell_text(cells[0])
        business_number = _cell_text(cells[2])
        registration_date = _cell_text(cells[3])
        if not legal_name or not business_number or not registration_date:
            continue
        registrants.append(
            DigitalEconomyRegistrant(
                legal_name=legal_name,
                trade_name=_cell_text(cells[1]),
                business_number=business_number,
                effective_registration_date=registration_date,
                effective_deregistration_date=_cell_text(cells[4]),
            )
        )
    return registrants


async def search_registrants(query: str = "", *, lang: str = "en") -> DigitalEconomyRegistryResult:
    if lang not in ("en", "fr"):
        raise InvalidInput(f"lang must be one of ('en', 'fr'), got {lang!r}.")
    url = constants.URL_EN if lang == "en" else constants.URL_FR
    cache_key = f"cra-digital-economy-registry:{lang}"

    async def fetch() -> str:
        await _LIMITER.acquire()
        try:
            response = await _get(url)
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"cra_digital_economy_registry returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(
                "cra_digital_economy_registry did not respond in time."
            ) from exc
        return response.text

    html, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    all_registrants = _parse_registrants(html)

    needle = query.strip().lower()
    if needle:
        matched = [
            r
            for r in all_registrants
            if needle in r.legal_name.lower()
            or (r.trade_name and needle in r.trade_name.lower())
            or needle in r.business_number.lower()
        ]
    else:
        matched = all_registrants

    truncated = matched[: constants.SEARCH_RESULTS_MAX]
    coverage = None
    if len(matched) > len(truncated):
        coverage = f"first {len(truncated)} of {len(matched)} matches -- narrow the query"

    return DigitalEconomyRegistryResult(
        query=query,
        registrants=truncated,
        returned_count=len(truncated),
        total_matched=len(matched),
        total_registrants=len(all_registrants),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=was_cached,
            schema_name="cra_digital_economy_registry.DigitalEconomyRegistryResult",
            coverage=coverage,
        ),
    )

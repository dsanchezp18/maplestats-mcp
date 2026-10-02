"""Client for StatCan's Delta File bulk daily-update archive.

Confirmed live 2026-09-21. Existence is checked with a HEAD request
(not a full download -- these files run several megabytes) against a
dedicated `httpx.AsyncClient` with `http2=True` and
`follow_redirects=True`: `www150.statcan.gc.ca` needs HTTP/2 offered
in the handshake (see `shared/http.py`'s own docstring for the
underlying reason), and the Delta File path itself 301s to a
`/n1/...` canonical URL before answering.
"""

from __future__ import annotations

from datetime import date as date_cls

import httpx

from maplestats_mcp.modules.statcan.delta import constants
from maplestats_mcp.modules.statcan.delta.schemas import DeltaFileLink
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, UpstreamUnavailable
from maplestats_mcp.shared.http import new_client
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_client = new_client(timeout=15.0, follow_redirects=True)

FILE_NOTES = [
    (
        "Released on business days about 8:30 ET; a correction arrives in the next day's file and "
        "nothing is deleted. About 47 business days are kept (statcan_delta_list_files)."
    ),
    (
        "Each zip holds codeSet.xml, YYYYMMDD.xml (cube metadata) and YYYYMMDD.csv (data, "
        "sorted by productId, scalar factors not applied); read one table without "
        "downloading with statcan_delta_read_table. Metadata schema: "
        "https://www.statcan.gc.ca/en/developers-developpeurs/df-fd/cubemetadata.zip"
    ),
]


async def get_file_link(date: str) -> DeltaFileLink:
    """Resolve the Delta File URL for one date and confirm whether it exists."""
    try:
        parsed = date_cls.fromisoformat(date)
    except ValueError as exc:
        raise InvalidInput(
            f"statcan_delta:get_file_link: expected a YYYY-MM-DD date, got {date!r}."
        ) from exc

    url = constants.BASE_URL.format(date=parsed.strftime("%Y%m%d"))

    await _LIMITER.acquire()
    try:
        response = await _client.head(url)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            "statcan_delta:get_file_link did not respond in time. Try again shortly."
        ) from exc

    exists = response.status_code == 200
    size_raw = response.headers.get("content-length")
    size_bytes = int(size_raw) if exists and size_raw is not None and size_raw.isdigit() else None

    return DeltaFileLink(
        date=date,
        url=url,
        exists=exists,
        size_bytes=size_bytes,
        last_modified=response.headers.get("last-modified") if exists else None,
        etag=response.headers.get("etag") if exists else None,
        notes=FILE_NOTES,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_delta.DeltaFileLink",
        ),
    )

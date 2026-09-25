"""HTTP client for ISED's Spectrum Management System licence site data.

Reuses shared/arcgis.py's generic FeatureServer query plumbing
(`query_layer`, the same function every ArcGIS Hub module in this
codebase uses to read rows) directly against this one known, fixed
service url -- `ArcGISHubConfig.domain` is only meaningful for Hub
Search API calls (`search_items`/`get_item`/`download_url`), none of
which this module needs, so it is set to the service's own host
purely for a sensible provenance URL and is otherwise unused.

Confirmed live 2026-09-19: ~840,000 records, one layer (id 0, point
geometry, "Site_Data_Extract_XYTableToPoint"), refreshed monthly per
the service's own description. Field names (LICENSEE, SERVICE,
TRANSMIT_FREQ, LATITUDE/LONGITUDE, STUCT_HT -- a genuine upstream
typo for "structure height", not this client's) are passed straight
through in each row rather than renamed, since there are 30+ of them
and callers already familiar with ISED's own data dictionary expect
these exact names.
"""

from __future__ import annotations

from typing import Any

from maplestats_mcp.modules.ised.spectrum import constants
from maplestats_mcp.modules.ised.spectrum.schemas import LicenceQueryResult
from maplestats_mcp.shared.arcgis import ArcGISHubConfig, query_layer
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.json_utils import list_or_empty

CONFIG = ArcGISHubConfig(
    source=constants.RATE_LIMIT_SOURCE,
    domain=constants.DOMAIN,
    rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
    rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
)


async def query_licences(
    *,
    where: str | None = None,
    out_fields: str = "*",
    order_by: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> LicenceQueryResult:
    """Query rows from ISED's spectrum licence site data; ``lang`` is accepted for consistency."""
    del lang
    if limit < 1 or limit > constants.ROWS_LIMIT_MAX:
        raise InvalidInput(f"limit must be between 1 and {constants.ROWS_LIMIT_MAX}, got {limit}.")
    if offset < 0:
        raise InvalidInput(f"offset must be >= 0, got {offset}.")
    where_clause = where or "1=1"

    async def fetch() -> dict[str, Any]:
        return await query_layer(
            CONFIG,
            constants.SERVICE_URL,
            constants.LAYER_INDEX,
            where=where_clause,
            out_fields=out_fields,
            order_by=order_by,
            return_geometry=False,
            limit=limit,
            offset=offset,
        )

    cache_key = f"ised-spectrum:query:{where_clause}:{out_fields}:{order_by}:{limit}:{offset}"
    body, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ROWS_SECONDS, fetch)
    features = list_or_empty(body, "features")
    rows = [dict(feature.get("attributes") or {}) for feature in features]
    exceeded = bool(body.get("exceededTransferLimit", False))
    return LicenceQueryResult(
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        where=where_clause,
        exceeded_transfer_limit=exceeded,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=f"{constants.SERVICE_URL}/{constants.LAYER_INDEX}/query",
            cached=was_cached,
            schema_name="ised_spectrum.LicenceQueryResult",
            coverage="~840,000 licence site records total, refreshed monthly by ISED",
            limits=(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else "")
            ),
        ),
    )

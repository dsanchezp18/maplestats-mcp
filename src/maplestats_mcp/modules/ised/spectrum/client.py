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

Date fields (LAST_MOD_DATE, LAST_UPLOAD_DATE: esriFieldTypeDate in the
layer's own field list) come back as epoch milliseconds at midnight UTC
(1557273600000); they are returned as ISO dates ("2019-05-08"). The
layer's editingInfo.dataLastEditDate gives provenance.as_of: checked
2026-10-03 it was 2024-02-08 and the newest LAST_UPLOAD_DATE 2024-01-29,
so despite the service description's "refreshed monthly" the hosted copy
has not changed since early 2024.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from maplestats_mcp.modules.ised.spectrum import constants
from maplestats_mcp.modules.ised.spectrum.schemas import LicenceQueryResult
from maplestats_mcp.shared.arcgis import ArcGISHubConfig, get_json, parse_epoch_millis, query_layer
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
_LAYER_URL = f"{constants.SERVICE_URL}/{constants.LAYER_INDEX}"


async def _layer_info() -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        return await get_json(CONFIG, "layer_info", _LAYER_URL)

    info, _ = await cached_fetch(
        "ised-spectrum:layer_info", constants.CACHE_TTL_LAYER_SECONDS, fetch
    )
    return info if isinstance(info, dict) else {}


def _iso_date(value: Any) -> Any:
    moment = parse_epoch_millis(value)
    return moment.date().isoformat() if moment else value


def _last_edit(info: dict[str, Any]) -> datetime | None:
    editing = info.get("editingInfo") or {}
    stamp = editing.get("dataLastEditDate") or editing.get("lastEditDate")
    return datetime.fromtimestamp(stamp / 1000, tz=UTC) if isinstance(stamp, int | float) else None


def _freshness(last_edit: datetime | None) -> str | None:
    if last_edit is None:
        return None
    text = f"hosted layer last edited {last_edit.date().isoformat()}"
    if datetime.now(UTC) - last_edit > timedelta(days=constants.STALE_AFTER_DAYS):
        text += "; the service description says monthly, but no refresh has followed since"
    return text


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
    info = await _layer_info()
    date_fields = {
        str(field.get("name"))
        for field in list_or_empty(info, "fields")
        if field.get("type") == "esriFieldTypeDate"
    }
    features = list_or_empty(body, "features")
    rows = [
        {
            key: _iso_date(value) if key in date_fields else value
            for key, value in (feature.get("attributes") or {}).items()
        }
        for feature in features
    ]
    exceeded = bool(body.get("exceededTransferLimit", False))
    last_edit = _last_edit(info)
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
            as_of=last_edit,
            freshness=_freshness(last_edit),
            coverage="~840,000 licence site records total",
            limits=(
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request"
                + (" (upstream layer's own transfer limit reached first)" if exceeded else "")
            ),
        ),
    )

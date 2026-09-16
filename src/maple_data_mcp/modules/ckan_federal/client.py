"""HTTP client for the Government of Canada Open Data (CKAN federal) API.

Every function wraps `shared.http.api_get` through the ckan-federal rate
limiter, unwraps CKAN's `{"help", "success", "result"}` envelope, and
maps HTTP error responses to this repo's typed errors. Confirmed live
this session:

- `package_show`/`organization_show`/`resource_show` return HTTP 404
  with `{"success": false, "error": {"__type": "Not Found Error", ...}}`
  for an unknown id -- mapped to NotFound.
- `package_search` returns HTTP 400 with
  `{"error": {"__type": "Search Query Error", ...}}` for a malformed
  `sort`/`fq` value (e.g. an unknown sort field) -- mapped to
  InvalidInput, since it is a caller-input problem, not an upstream
  failure.
- The Action API ignores a `lang` query parameter and a `/data/fr/...`
  path prefix on `/api/...` routes -- a `/data/fr/api/...` request
  302-redirects instead of returning translated JSON (confirmed live).
  Unlike CKAN's generic multilingual-extension docs, this deployment
  requires picking the requested language client-side from each
  record's `_translated` dict (or `_fra`-suffixed field, for
  license_list -- a different, older convention within the same API).
  See `_pick_translated`/`_pick_translated_list`/`_pick_fra` below.
- `group_list` and `tag_list` both return `[]` live, and every sampled
  package's `tags`/`groups` arrays are empty too -- this portal does
  not use CKAN tags or groups at all (subject terms live in the
  bilingual `keywords` field instead). No group/tag client functions
  are defined here as a result; see schemas.py's module docstring.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn

import httpx

from maple_data_mcp.modules.ckan_federal import constants
from maple_data_mcp.modules.ckan_federal.schemas import (
    LicenseInfo,
    LicenseList,
    OrganizationDetail,
    OrganizationList,
    OrganizationRef,
    OrganizationSummary,
    PackageDetail,
    PackageSearchResult,
    PackageSummary,
    ResourceDetail,
    ResourceInfo,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.json_utils import list_or_empty
from maple_data_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


def _error_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except ValueError:
        return exc.response.text[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        detail = err.get("message") or err.get("__type")
        if detail:
            return str(detail)
    return exc.response.text[:200]


def _raise_for_status_error(exc: httpx.HTTPStatusError, method: str) -> NoReturn:
    status = exc.response.status_code
    detail = _error_detail(exc)
    if status == 404:
        raise NotFound(f"{method}: no match found ({detail}).") from exc
    if status == 400:
        raise InvalidInput(f"{method}: rejected the request ({detail}).") from exc
    raise UpstreamError(f"{method} returned HTTP {status}: {detail}") from exc


def _raise_unavailable(method: str, exc: httpx.HTTPError) -> NoReturn:
    raise UpstreamUnavailable(
        f"{method} did not respond in time (already retried by shared/http.py). Try again shortly."
    ) from exc


async def _get(method: str, params: dict[str, Any] | None = None) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{method}"
    try:
        data = await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        _raise_for_status_error(exc, method)
    except httpx.HTTPError as exc:
        _raise_unavailable(method, exc)
    if not isinstance(data, dict) or not data.get("success"):
        raise UpstreamError(f"{method} returned an unsuccessful envelope: {data!r}")
    return data["result"]


def _pick_translated(flat: str | None, translated: dict[str, str] | None, lang: str) -> str:
    """Pick `lang` out of a CKAN `<field>_translated` dict.

    Falls back to English, then to the flat (English-default) field --
    confirmed live that `_translated` is occasionally missing the "fr"
    key (~2% of a live 100-dataset sample) but never missing "en".
    """
    if translated:
        picked = translated.get(lang) or translated.get("en")
        if picked:
            return picked
    return flat or ""


def _pick_translated_list(translated: dict[str, list[str]] | None, lang: str) -> list[str]:
    """Pick `lang` out of a `<field>_translated` dict of lists.

    Uses `lang in translated` rather than `translated.get(lang) or ...`
    so a genuinely empty list for the requested language (e.g. a
    dataset with no French keywords) is returned as-is instead of being
    treated as missing and silently backfilled from English.
    """
    if not translated:
        return []
    if lang in translated:
        return translated[lang]
    return translated.get("en") or []


def _pick_fra(base_value: str, fra_value: str | None, lang: str) -> str:
    """Pick between a flat field and its `_fra`-suffixed counterpart.

    license_list uses this older CKAN naming convention (`title_fra`,
    `url_fra`) rather than the `_translated` dict package/resource
    records use -- confirmed live, a second bilingual convention within
    the same API.
    """
    if lang == "fr" and fra_value:
        return fra_value
    return base_value


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _excerpt(text: str) -> str:
    text = text.strip()
    if len(text) <= constants.NOTES_EXCERPT_LENGTH:
        return text
    return text[: constants.NOTES_EXCERPT_LENGTH].rstrip() + "…"


def _resource_from_json(obj: dict[str, Any], lang: str) -> ResourceInfo:
    description = (
        _pick_translated(obj.get("description"), obj.get("description_translated"), lang) or None
    )
    return ResourceInfo(
        id=obj["id"],
        package_id=obj.get("package_id"),
        name=_pick_translated(obj.get("name"), obj.get("name_translated"), lang),
        description=description,
        format=obj.get("format") or None,
        url=obj["url"],
        size=obj.get("size"),
        language=list_or_empty(obj, "language"),
        created=_parse_dt(obj.get("created")),
        last_modified=_parse_dt(obj.get("last_modified")),
        metadata_modified=_parse_dt(obj.get("metadata_modified")),
        mimetype=obj.get("mimetype"),
    )


def _organization_ref_from_json(obj: dict[str, Any]) -> OrganizationRef:
    return OrganizationRef(id=obj["id"], name=obj["name"], title=obj.get("title") or obj["name"])


def _package_summary_from_json(obj: dict[str, Any], lang: str) -> PackageSummary:
    org = obj.get("organization") or {}
    notes = _pick_translated(obj.get("notes"), obj.get("notes_translated"), lang)
    resources = list_or_empty(obj, "resources")
    formats = sorted({r["format"] for r in resources if r.get("format")})
    return PackageSummary(
        id=obj["id"],
        title=_pick_translated(obj.get("title"), obj.get("title_translated"), lang),
        organization_name=org.get("name"),
        organization_title=org.get("title"),
        notes_excerpt=_excerpt(notes),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        num_resources=obj.get("num_resources", len(resources)),
        resource_formats=formats,
        metadata_modified=_parse_dt(obj.get("metadata_modified")),
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
    )


def _package_detail_from_json(obj: dict[str, Any], lang: str, *, cached: bool) -> PackageDetail:
    resources = list_or_empty(obj, "resources")
    return PackageDetail(
        id=obj["id"],
        title=_pick_translated(obj.get("title"), obj.get("title_translated"), lang),
        notes=_pick_translated(obj.get("notes"), obj.get("notes_translated"), lang),
        organization=_organization_ref_from_json(obj["organization"]),
        license_id=obj.get("license_id"),
        license_title=obj.get("license_title"),
        license_url=obj.get("license_url"),
        keywords=_pick_translated_list(obj.get("keywords"), lang),
        metadata_created=_parse_dt(obj.get("metadata_created")),
        metadata_modified=_parse_dt(obj.get("metadata_modified")),
        num_resources=obj.get("num_resources", len(resources)),
        resources=[_resource_from_json(r, lang) for r in resources],
        landing_page_url=f"{constants.DATASET_LANDING_URL.format(lang=lang)}{obj['id']}",
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}package_show",
            cached=cached,
            schema_name="ckan_federal.PackageDetail",
        ),
    )


async def search_datasets(
    query: str = "",
    *,
    fq: str | None = None,
    rows: int = constants.SEARCH_ROWS_DEFAULT,
    start: int = 0,
    sort: str | None = None,
    lang: str = "en",
) -> PackageSearchResult:
    """Full-text/filtered dataset search over `package_search`.

    An empty `query` is a deliberate match-all, not an error -- confirmed
    live that `package_search` with no `q` (or `q=""`) and only `fq` set
    returns the same total count as CKAN's documented `q=*:*` idiom.
    """
    if rows < 1 or rows > constants.SEARCH_ROWS_MAX:
        raise InvalidInput(f"rows must be between 1 and {constants.SEARCH_ROWS_MAX}, got {rows}.")
    if start < 0:
        raise InvalidInput(f"start must be >= 0, got {start}.")

    params: dict[str, Any] = {"q": query, "rows": rows, "start": start}
    if fq:
        params["fq"] = fq
    if sort:
        params["sort"] = sort

    cache_key = f"ckan:package_search:{query}:{fq}:{rows}:{start}:{sort}"

    async def fetch() -> dict[str, Any]:
        return await _get("package_search", params=params)

    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)

    raw_results = list_or_empty(result, "results")
    total_count = result.get("count", len(raw_results))
    packages = [_package_summary_from_json(obj, lang) for obj in raw_results]
    return PackageSearchResult(
        packages=packages,
        total_count=total_count,
        returned_count=len(packages),
        start=start,
        rows=rows,
        query=query,
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}package_search",
            cached=was_cached,
            schema_name="ckan_federal.PackageSearchResult",
            coverage=f"{len(packages)} of {total_count} total matches returned",
            limits=f"rows capped at {constants.SEARCH_ROWS_MAX} per request",
        ),
    )


async def get_dataset(dataset_id: str, lang: str = "en") -> PackageDetail:
    if not dataset_id.strip():
        raise InvalidInput("dataset_id must not be empty.")
    cache_key = f"ckan:package_show:{dataset_id}"

    async def fetch() -> dict[str, Any]:
        return await _get("package_show", params={"id": dataset_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_PACKAGE_SECONDS, fetch)
    return _package_detail_from_json(obj, lang, cached=was_cached)


async def list_organizations(lang: str = "en") -> OrganizationList:
    """List every publishing organization via `organization_list(all_fields=True)`.

    `lang` has no effect here -- confirmed live that, unlike
    organization_show, organization_list does not attach a
    `title_translated` dict; `title` is this portal's combined
    "English | French" convention regardless of `lang` (see
    OrganizationSummary's docstring).
    """
    cache_key = "ckan:organization_list:all_fields"

    async def fetch() -> list[dict[str, Any]]:
        return await _get("organization_list", params={"all_fields": "true"})

    orgs_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_ORGANIZATION_LIST_SECONDS, fetch
    )
    organizations = [
        OrganizationSummary(
            id=o["id"],
            name=o["name"],
            title=o.get("title") or o["name"],
            package_count=o.get("package_count", 0),
        )
        for o in orgs_raw
    ]
    return OrganizationList(
        organizations=organizations,
        total_count=len(organizations),
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}organization_list",
            cached=was_cached,
            schema_name="ckan_federal.OrganizationList",
            freshness="organization roster changes infrequently; cached 24h",
        ),
    )


async def get_organization(organization_id: str, lang: str = "en") -> OrganizationDetail:
    if not organization_id.strip():
        raise InvalidInput("organization_id must not be empty.")
    cache_key = f"ckan:organization_show:{organization_id}"

    async def fetch() -> dict[str, Any]:
        # include_datasets pinned to false regardless of CKAN's own
        # default (confirmed live: absent already omits `packages`) so
        # this stays compact even if a future CKAN upgrade changes that
        # default -- full dataset listing for an org goes through
        # search_datasets(fq="organization:<name>") instead.
        return await _get(
            "organization_show", params={"id": organization_id, "include_datasets": "false"}
        )

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ORGANIZATION_SECONDS, fetch)
    return OrganizationDetail(
        id=obj["id"],
        name=obj["name"],
        title=_pick_translated(obj.get("title"), obj.get("title_translated"), lang),
        description=obj.get("description") or None,
        package_count=obj.get("package_count", 0),
        image_url=obj.get("image_url") or None,
        landing_page_url=f"{constants.ORGANIZATION_LANDING_URL.format(lang=lang)}{obj['name']}",
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}organization_show?id={organization_id}",
            cached=was_cached,
            schema_name="ckan_federal.OrganizationDetail",
        ),
    )


async def get_resource(resource_id: str, lang: str = "en") -> ResourceDetail:
    if not resource_id.strip():
        raise InvalidInput("resource_id must not be empty.")
    cache_key = f"ckan:resource_show:{resource_id}"

    async def fetch() -> dict[str, Any]:
        return await _get("resource_show", params={"id": resource_id})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_RESOURCE_SECONDS, fetch)
    return ResourceDetail(
        resource=_resource_from_json(obj, lang),
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}resource_show?id={resource_id}",
            cached=was_cached,
            schema_name="ckan_federal.ResourceDetail",
        ),
    )


async def list_licenses(lang: str = "en") -> LicenseList:
    cache_key = "ckan:license_list"

    async def fetch() -> list[dict[str, Any]]:
        return await _get("license_list")

    licenses_raw, was_cached = await cached_fetch(
        cache_key, constants.CACHE_TTL_LICENSE_LIST_SECONDS, fetch
    )
    licenses = [
        LicenseInfo(
            id=lic["id"],
            title=_pick_fra(lic["title"], lic.get("title_fra"), lang),
            url=_pick_fra(lic.get("url") or "", lic.get("url_fra"), lang) or None,
            status=lic.get("status", "unknown"),
            is_okd_compliant=bool(lic.get("is_okd_compliant")),
            is_osi_compliant=bool(lic.get("is_osi_compliant")),
        )
        for lic in licenses_raw
    ]
    return LicenseList(
        licenses=licenses,
        provenance=make_provenance(
            source="ckan-federal",
            url=f"{constants.BASE_URL}license_list",
            cached=was_cached,
            schema_name="ckan_federal.LicenseList",
            freshness="licenses rarely change; cached 7d",
        ),
    )

"""HTTP client for StatCan's Reference Data as a Service (RDaaS).

All 12 endpoints from the live OpenAPI spec (see constants.py). Response
`@id` URLs are kept as-is (they're stable, dereferenceable identifiers);
callers pass just the trailing id segment to detail endpoints, matching
what the spec's `{id}` path parameter expects.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from maple_data_mcp.modules.statcan.rdaas import constants
from maple_data_mcp.modules.statcan.rdaas.schemas import (
    ClassificationCategoriesDetailed,
    ClassificationCategory,
    ClassificationDetail,
    ClassificationExclusion,
    ClassificationExclusions,
    ClassificationIndexEntry,
    ClassificationIndexes,
    ClassificationLevel,
    ClassificationSearchResult,
    ClassificationSummary,
    CodeMapEntry,
    CodeMapList,
    ConcordanceDetail,
    ConcordanceSearchResult,
    ConcordanceSummary,
    FilterOption,
    SearchFacets,
    SearchFilters,
    TermExclusion,
)
from maple_data_mcp.shared.cache import cached_fetch
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound
from maple_data_mcp.shared.http import api_get
from maple_data_mcp.shared.json_utils import list_or_empty
from maple_data_mcp.shared.rate_limiter import get_limiter


def _limiter():
    return get_limiter(
        constants.RATE_LIMIT_SOURCE,
        rate=constants.RATE_LIMIT_PER_SECOND,
        capacity=constants.RATE_LIMIT_CAPACITY,
    )


async def _get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    await _limiter().acquire()
    url = f"{constants.BASE_URL}{path}"
    try:
        return await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # Confirmed live: a well-formed but nonexistent id raises here
            # before any caller-side `if not obj.get("@id")` check ever
            # runs — api_get already calls raise_for_status(). Translate
            # once, centrally, rather than per detail-fetch function.
            raise NotFound(f"No RDaaS resource found at {path!r}") from exc
        raise


_VALID_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _resource_id(rdaas_url_or_id: str) -> str:
    """RDaaS accepts either a bare id or its full resource URL; normalize
    to the bare id since that's what the path template expects.

    The result is interpolated directly into both the request URL and
    the cache key, so it is validated here rather than trusted — a
    caller-supplied id containing "?", "#", ":", or whitespace must not
    be able to smuggle a query string or fragment into the upstream
    request or collide with an unrelated cache key. (A "/"-containing
    value is already reduced to its final segment above, so directory
    traversal is not a separate risk here.)
    """
    resource_id = rdaas_url_or_id.rsplit("/", 1)[-1]
    if not _VALID_RESOURCE_ID.match(resource_id):
        raise InvalidInput(f"{rdaas_url_or_id!r} is not a valid RDaaS resource id or URL.")
    return resource_id


def _facets_from_json(obj: dict[str, Any]) -> SearchFacets:
    facets = obj.get("facets", {})
    return SearchFacets(status=facets.get("status", {}), audience=facets.get("audience", {}))


def _classification_summary(entry: dict[str, Any]) -> ClassificationSummary:
    return ClassificationSummary(
        id=entry.get("@id", ""),
        name=entry.get("name", ""),
        abbreviation=entry.get("abbreviation"),
        audience=entry.get("audience", ""),
        status=entry.get("status", ""),
        version_number=entry.get("versionNumber"),
        valid_from=entry.get("validFrom"),
        last_updated=entry.get("lastUpdated"),
        code_count=entry.get("codeCount"),
        level_count=entry.get("levelCount"),
    )


async def search_classifications(
    query: str = "",
    *,
    start: int = 0,
    limit: int = constants.DEFAULT_SEARCH_LIMIT,
    audience: list[str] | None = None,
    status: list[str] | None = None,
    lang: str = "en",
) -> ClassificationSearchResult:
    params: dict[str, Any] = {
        "start": start,
        "limit": min(limit, constants.MAX_SEARCH_LIMIT),
        "lang": lang,
    }
    if query:
        params["q"] = query
    if audience:
        params["audience"] = audience
    if status:
        params["status"] = status

    obj = await _get("/search/classifications", params=params)
    results_obj = obj.get("results", obj)
    entries = results_obj.get("@graph", [])
    return ClassificationSearchResult(
        results=[_classification_summary(e) for e in entries],
        found=obj.get("found", len(entries)),
        start=obj.get("start", start),
        limit=obj.get("limit", limit),
        facets=_facets_from_json(obj),
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/search/classifications",
            cached=False,
            schema_name="statcan.rdaas.ClassificationSearchResult",
        ),
    )


async def get_classification_search_filters() -> SearchFilters:
    entries = await _get("/search/classifications/filters")
    return SearchFilters(
        filters=[FilterOption(parameter=e["parameter"], values=e["values"]) for e in entries],
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/search/classifications/filters",
            cached=False,
            schema_name="statcan.rdaas.SearchFilters",
        ),
    )


async def get_classification(classification_id: str, *, lang: str = "en") -> ClassificationDetail:
    resource_id = _resource_id(classification_id)
    cache_key = f"rdaas:classification:{resource_id}:{lang}"

    async def fetch() -> dict[str, Any]:
        return await _get(f"/classification/{resource_id}", params={"lang": lang})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    if not obj.get("@id"):
        raise NotFound(f"No classification found for id {resource_id!r}")

    levels = [
        ClassificationLevel(
            id=lvl.get("@id", ""),
            level_depth=lvl.get("levelDepth", 0),
            name=lvl.get("name", ""),
            code_count=lvl.get("codeCount", 0),
        )
        for lvl in obj.get("levels", [])
    ]
    return ClassificationDetail(
        id=obj.get("@id", ""),
        name=obj.get("name", ""),
        abbreviation=obj.get("abbreviation"),
        audience=obj.get("audience", ""),
        status=obj.get("status", ""),
        standard_status=obj.get("standardStatus"),
        is_harmonized=obj.get("isHarmonized"),
        catalogue_number=obj.get("catalogueNumber"),
        version_name=obj.get("versionName"),
        valid_from=obj.get("validFrom"),
        release_date=obj.get("releaseDate"),
        last_updated=obj.get("lastUpdated"),
        background=obj.get("background"),
        related_classification_ids=list_or_empty(obj, "relatedClassifications"),
        levels=levels,
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/classification/{resource_id}",
            cached=was_cached,
            schema_name="statcan.rdaas.ClassificationDetail",
        ),
    )


async def _get_or_empty(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET, treating a 200-with-empty-body response as "no data" (`{}`).

    Verified live: `/classification/{id}/categories/detailed` returns
    HTTP 200 with a zero-byte body for the CURRENT released NAICS
    classification specifically (2022.1.0, id MJRdRiFsfmJAprtT) — this
    is not true of NAICS in general: every retired NAICS version tried
    (e.g. 2017.3.0, id S049Pjk4RIUgw6j2, ~434KB) and the NAICS Trade
    Variant (id oufGyF9pTCpcm8OJ, ~381KB) return full category data,
    and NAICS 2022.1.0's own `/indexes` endpoint separately returns
    ~8MB of data — so this is an upstream gap specific to this one
    classification id's `/categories/detailed` (and `/exclusions`)
    response, not a general "NAICS has no data" situation. A caller
    who needs the current NAICS 2022 code list despite this gap can
    get it indirectly via the "NAICS Canada 2017.3.0 to 2022.1.0"
    concordance (rdaas_search_concordances) — its `target_code`/
    `target_descriptor` fields are real current-NAICS codes and
    descriptions, confirmed live. A plain `response.json()` on an
    empty body raises a JSON decode error, so this wrapper treats
    that specific failure as "empty" rather than letting it propagate
    as an unrelated parsing exception.
    """
    try:
        return await _get(path, params=params)
    except httpx.DecodingError:
        return {}


def _graph_entries(obj: dict[str, Any]) -> list[dict[str, Any]]:
    return obj.get("@graph", [])


def _exclusion_from_json(e: dict[str, Any]) -> ClassificationExclusion:
    return ClassificationExclusion(
        id=e.get("@id", ""),
        source_id=e.get("source", ""),
        source_code_value=e.get("sourceCodeValue", ""),
        term=e.get("term", ""),
        target_id=e.get("target", ""),
        target_code_value=e.get("targetCodeValue", ""),
    )


def _index_entry_from_json(e: dict[str, Any]) -> ClassificationIndexEntry:
    return ClassificationIndexEntry(
        id=e.get("@id", ""),
        index_id=int(e.get("indexId", 0)),
        primary_term=e.get("primaryTerm"),
        other_examples=list_or_empty(e, "otherExamples"),
        illustrative_examples=list_or_empty(e, "illustrativeExamples"),
        inclusions=list_or_empty(e, "inclusions"),
        internal_examples=list_or_empty(e, "internalExamples"),
        index_code_id=e.get("indexCode"),
        index_code_value=e.get("indexCodeValue"),
        index_code_descriptor=e.get("indexCodeDescriptor"),
    )


async def get_classification_categories_detailed(
    classification_id: str, *, lang: str = "en"
) -> ClassificationCategoriesDetailed:
    resource_id = _resource_id(classification_id)
    obj = await _get_or_empty(
        f"/classification/{resource_id}/categories/detailed", params={"lang": lang}
    )
    entries = _graph_entries(obj)
    categories = [
        ClassificationCategory(
            id=e.get("@id", ""),
            code=e.get("code", ""),
            descriptor=e.get("descriptor", ""),
            definition=e.get("definition"),
            level_depth=e.get("levelDepth"),
            main_duties=list_or_empty(e, "mainDuties"),
            employment_requirements=list_or_empty(e, "employmentRequirements"),
        )
        for e in entries
    ]
    return ClassificationCategoriesDetailed(
        classification_id=resource_id,
        categories=categories,
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/classification/{resource_id}/categories/detailed",
            cached=False,
            schema_name="statcan.rdaas.ClassificationCategoriesDetailed",
            coverage=(
                "empty: RDaaS itself returns no category data for this classification id "
                "(confirmed for the current released NAICS 2022.1.0 specifically -- retired "
                "NAICS versions and the NAICS Trade Variant return full data, so this is not "
                "true of NAICS in general). If this is the current NAICS and you need its code "
                "list, try rdaas_get_concordance_maps on the 'NAICS Canada 2017.3.0 to "
                "2022.1.0' concordance instead -- its target_code/target_descriptor fields are "
                "the same current-NAICS codes and descriptions."
            )
            if not entries
            else None,
        ),
    )


async def get_classification_exclusions(
    classification_id: str, *, lang: str = "en"
) -> ClassificationExclusions:
    resource_id = _resource_id(classification_id)
    obj = await _get_or_empty(f"/classification/{resource_id}/exclusions", params={"lang": lang})
    entries = _graph_entries(obj)
    exclusions = [_exclusion_from_json(e) for e in entries]
    return ClassificationExclusions(
        classification_id=resource_id,
        exclusions=exclusions,
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/classification/{resource_id}/exclusions",
            cached=False,
            schema_name="statcan.rdaas.ClassificationExclusions",
            coverage=(
                "empty: RDaaS itself returns no exclusions data for this classification id "
                "(confirmed live for both the current NAICS 2022.1.0 and a retired NAICS "
                "version, so this one genuinely appears to have no exclusions data in RDaaS "
                "across versions, unlike categories/detailed above)"
            )
            if not entries
            else None,
        ),
    )


async def get_classification_indexes(classification_id: str) -> ClassificationIndexes:
    resource_id = _resource_id(classification_id)
    obj = await _get(f"/classification/{resource_id}/indexes")
    entries = _graph_entries(obj)
    index_entries = [_index_entry_from_json(e) for e in entries]
    return ClassificationIndexes(
        classification_id=resource_id,
        entries=index_entries,
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/classification/{resource_id}/indexes",
            cached=False,
            schema_name="statcan.rdaas.ClassificationIndexes",
        ),
    )


async def get_classification_index_entry(
    classification_id: str, index_id: int
) -> ClassificationIndexEntry:
    resource_id = _resource_id(classification_id)
    obj = await _get(f"/classification/{resource_id}/indexes/entry/{index_id}")
    if not obj.get("@id"):
        raise NotFound(f"No index entry {index_id!r} for classification {resource_id!r}")
    return _index_entry_from_json(obj)


async def get_term_exclusion(term_exclusion_id: str, *, lang: str = "en") -> TermExclusion:
    resource_id = _resource_id(term_exclusion_id)
    obj = await _get(f"/termexclusion/{resource_id}", params={"lang": lang})
    if not obj.get("@id"):
        raise NotFound(f"No term exclusion found for id {resource_id!r}")
    return TermExclusion(
        id=obj.get("@id", ""),
        source_id=obj.get("source", ""),
        source_code_value=obj.get("sourceCodeValue", ""),
        term=obj.get("term", ""),
        target_id=obj.get("target", ""),
        target_code_value=obj.get("targetCodeValue", ""),
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/termexclusion/{resource_id}",
            cached=False,
            schema_name="statcan.rdaas.TermExclusion",
        ),
    )


def _concordance_summary(entry: dict[str, Any]) -> ConcordanceSummary:
    return ConcordanceSummary(
        id=entry.get("@id", ""),
        name=entry.get("name", ""),
        version_number=entry.get("versionNumber"),
        audience=entry.get("audience", ""),
        status=entry.get("status", ""),
        last_updated=entry.get("lastUpdated"),
        source_id=entry.get("source", ""),
        source_name=entry.get("source_name", ""),
        source_version_number=entry.get("sourceVersionNumber"),
        target_id=entry.get("target", ""),
        target_name=entry.get("target_name", ""),
        target_version_number=entry.get("targetVersionNumber"),
    )


async def search_concordances(
    query: str = "",
    *,
    start: int = 0,
    limit: int = constants.DEFAULT_SEARCH_LIMIT,
    audience: list[str] | None = None,
    status: list[str] | None = None,
    lang: str = "en",
) -> ConcordanceSearchResult:
    params: dict[str, Any] = {
        "start": start,
        "limit": min(limit, constants.MAX_SEARCH_LIMIT),
        "lang": lang,
    }
    if query:
        params["q"] = query
    if audience:
        params["audience"] = audience
    if status:
        params["status"] = status

    obj = await _get("/search/concordances", params=params)
    results_obj = obj.get("results", obj)
    entries = results_obj.get("@graph", [])
    return ConcordanceSearchResult(
        results=[_concordance_summary(e) for e in entries],
        found=obj.get("found", len(entries)),
        start=obj.get("start", start),
        limit=obj.get("limit", limit),
        facets=_facets_from_json(obj),
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/search/concordances",
            cached=False,
            schema_name="statcan.rdaas.ConcordanceSearchResult",
        ),
    )


async def get_concordance_search_filters() -> SearchFilters:
    entries = await _get("/search/concordances/filters")
    return SearchFilters(
        filters=[FilterOption(parameter=e["parameter"], values=e["values"]) for e in entries],
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/search/concordances/filters",
            cached=False,
            schema_name="statcan.rdaas.SearchFilters",
        ),
    )


async def get_concordance(concordance_id: str, *, lang: str = "en") -> ConcordanceDetail:
    resource_id = _resource_id(concordance_id)
    cache_key = f"rdaas:concordance:{resource_id}:{lang}"

    async def fetch() -> dict[str, Any]:
        return await _get(f"/concordance/{resource_id}", params={"lang": lang})

    obj, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)
    if not obj.get("@id"):
        raise NotFound(f"No concordance found for id {resource_id!r}")

    return ConcordanceDetail(
        id=obj.get("@id", ""),
        name=obj.get("name", ""),
        version_number=obj.get("versionNumber"),
        audience=obj.get("audience", ""),
        status=obj.get("status", ""),
        source_id=obj.get("source", ""),
        source_name=obj.get("source_name", ""),
        target_id=obj.get("target", ""),
        target_name=obj.get("target_name", ""),
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/concordance/{resource_id}",
            cached=was_cached,
            schema_name="statcan.rdaas.ConcordanceDetail",
        ),
    )


async def get_concordance_maps(concordance_id: str, *, lang: str = "en") -> CodeMapList:
    resource_id = _resource_id(concordance_id)
    obj = await _get(f"/concordance/{resource_id}/maps", params={"lang": lang})
    entries = obj.get("@graph", [])
    maps = [
        CodeMapEntry(
            id=e.get("@id", ""),
            map_type=e.get("maptype", ""),
            source_code=e.get("sourceCode", ""),
            source_descriptor=e.get("sourceDescriptor", ""),
            source_since_version=e.get("sourceSinceVersion"),
            target_code=e.get("targetCode", ""),
            target_descriptor=e.get("targetDescriptor", ""),
            target_since_version=e.get("targetSinceVersion"),
        )
        for e in entries
    ]
    return CodeMapList(
        concordance_id=resource_id,
        maps=maps,
        provenance=make_provenance(
            source="statcan-rdaas",
            url=f"{constants.BASE_URL}/concordance/{resource_id}/maps",
            cached=False,
            schema_name="statcan.rdaas.CodeMapList",
        ),
    )

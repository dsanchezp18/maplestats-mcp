"""HTTP client for every Canadian Socrata (SODA) portal in constants.PORTALS.

Field names and shapes below are verified against live responses: the
discovery API's `resource`/`classification`/`link`/`permalink`
envelope, the Views API's flat metadata document (with Unix-seconds
timestamps — see shared/socrata.py's `parse_epoch_seconds`), and the
SODA resource API's plain list-of-row-objects shape. These portals
previously lived in five copy-pasted `socrata_<portal>` modules whose
code differed only in the domain; they now share this client keyed by
`portal`.
"""

from __future__ import annotations

import re
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.socrata import constants
from maplestats_mcp.modules.socrata.schemas import (
    CategoryCount,
    CategoryList,
    ColumnInfo,
    DatasetDetail,
    DatasetSearchResult,
    DatasetSummary,
    PortalInfo,
    PortalList,
    RowQueryResult,
    TagCount,
    TagList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.json_utils import get_or, list_or_empty
from maplestats_mcp.shared.rate_limiter import get_limiter
from maplestats_mcp.shared.socrata import (
    CATALOG_BASE_URL,
    SocrataConfig,
    _raise_for_status_error,  # pyright: ignore[reportPrivateUsage]
    catalog_search,
    excerpt,
    facet_categories,
    facet_tags,
    get_view,
    parse_dt,
    parse_epoch_seconds,
)
from maplestats_mcp.shared.upstream_text import network_error

# Socrata's "four-by-four" dataset id. Checked before it goes into a URL path,
# so a value like "../x" or "abcd-1234?$where=" cannot reach another resource.
_DATASET_ID = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")

# French only: the portals publish their own text in English (New Brunswick
# writes both languages in the same field).
_SOURCE_TEXT_FR = (
    "Titres, descriptions, catégories et étiquettes tels que publiés par le portail, en "
    "anglais sauf au Nouveau-Brunswick, qui écrit les deux langues dans le même champ."
)


def _dataset_id(dataset_id: str, lang: str = "en") -> str:
    cleaned = dataset_id.strip().lower()
    if not cleaned:
        raise_localized(
            InvalidInput,
            "dataset_id must not be empty.",
            "dataset_id ne doit pas être vide.",
            lang,
        )
    if not _DATASET_ID.match(cleaned):
        raise_localized(
            InvalidInput,
            "dataset_id must be a Socrata id of the form 'abcd-1234' (two groups of four "
            f"letters or digits), as returned by socrata_search_datasets; got {dataset_id!r}.",
            "dataset_id doit être un identifiant Socrata de la forme « abcd-1234 » (deux "
            "groupes de quatre lettres ou chiffres), comme ceux que renvoie "
            f"socrata_search_datasets ; reçu {dataset_id!r}.",
            lang,
        )
    return cleaned


def _check_page(limit: int, offset: int, limit_max: int, lang: str) -> None:
    if limit < 1 or limit > limit_max:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {limit_max}, got {limit}.",
            f"limit doit être entre 1 et {limit_max}; reçu {limit}.",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être supérieur ou égal à 0 ; reçu {offset}.",
            lang,
        )


def _config(portal: str, lang: str = "en") -> SocrataConfig:
    info = constants.PORTALS.get(portal)
    if info is None:
        raise_localized(
            InvalidInput,
            f"portal must be one of {sorted(constants.PORTALS)}, got {portal!r}.",
            f"portal doit être l'une des valeurs {sorted(constants.PORTALS)}; reçu {portal!r}.",
            lang,
        )
    return SocrataConfig(
        source=f"socrata-{portal}",
        domain=info.domain,
        rate_limit_per_second=constants.RATE_LIMIT_PER_SECOND,
        rate_limit_capacity=constants.RATE_LIMIT_CAPACITY,
    )


def list_portals(lang: str = "en") -> PortalList:
    """Every portal key this module accepts, with its display name and domain."""
    return PortalList(
        portals=[
            PortalInfo(
                portal=key,
                name=pick(lang, info.name_en, info.name_fr),
                domain=info.domain,
                bilingual_content=info.bilingual_content,
            )
            for key, info in constants.PORTALS.items()
        ],
        provenance=make_provenance(
            source="socrata",
            url=pick(
                lang,
                "(static portal registry in modules/socrata/constants.py)",
                "(registre fixe des portails dans modules/socrata/constants.py)",
            ),
            cached=False,
            schema_name="socrata.PortalList",
            lang=lang,
        ),
    )


def _dataset_summary(obj: dict[str, Any]) -> DatasetSummary:
    resource = obj.get("resource") or {}
    classification = obj.get("classification") or {}
    return DatasetSummary(
        id=resource["id"],
        name=resource.get("name") or resource["id"],
        description_excerpt=excerpt(
            resource.get("description") or "", constants.DESCRIPTION_EXCERPT_LENGTH
        ),
        category=classification.get("domain_category") or None,
        tags=list_or_empty(classification, "domain_tags"),
        dataset_type=resource.get("lens_view_type") or "unknown",
        updated_at=parse_dt(resource.get("updatedAt")),
        download_count=get_or(resource, "download_count", 0),
        permalink=obj.get("permalink") or "",
        landing_page_url=obj.get("link") or obj.get("permalink") or "",
    )


def _column_info(obj: dict[str, Any]) -> ColumnInfo:
    return ColumnInfo(
        name=obj.get("name") or obj.get("fieldName") or "",
        field_name=obj.get("fieldName") or "",
        data_type=obj.get("dataTypeName") or "unknown",
        description=obj.get("description") or None,
    )


async def search_datasets(
    portal: str,
    query: str = "",
    *,
    category: str | None = None,
    tag: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> DatasetSearchResult:
    """Search one portal's dataset catalogue; ``lang`` sets the language of messages and notes."""
    config = _config(portal, lang)
    _check_page(limit, offset, constants.SEARCH_LIMIT_MAX, lang)

    async def fetch() -> dict[str, Any]:
        return await catalog_search(
            config,
            query=query,
            category=category,
            tag=tag,
            limit=limit,
            offset=offset,
            lang=lang,
        )

    cache_key = f"{config.source}:search:{query}:{category}:{tag}:{limit}:{offset}"
    result, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SEARCH_SECONDS, fetch)
    raw_results = list_or_empty(result, "results")
    total_count = get_or(result, "resultSetSize", len(raw_results))
    datasets = [_dataset_summary(obj) for obj in raw_results]
    return DatasetSearchResult(
        portal=portal,
        datasets=datasets,
        total_count=total_count,
        returned_count=len(datasets),
        limit=limit,
        offset=offset,
        query=query,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.DatasetSearchResult",
            coverage=pick(
                lang,
                f"{len(datasets)} of {total_count} total matches returned",
                f"{len(datasets)} résultats renvoyés sur {total_count} au total",
            ),
            limits=pick(
                lang,
                f"limit capped at {constants.SEARCH_LIMIT_MAX} per request",
                f"limit plafonné à {constants.SEARCH_LIMIT_MAX} par requête. {_SOURCE_TEXT_FR}",
            ),
            lang=lang,
        ),
    )


async def get_dataset(portal: str, dataset_id: str, lang: str = "en") -> DatasetDetail:
    config = _config(portal, lang)
    dataset_id = _dataset_id(dataset_id, lang)

    async def fetch() -> dict[str, Any]:
        return await get_view(config, dataset_id, lang)

    obj, was_cached = await cached_fetch(
        f"{config.source}:get_view:{dataset_id}", constants.CACHE_TTL_DATASET_SECONDS, fetch
    )
    license_info = obj.get("license") or {}
    return DatasetDetail(
        portal=portal,
        id=obj["id"],
        name=obj.get("name") or obj["id"],
        description=obj.get("description") or "",
        category=obj.get("category") or None,
        attribution=obj.get("attribution") or None,
        license_name=license_info.get("name"),
        license_url=license_info.get("termsLink"),
        tags=list_or_empty(obj, "tags"),
        columns=[_column_info(c) for c in list_or_empty(obj, "columns")],
        created_at=parse_epoch_seconds(obj.get("createdAt")),
        rows_updated_at=parse_epoch_seconds(obj.get("rowsUpdatedAt")),
        publication_date=parse_epoch_seconds(obj.get("publicationDate")),
        download_count=get_or(obj, "downloadCount", 0),
        view_count=get_or(obj, "viewCount", 0),
        landing_page_url=f"https://{config.domain}/d/{obj['id']}",
        csv_download_url=f"https://{config.domain}/api/views/{obj['id']}/rows.csv?accessType=DOWNLOAD",
        query_url=f"https://{config.domain}/resource/{obj['id']}.json",
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/api/views/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata.DatasetDetail",
            limits=pick(lang, "", _SOURCE_TEXT_FR) or None,
            lang=lang,
        ),
    )


# A rejected SoQL query, as data.calgary.ca and data.edmonton.ca answer it (seen live
# 2026-11-09): HTTP 400 with {"message": "Query coordinator error: <code>; <reason>;
# position: Map(... line -> \"SELECT `col1`, `col2`, ... |> SELECT ...\")",
# "errorCode": "<code>"}. The position part echoes the dataset's whole internal column
# list, and the generic 200-character error detail cut that list into the visible
# text, so the reason read like a complaint about unrelated columns. Only the code
# and the reason are kept.
_SOQL_MESSAGE = re.compile(
    r"^(?:Query coordinator error:\s*)?(?P<code>query\.soql\.[\w.-]+)\s*;\s*"
    r"(?P<reason>.*?)(?:\s*;\s*position:.*)?$",
    re.DOTALL,
)

_SOQL_HINTS: dict[str, tuple[str, str]] = {
    "query.soql.column-not-in-group-bys": (
        (
            "With an aggregate such as count(*) or sum(...) in select, list every other "
            "selected column in group (SoQL $group), e.g. select='permittype, count(*)', "
            "group='permittype'."
        ),
        (
            "Avec un agrégat comme count(*) ou sum(...) dans select, indiquez toutes les autres "
            "colonnes choisies dans group (SoQL $group), par ex. select='permittype, count(*)', "
            "group='permittype'."
        ),
    ),
    "query.soql.no-such-column": (
        "Use the field_name values that socrata_get_dataset lists for this dataset.",
        "Utilisez les valeurs field_name que socrata_get_dataset donne pour ce jeu de données.",
    ),
}


def _soql_error(exc: httpx.HTTPStatusError) -> tuple[str, str] | None:
    """The (error code, reason) of a rejected SoQL query, or None for any other error."""
    if exc.response.status_code != 400:
        return None
    try:
        body = exc.response.json()
    except ValueError:
        return None
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str):
        return None
    match = _SOQL_MESSAGE.match(message.strip())
    if match is None:
        return None
    reason = " ".join(match.group("reason").split()).rstrip(".")
    return match.group("code"), reason


def _raise_soql_error(code: str, reason: str, lang: str) -> NoReturn:
    hint_en, hint_fr = _SOQL_HINTS.get(code, ("", ""))
    raise_localized(
        InvalidInput,
        f"Socrata rejected the SoQL query: {reason} ({code}). {hint_en}".rstrip(),
        f"Socrata a refusé la requête SoQL : {reason} ({code}). {hint_fr}".rstrip(),
        lang,
    )


async def _fetch_rows(
    config: SocrataConfig, dataset_id: str, params: dict[str, Any], lang: str
) -> list[dict[str, Any]]:
    """GET the SODA resource endpoint; a rejected SoQL query raises with Socrata's reason.

    shared/socrata.py's query_rows has no $group or $having and reports a SoQL
    rejection through its generic, truncated error detail, hence this module's own call.
    """
    context = f"{config.source}:query_rows:{dataset_id}"
    url = f"https://{config.domain}/resource/{dataset_id}.json"
    await get_limiter(
        config.source, rate=config.rate_limit_per_second, capacity=config.rate_limit_capacity
    ).acquire()
    try:
        data = await api_get(url, params=params)
    except httpx.HTTPStatusError as exc:
        soql = _soql_error(exc)
        if soql is not None:
            _raise_soql_error(*soql, lang)
        _raise_for_status_error(exc, context, lang)
    except httpx.HTTPError as exc:
        raise network_error(context, exc, lang) from exc
    return data if isinstance(data, list) else []


async def query_dataset_rows(
    portal: str,
    dataset_id: str,
    *,
    select: str | None = None,
    where: str | None = None,
    order: str | None = None,
    group: str | None = None,
    having: str | None = None,
    q: str | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> RowQueryResult:
    """Run a SoQL query against one dataset's rows; ``lang`` sets the language of messages.

    ``group`` and ``having`` are SoQL's $group and $having, so counts and sums by
    category are computed by Socrata over every matching row, not over one page.
    """
    config = _config(portal, lang)
    dataset_id = _dataset_id(dataset_id, lang)
    _check_page(limit, offset, constants.ROWS_LIMIT_MAX, lang)
    if having and not group:
        raise_localized(
            InvalidInput,
            "having filters grouped rows, so it needs group as well (SoQL $having works "
            "only with $group).",
            "having filtre des lignes regroupées : il faut aussi group (le $having de SoQL "
            "ne fonctionne qu'avec $group).",
            lang,
        )

    clauses = {
        "$select": select,
        "$where": where,
        "$group": group,
        "$having": having,
        "$order": order,
        "$q": q,
    }
    params: dict[str, Any] = {"$limit": limit, "$offset": offset}
    params.update({key: value for key, value in clauses.items() if value})

    async def fetch() -> list[dict[str, Any]]:
        return await _fetch_rows(config, dataset_id, params, lang)

    cache_key = (
        f"{config.source}:rows:{dataset_id}:{select}:{where}:{group}:{having}:{order}:{q}"
        f":{limit}:{offset}"
    )
    rows, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_ROWS_SECONDS, fetch)
    grouped_en = "; groups and aggregates computed by Socrata ($group)" if group else ""
    grouped_fr = " ; groupes et agrégats calculés par Socrata ($group)" if group else ""
    return RowQueryResult(
        portal=portal,
        dataset_id=dataset_id,
        rows=rows,
        returned_count=len(rows),
        limit=limit,
        offset=offset,
        select=select,
        where=where,
        order=order,
        group=group,
        having=having,
        q=q,
        provenance=make_provenance(
            source=config.source,
            url=f"https://{config.domain}/resource/{dataset_id}.json",
            cached=was_cached,
            schema_name="socrata.RowQueryResult",
            limits=pick(
                lang,
                f"rows capped at {constants.ROWS_LIMIT_MAX} per request{grouped_en}",
                f"lignes plafonnées à {constants.ROWS_LIMIT_MAX} par requête ; noms de "
                f"colonnes et valeurs tels que publiés par le portail{grouped_fr}",
            ),
            lang=lang,
        ),
    )


async def list_categories(portal: str, lang: str = "en") -> CategoryList:
    config = _config(portal, lang)

    async def fetch() -> list[dict[str, Any]]:
        return await facet_categories(config, lang)

    raw, was_cached = await cached_fetch(
        f"{config.source}:domain_categories", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    categories = [
        CategoryCount(category=c["domain_category"], dataset_count=get_or(c, "count", 0))
        for c in raw
        if c.get("domain_category")
    ]
    return CategoryList(
        portal=portal,
        categories=categories,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}/domain_categories?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.CategoryList",
            limits=pick(lang, "", _SOURCE_TEXT_FR) or None,
            lang=lang,
        ),
    )


async def list_tags(portal: str, lang: str = "en") -> TagList:
    config = _config(portal, lang)

    async def fetch() -> list[dict[str, Any]]:
        return await facet_tags(config, lang)

    raw, was_cached = await cached_fetch(
        f"{config.source}:domain_tags", constants.CACHE_TTL_FACET_SECONDS, fetch
    )
    tags = [
        TagCount(tag=t["domain_tag"], dataset_count=get_or(t, "count", 0))
        for t in raw
        if t.get("domain_tag")
    ]
    return TagList(
        portal=portal,
        tags=tags,
        provenance=make_provenance(
            source=config.source,
            url=f"{CATALOG_BASE_URL}/domain_tags?domains={config.domain}",
            cached=was_cached,
            schema_name="socrata.TagList",
            limits=pick(lang, "", _SOURCE_TEXT_FR) or None,
            lang=lang,
        ),
    )

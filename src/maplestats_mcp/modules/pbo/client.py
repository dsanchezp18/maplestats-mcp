"""Client for the PBO distribution API.

Checked live 2026-09-26:

1. /publications is paginated at a fixed 15 per page (per_page and limit
   are ignored) with Laravel `meta` (total, last_page); `types=ES,NT`
   filters by type code; `tags=<id>` by tag. There is no text filter on
   the list; /search?query= returns a JSON list of {type, score,
   payload} across content types, of which 'Publication' ones are kept.
2. /publications/<id> returns the full record: bilingual titles and
   abstract (metadata.abstract_en|fr), permalinks.<lang>.website, the PDF
   at artifacts.main.<lang>.public, and pboml_document['data-url'], a
   base64 YAML data URL.
3. PBOML slices: markdown, heading, svg (charts, no data), table
   (variables: id -> label and is_descriptive; content: rows whose values
   are numbers or {en, fr} text), html (a <table> per language) and
   kvlist (key/value rows; print_only ones are author credits). Of 42
   sampled publications, 21 had tables: costing notes since 2021 and most
   reports since 2025. Archived and pre-2021 items have no PBOML.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
import yaml
from bs4 import BeautifulSoup

from maplestats_mcp.modules.pbo import constants
from maplestats_mcp.modules.pbo.schemas import (
    PboPublication,
    PboPublicationSummary,
    PboSearchResult,
    PboTable,
    Value,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_ID = re.compile(r"^[A-Z]{2,6}-\d{4}-\d{3}(-[A-Z])?$")


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    await _LIMITER.acquire()
    try:
        return await api_get(constants.API + path, params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise NotFound(f"pbo: {path} does not exist.") from exc
        raise UpstreamError(f"pbo: {path} returned HTTP {exc.response.status_code}.") from exc
    except httpx.DecodingError as exc:
        # The API answers some unknown paths with the website's HTML page.
        raise NotFound(f"pbo: {path} did not return JSON.") from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(f"pbo: {path} did not respond in time.") from exc


def _pick(value: Any, lang: str) -> str:
    """Text from a {en, fr} dict (or a plain value)."""
    if isinstance(value, dict):
        chosen = value.get(lang) or value.get("en") or value.get("fr") or ""
        return " ".join(chosen) if isinstance(chosen, list) else str(chosen)
    return "" if value is None else str(value)


def summary(record: dict[str, Any], lang: str) -> PboPublicationSummary:
    kind = str(record.get("type") or "")
    english, french = constants.TYPES.get(kind, (kind, kind))
    metadata = record.get("metadata") or {}
    permalinks = (record.get("permalinks") or {}).get(lang) or {}
    pdf = (((record.get("artifacts") or {}).get("main") or {}).get(lang) or {}).get("public")
    return PboPublicationSummary(
        id=str(record.get("id") or ""),
        type=kind,
        type_label=french if lang == "fr" else english,
        title=str(record.get(f"title_{lang}") or record.get("title_en") or ""),
        abstract=metadata.get(f"abstract_{lang}") or metadata.get("abstract_en"),
        release_date=str(record.get("release_date") or "")[:10] or None,
        url=permalinks.get("website"),
        pdf_url=pdf,
    )


def _provenance(url: str, cached: bool, schema: str, coverage: str | None = None) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"pbo.{schema}",
        freshness="as PBO publishes (several a week)",
        coverage=coverage,
        limits="PBO materials: personal and non-commercial use, unaltered, with attribution",
    )


async def search_publications(
    query: str = "",
    *,
    types: list[str] | None = None,
    page: int = 1,
    lang: str = "en",
) -> PboSearchResult:
    """Newest publications, or those matching `query`, optionally of some types."""
    if page < 1:
        raise InvalidInput("pbo: page must be >= 1.")
    unknown = [t for t in types or [] if t not in constants.TYPES]
    if unknown:
        raise InvalidInput(f"pbo: unknown types {unknown}; use {list(constants.TYPES)}.")

    if query.strip():

        async def fetch_search() -> list[dict[str, Any]]:
            found = await _get("search", {"query": query.strip()})
            if not isinstance(found, list):
                raise UpstreamError("pbo: search returned an unexpected shape.")
            return [r["payload"] for r in found if r.get("type") == "Publication"]

        records, cached = await cached_fetch(
            f"pbo:search:{query.strip().lower()}", constants.LIST_TTL_SECONDS, fetch_search
        )
        matched = [r for r in records if not types or r.get("type") in types]
        start = (page - 1) * constants.PAGE_SIZE
        shown = matched[start : start + constants.PAGE_SIZE]
        last_page = max(1, -(-len(matched) // constants.PAGE_SIZE))
        return PboSearchResult(
            publications=[summary(r, lang) for r in shown],
            returned_count=len(shown),
            total_matched=len(matched),
            page=page,
            last_page=last_page,
            provenance=_provenance(
                constants.API + "search", cached, "PboSearchResult", "ranked by PBO's search"
            ),
        )

    params: dict[str, Any] = {"page": page}
    if types:
        params["types"] = ",".join(types)

    async def fetch_list() -> dict[str, Any]:
        return await _get("publications", params)

    listing, cached = await cached_fetch(
        f"pbo:list:{params}", constants.LIST_TTL_SECONDS, fetch_list
    )
    meta = listing.get("meta") or {}
    records = listing.get("data") or []
    return PboSearchResult(
        publications=[summary(r, lang) for r in records],
        returned_count=len(records),
        total_matched=int(meta.get("total") or len(records)),
        page=int(meta.get("current_page") or page),
        last_page=int(meta.get("last_page") or page),
        provenance=_provenance(
            constants.API + "publications", cached, "PboSearchResult", "newest first"
        ),
    )


# ------------------------------------------------------------------ PBOML


def decode_pboml(record: dict[str, Any]) -> dict[str, Any] | None:
    url = (record.get("pboml_document") or {}).get("data-url")
    if not url or "," not in url:
        return None
    try:
        document = yaml.safe_load(base64.b64decode(url.split(",", 1)[1]))
    except (ValueError, yaml.YAMLError) as exc:
        raise UpstreamError("pbo: the publication's PBOML document does not parse.") from exc
    return document if isinstance(document, dict) else None


def _cell(value: Any, lang: str) -> Value:
    if isinstance(value, dict):
        return _pick(value, lang) or None
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _table(slice_: dict[str, Any], lang: str) -> PboTable | None:
    kind = slice_.get("type")
    common = {
        "reference": _pick(slice_.get("referenced_as"), lang) or None,
        "label": _pick(slice_.get("label"), lang) or None,
        "sources": [_pick(s, lang) for s in slice_.get("sources") or []],
        "notes": [_pick(n, lang) for n in slice_.get("notes") or []],
    }
    if kind == "table":
        variables = slice_.get("variables") or {}
        labels = {key: _pick((v or {}).get("label"), lang) or key for key, v in variables.items()}
        rows = [
            {labels.get(k, k): _cell(v, lang) for k, v in row.items()}
            for row in slice_.get("content") or []
            if isinstance(row, dict)
        ]
        return PboTable(kind="table", columns=list(labels.values()), rows=rows, **common)
    if kind == "html":
        soup = BeautifulSoup(_pick(slice_.get("content"), lang), "html.parser")
        if soup.find("table") is None:
            return None
        cells = [
            [" ".join(td.get_text(" ").split()) for td in tr.find_all(["td", "th"])]
            for tr in soup.find_all("tr")
        ]
        return PboTable(kind="html", cells=[c for c in cells if any(c)], **common)
    if kind == "kvlist" and not slice_.get("print_only"):
        rows: list[dict[str, Value]] = [
            {
                "key": _pick((item.get("key") or {}).get("content"), lang),
                "value": _pick((item.get("value") or {}).get("content"), lang),
            }
            for item in slice_.get("content") or []
        ]
        return PboTable(kind="kvlist", columns=["key", "value"], rows=rows, **common)
    return None


async def get_publication(publication_id: str, *, lang: str = "en") -> PboPublication:
    """One publication with its tables and text, from its PBOML document."""
    publication_id = publication_id.strip().upper()
    if not _ID.match(publication_id):
        raise InvalidInput(f"pbo: {publication_id!r} is not a PBO id like 'LEG-2526-012-S'.")

    async def fetch() -> dict[str, Any]:
        record = await _get(f"publications/{publication_id}")
        return record.get("data", record) if isinstance(record, dict) else {}

    record, cached = await cached_fetch(
        f"pbo:publication:{publication_id}", constants.PUBLICATION_TTL_SECONDS, fetch
    )
    document = decode_pboml(record)
    tables: list[PboTable] = []
    text_parts: list[str] = []
    for slice_ in (document or {}).get("slices") or []:
        if not isinstance(slice_, dict):
            continue
        kind = slice_.get("type")
        if kind in ("table", "html", "kvlist"):
            if (table := _table(slice_, lang)) is not None:
                tables.append(table)
        elif kind == "heading":
            text_parts.append("## " + _pick(slice_.get("content"), lang))
        elif kind == "markdown":
            text_parts.append(_pick(slice_.get("content"), lang))
    text = "\n\n".join(p for p in text_parts if p.strip())
    return PboPublication(
        publication=summary(record, lang),
        has_structured_content=document is not None,
        tables=tables,
        text=text[: constants.TEXT_MAX_CHARS] or None,
        text_truncated=len(text) > constants.TEXT_MAX_CHARS,
        provenance=_provenance(
            constants.API + f"publications/{publication_id}", cached, "PboPublication"
        ),
    )

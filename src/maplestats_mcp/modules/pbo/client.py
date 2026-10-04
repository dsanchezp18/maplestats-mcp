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

Information requests, checked live 2026-09-27:

4. /information-requests lists all 1,121 requests (December 2008 on),
   newest first, 40 per page; it ignores every filter parameter tried
   (department, status, search, query), so the register is read whole
   and filtered here. /information-requests/<numeric id> adds `files`
   (letters, nearly all PDF) and staff `contacts`, which are not passed
   on. Letter URLs are {en: {public}, fr: {public}} or, for a bilingual
   letter, a bare {public}; a language may be null.
5. Request numbers are mostly IR + 4 digits, but 9 are RI…, and some
   carry a suffix (IR0080a); the detail path takes only the numeric id,
   so the number is resolved through the register.
"""

from __future__ import annotations

import asyncio
import base64
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

import httpx
import yaml
from bs4 import BeautifulSoup

from maplestats_mcp.modules.pbo import constants
from maplestats_mcp.modules.pbo.schemas import (
    PboInformationRequest,
    PboInformationRequestFile,
    PboInformationRequestList,
    PboInformationRequestSummary,
    PboPublication,
    PboPublicationSummary,
    PboSearchResult,
    PboTable,
    Value,
)
from maplestats_mcp.shared.arg_checks import check_range
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_ID = re.compile(r"^[A-Z]{2,6}-\d{4}-\d{3}(-[A-Z])?$")


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def _text(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


async def _get(path: str, params: dict[str, Any] | None = None, lang: str = "en") -> Any:
    await _LIMITER.acquire()
    try:
        return await api_get(constants.API + path, params=params, timeout=60.0)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            _raise(NotFound, f"pbo: {path} does not exist.", f"pbo : {path} n'existe pas.", lang)
        _raise(
            UpstreamError,
            f"pbo: {path} returned HTTP {status}.",
            f"pbo : {path} a renvoyé HTTP {status}.",
            lang,
        )
    except httpx.DecodingError:
        # The API answers some unknown paths with the website's HTML page.
        _raise(
            NotFound,
            f"pbo: {path} did not return JSON.",
            f"pbo : {path} n'a pas renvoyé de JSON.",
            lang,
        )
    except httpx.HTTPError:
        _raise(
            UpstreamUnavailable,
            f"pbo: {path} did not respond in time.",
            f"pbo : {path} n'a pas répondu à temps.",
            lang,
        )


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


def _provenance(
    url: str, cached: bool, schema: str, coverage: str | None = None, lang: str = "en"
) -> Any:
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"pbo.{schema}",
        freshness=_text(
            "as PBO publishes (several a week)",
            "au fil des publications du DPB (plusieurs par semaine)",
            lang,
        ),
        coverage=coverage,
        lang=lang,
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
        _raise(InvalidInput, "pbo: page must be >= 1.", "pbo : page doit être >= 1.", lang)
    unknown = [t for t in types or [] if t not in constants.TYPES]
    if unknown:
        _raise(
            InvalidInput,
            f"pbo: unknown types {unknown}; use {list(constants.TYPES)}.",
            f"pbo : types inconnus {unknown} ; utilisez {list(constants.TYPES)}.",
            lang,
        )

    if query.strip():

        async def fetch_search() -> list[dict[str, Any]]:
            found = await _get("search", {"query": query.strip()}, lang)
            if not isinstance(found, list):
                _raise(
                    UpstreamError,
                    "pbo: search returned an unexpected shape.",
                    "pbo : la recherche a renvoyé une forme inattendue.",
                    lang,
                )
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
                constants.API + "search",
                cached,
                "PboSearchResult",
                _text("ranked by PBO's search", "classés par la recherche du DPB", lang),
                lang,
            ),
        )

    params: dict[str, Any] = {"page": page}
    if types:
        params["types"] = ",".join(types)

    async def fetch_list() -> dict[str, Any]:
        return await _get("publications", params, lang)

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
            constants.API + "publications",
            cached,
            "PboSearchResult",
            _text("newest first", "les plus récentes d'abord", lang),
            lang,
        ),
    )


# ------------------------------------------------------------------ PBOML


def decode_pboml(record: dict[str, Any], lang: str = "en") -> dict[str, Any] | None:
    url = (record.get("pboml_document") or {}).get("data-url")
    if not url or "," not in url:
        return None
    try:
        document = yaml.safe_load(base64.b64decode(url.split(",", 1)[1]))
    except (ValueError, yaml.YAMLError):
        _raise(
            UpstreamError,
            "pbo: the publication's PBOML document does not parse.",
            "pbo : le document PBOML de la publication ne peut pas être lu.",
            lang,
        )
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
        _raise(
            InvalidInput,
            f"pbo: {publication_id!r} is not a PBO id like 'LEG-2526-012-S'.",
            f"pbo : {publication_id!r} n'est pas un identifiant du DPB comme 'LEG-2526-012-S'.",
            lang,
        )

    async def fetch() -> dict[str, Any]:
        record = await _get(f"publications/{publication_id}", lang=lang)
        return record.get("data", record) if isinstance(record, dict) else {}

    record, cached = await cached_fetch(
        f"pbo:publication:{publication_id}", constants.PUBLICATION_TTL_SECONDS, fetch
    )
    document = decode_pboml(record, lang)
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
            constants.API + f"publications/{publication_id}", cached, "PboPublication", lang=lang
        ),
    )


# ------------------------------------------------------ information requests


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _label(table: dict[str, tuple[str, str]], code: str | None, lang: str) -> str | None:
    if not code:
        return None
    english, french = table.get(code, (code, code))
    return french if lang == "fr" else english


def _today() -> date:
    # PBO sets deadlines in Ottawa time.
    return datetime.now(ZoneInfo("America/Toronto")).date()


def request_summary(
    record: dict[str, Any], lang: str, today: date | None = None
) -> PboInformationRequestSummary:
    department = record.get("department") or {}
    status = str(record.get("request_status") or "")
    disposition = record.get("disposition_status") or None
    deadline = str(record.get("deadline_date") or "")[:10] or None
    extension = str(record.get("extension_date") or "")[:10] or None
    late: int | None = None
    due = extension or deadline
    if status.startswith("pending") and due:
        late = max(0, ((today or _today()) - date.fromisoformat(due)).days)
    other = "fr" if lang == "en" else "en"
    return PboInformationRequestSummary(
        id=str(record.get("internal_id") or ""),
        summary=str(record.get(f"summary_{lang}") or record.get(f"summary_{other}") or ""),
        department=str(
            department.get(f"name_{lang}") or department.get(f"name_{other}") or "unknown"
        ),
        department_acronym=department.get(f"acronym_{lang}") or department.get("acronym_en"),
        request_date=str(record.get("request_date") or "")[:10] or None,
        deadline_date=deadline,
        extension_date=extension,
        status=status,
        status_label=_label(constants.REQUEST_STATUSES, status, lang) or status,
        disposition=disposition,
        disposition_label=_label(constants.DISPOSITIONS, disposition, lang),
        disposition_note=record.get(f"disposition_note_{lang}")
        or record.get(f"disposition_note_{other}"),
        days_past_deadline=late,
        url=((record.get("permalinks") or {}).get(lang) or {}).get("website"),
    )


async def _register(lang: str = "en") -> tuple[list[dict[str, Any]], bool]:
    """Every information request, newest first, read page by page."""

    async def fetch() -> list[dict[str, Any]]:
        first = await _get("information-requests", {"page": 1}, lang)
        last_page = int((first.get("meta") or {}).get("last_page") or 1)
        gate = asyncio.Semaphore(constants.IR_FETCH_CONCURRENCY)

        async def one(page: int) -> list[dict[str, Any]]:
            async with gate:
                listing = await _get("information-requests", {"page": page}, lang)
            return list(listing.get("data") or [])

        rest = await asyncio.gather(*(one(p) for p in range(2, last_page + 1)))
        rows = list(first.get("data") or [])
        for page_rows in rest:
            rows.extend(page_rows)
        if not rows:
            _raise(
                UpstreamError,
                "pbo: the information-request register came back empty.",
                "pbo : le registre des demandes d'information est revenu vide.",
                lang,
            )
        return rows

    return await cached_fetch("pbo:information-requests", constants.REGISTER_TTL_SECONDS, fetch)


def _matches(record: dict[str, Any], words: list[str]) -> bool:
    haystack = _fold(" ".join(str(record.get(k) or "") for k in ("summary_en", "summary_fr")))
    return all(w in haystack for w in words)


def _department_matches(record: dict[str, Any], wanted: str) -> bool:
    department = record.get("department") or {}
    acronyms = {_fold(str(department.get(k) or "")) for k in ("acronym_en", "acronym_fr")}
    if wanted in acronyms:
        return True
    names = _fold(" ".join(str(department.get(k) or "") for k in ("name_en", "name_fr")))
    return wanted in names


def _date_arg(value: str, name: str, lang: str = "en") -> str:
    value = value.strip()
    if not value:
        return ""
    if not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
        _raise(
            InvalidInput,
            f"pbo: {name} must be YYYY, YYYY-MM or YYYY-MM-DD, not {value!r}.",
            f"pbo : {name} doit être au format AAAA, AAAA-MM ou AAAA-MM-JJ, pas {value!r}.",
            lang,
        )
    return value


async def search_information_requests(
    query: str = "",
    *,
    department: str = "",
    status: str | None = None,
    disposition: str | None = None,
    since: str = "",
    until: str = "",
    page: int = 1,
    lang: str = "en",
) -> PboInformationRequestList:
    """Filter PBO's register of information requests, newest first, with counts."""
    if page < 1:
        _raise(InvalidInput, "pbo: page must be >= 1.", "pbo : page doit être >= 1.", lang)
    if status and status not in constants.REQUEST_STATUSES and status != "open":
        statuses = list(constants.REQUEST_STATUSES)
        _raise(
            InvalidInput,
            f"pbo: unknown status {status!r}; use 'open' or one of {statuses}.",
            f"pbo : statut inconnu {status!r} ; utilisez 'open' ou l'un de {statuses}.",
            lang,
        )
    if disposition and disposition not in constants.DISPOSITIONS:
        dispositions = list(constants.DISPOSITIONS)
        _raise(
            InvalidInput,
            f"pbo: unknown disposition {disposition!r}; use {dispositions}.",
            f"pbo : issue inconnue {disposition!r} ; utilisez {dispositions}.",
            lang,
        )
    since, until = _date_arg(since, "since", lang), _date_arg(until, "until", lang)
    # Compare at the shorter precision: since="2024-06" and until="2024" overlap.
    shared = min(len(since), len(until))
    # The shared range check words its error in English only.
    if lang == "fr" and shared and since[:shared] > until[:shared]:
        _raise(
            InvalidInput,
            "",
            f"since ({since}) est postérieur à until ({until}) ; inversez-les ou élargissez "
            "la plage.",
            lang,
        )
    check_range(since[:shared] or None, until[:shared] or None, "since", "until")

    rows, cached = await _register(lang)
    words = _fold(query).split()
    wanted_department = _fold(department.strip())
    matched: list[dict[str, Any]] = []
    for record in rows:
        requested = str(record.get("request_date") or "")[:10]
        record_status = str(record.get("request_status") or "")
        if words and not _matches(record, words):
            continue
        if wanted_department and not _department_matches(record, wanted_department):
            continue
        if status == "open" and not record_status.startswith("pending"):
            continue
        if status and status != "open" and record_status != status:
            continue
        if disposition and record.get("disposition_status") != disposition:
            continue
        # A prefix compare lets "2024" or "2024-03" bound a whole year or month.
        if since and requested[: len(since)] < since:
            continue
        if until and requested[: len(until)] > until:
            continue
        matched.append(record)

    start = (page - 1) * constants.IR_PAGE_SIZE
    shown = matched[start : start + constants.IR_PAGE_SIZE]
    today = _today()
    departments = Counter(
        str((r.get("department") or {}).get(f"acronym_{lang}") or "unknown") for r in matched
    )
    return PboInformationRequestList(
        requests=[request_summary(r, lang, today) for r in shown],
        returned_count=len(shown),
        total_matched=len(matched),
        page=page,
        last_page=max(1, -(-len(matched) // constants.IR_PAGE_SIZE)),
        by_disposition=dict(
            Counter(str(r.get("disposition_status") or "none") for r in matched).most_common()
        ),
        by_status=dict(Counter(str(r.get("request_status") or "") for r in matched).most_common()),
        by_department=dict(departments.most_common(15)),
        provenance=_provenance(
            constants.API + "information-requests",
            cached,
            "PboInformationRequestList",
            _text(
                f"{len(rows)} requests since December 2008, newest first",
                f"{len(rows)} demandes depuis décembre 2008, les plus récentes d'abord",
                lang,
            ),
            lang,
        ),
    )


def _file(entry: dict[str, Any], lang: str) -> PboInformationRequestFile:
    urls = entry.get("urls") or {}
    other = "fr" if lang == "en" else "en"
    url = urls.get("public")
    if url is None:
        url = (urls.get(lang) or {}).get("public") or (urls.get(other) or {}).get("public")
    kind = str(entry.get("document_type") or "")
    return PboInformationRequestFile(
        document_type=kind,
        label=entry.get(f"description_{lang}")
        or _label(constants.DOCUMENT_TYPES, kind, lang)
        or kind,
        mime=entry.get("mime"),
        url=url,
    )


async def get_information_request(request_id: str, *, lang: str = "en") -> PboInformationRequest:
    """One information request with its letters."""
    wanted = request_id.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}\d{3,5}[A-Z]?", wanted):
        _raise(
            InvalidInput,
            f"pbo: {request_id!r} is not a PBO request number like 'IR0959'.",
            f"pbo : {request_id!r} n'est pas un numéro de demande du DPB comme 'IR0959'.",
            lang,
        )
    rows, _ = await _register(lang)
    found = next((r for r in rows if str(r.get("internal_id") or "").upper() == wanted), None)
    if found is None:
        _raise(
            NotFound,
            f"pbo: no information request {wanted}.",
            f"pbo : aucune demande d'information {wanted}.",
            lang,
        )

    async def fetch() -> dict[str, Any]:
        record = await _get(f"information-requests/{found['id']}", lang=lang)
        return record.get("data", record) if isinstance(record, dict) else {}

    record, cached = await cached_fetch(
        f"pbo:information-request:{found['id']}", constants.PUBLICATION_TTL_SECONDS, fetch
    )
    return PboInformationRequest(
        request=request_summary(record, lang),
        files=[_file(f, lang) for f in record.get("files") or [] if isinstance(f, dict)],
        provenance=_provenance(
            constants.API + f"information-requests/{found['id']}",
            cached,
            "PboInformationRequest",
            lang=lang,
        ),
    )

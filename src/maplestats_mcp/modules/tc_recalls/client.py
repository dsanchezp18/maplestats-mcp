"""Client for Transport Canada's vehicle recall API.

Responses are lists of name/value pairs, flattened by `_values`/`_named`.
Search columns are labelled in the request language ("Recall number" /
"Numéro de rappel"), so rows are read by position, confirmed stable in
both languages; summary fields use fixed database names.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from maplestats_mcp.modules.tc_recalls import constants
from maplestats_mcp.modules.tc_recalls.schemas import (
    AffectedVehicle,
    RecallDetail,
    RecallRow,
    RecallSearchResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.fr_typography import NBSP, fr_or_en, french_spacing, lang_error
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_NAME = re.compile(r"^[\w .&'-]{1,60}$")

# The French search answers the same values as the English one (live
# 2026-09-23: only the column labels change), so a French caller is told
# the rows are the source's own names rather than a translation.
_FR_ROWS_NOTE = (
    "Les lignes de recherche sont identiques en français et en anglais : les numéros, "
    "fabricants, marques, modèles et dates proviennent de Transports Canada tels que publiés, "
    "sans traduction. La catégorie, le système et la description en français se trouvent "
    'dans tc_recalls_get (lang="fr").'
)


def _count_fr(value: int) -> str:
    """A count with the French thousands separator (no-break space)."""
    return f"{value:,}".replace(",", NBSP)


def _root(lang: str) -> str:
    return constants.BASE_URL.format(lang="fra" if lang == "fr" else "eng")


async def _get(
    url: str, params: dict[str, Any] | None = None, lang: str = "en"
) -> tuple[list[list[Any]], bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            raise lang_error(
                UpstreamError,
                lang,
                f"tc_recalls: {url} returned HTTP {exc.response.status_code}.",
                f"tc_recalls : {url} a répondu HTTP {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"tc_recalls: {url} could not be reached.",
                f"tc_recalls : {url} est injoignable.",
            ) from exc

    body, cached = await cached_fetch(
        f"tc-recalls:{url}:{sorted((params or {}).items())}", constants.CACHE_TTL_SECONDS, fetch
    )
    rows = body.get("ResultSet") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise lang_error(
            UpstreamError,
            lang,
            "tc_recalls: response has no ResultSet.",
            "tc_recalls : la réponse n'a pas de ResultSet.",
        )
    return rows, cached


def _values(row: list[dict[str, Any]]) -> list[Any]:
    return [(field.get("Value") or {}).get("Literal") for field in row]


def _named(row: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(field.get("Name")): (field.get("Value") or {}).get("Literal") for field in row}


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        month, day, year = str(value).split(" ")[0].split("/")
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _segment(value: str, name: str, lang: str = "en") -> str:
    value = value.strip()
    if not _NAME.match(value):
        raise lang_error(
            InvalidInput,
            lang,
            f"{name} contains unsupported characters: {value!r}.",
            f"{name} contient des caractères non pris en charge : {value!r}.",
        )
    return quote(value.lower())


def _row(row: list[dict[str, Any]]) -> RecallRow:
    values = _values(row) + [None] * 6
    return RecallRow(
        recall_number=str(values[0]),
        manufacturer=values[1],
        model=values[2],
        make=values[3],
        model_year=_int(values[4]),
        recall_date=_date(values[5]),
    )


async def _all_rows(url: str, lang: str = "en") -> tuple[list[list[Any]], bool, bool]:
    """Every matching row, whether all were read, and whether all came from the cache."""
    rows: list[list[Any]] = []
    cached_all = True
    for number in range(1, constants.FETCH_PAGES_MAX + 1):
        chunk, cached = await _get(url, {"limit": constants.FETCH_PAGE_SIZE, "page": number}, lang)
        rows.extend(chunk)
        cached_all = cached_all and cached
        if len(chunk) < constants.FETCH_PAGE_SIZE:
            return rows, True, cached_all
    return rows, False, cached_all


async def search(
    *,
    make: str | None = None,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    page: int = 1,
    order: str = "newest",
    lang: str = "en",
) -> RecallSearchResult:
    """Recalls matching the filters, sorted by recall date (newest first by default).

    The API lists roughly oldest first with page/limit paging and has no
    sort parameter or total, so every matching row is read (pages of
    FETCH_PAGE_SIZE, cached) and sorted and paged here.
    """
    if not (make or model or year_from or year_to):
        raise lang_error(
            InvalidInput,
            lang,
            "Give at least a make, a model, or a model-year range.",
            "indiquez au moins une marque, un modèle ou une plage d'années-modèles.",
        )
    if limit < 1 or limit > constants.LIMIT_MAX:
        raise lang_error(
            InvalidInput,
            lang,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX} ; reçu {limit}.",
        )
    if page < 1:
        raise lang_error(
            InvalidInput,
            lang,
            f"page must be >= 1, got {page}.",
            f"page doit être supérieur ou égal à 1 ; reçu {page}.",
        )
    if order not in ("newest", "oldest"):
        raise lang_error(
            InvalidInput,
            lang,
            f"order must be 'newest' or 'oldest', got {order!r}.",
            f"order doit être 'newest' ou 'oldest' ; reçu {order!r}.",
        )
    path = "recall"
    if make:
        path += f"/make-name/{_segment(make, 'make', lang)}"
    if model:
        path += f"/model-name/{_segment(model, 'model', lang)}"
    if year_from or year_to:
        first, last = year_from or year_to, year_to or year_from
        if first is None or last is None or first < 1900 or last > 2100:
            raise lang_error(
                InvalidInput,
                lang,
                f"Invalid model-year range {year_from}-{year_to}.",
                f"plage d'années-modèles invalide : {year_from}-{year_to}.",
            )
        if first > last:
            # Same English text as shared check_range, which has no French.
            raise lang_error(
                InvalidInput,
                lang,
                f"year_from ({first}) is after year_to ({last}); swap them or widen the range.",
                f"year_from ({first}) est postérieur à year_to ({last}) ; inversez-les ou "
                "élargissez la plage.",
            )
        path += f"/year-range/{first}-{last}"
    url = _root(lang) + path
    # Upstream order is oldest first with no total: a make-only search for
    # Ford started at 1975 and gave no way to reach recent recalls. The rows
    # are only roughly in date order (25 of 5,181 Ford rows out of order,
    # live 2026-10-03), so every matching row is read and sorted here.
    raw, complete, cached = await _all_rows(url, lang)
    recalls = [_row(r) for r in raw]
    known_make = bool(recalls) or not make
    if not recalls and make and (model or year_from or year_to):
        # An unknown make answers an empty list; tell it apart from a known
        # make with no recall for this model or these years.
        make_rows, _ = await _get(
            _root(lang) + f"recall/make-name/{_segment(make, 'make', lang)}",
            {"limit": 1, "page": 1},
            lang,
        )
        known_make = bool(make_rows)
    if not known_make:
        raise lang_error(
            InvalidInput,
            lang,
            f"No recall at all lists make {make!r}; check the spelling (makes are "
            "matched as written, e.g. 'Honda', 'Mercedes-Benz').",
            f"aucun rappel ne mentionne la marque {make!r} ; vérifiez l'orthographe (les "
            "marques sont comparées telles qu'écrites, p. ex. 'Honda', 'Mercedes-Benz').",
        )
    recalls.sort(
        key=lambda r: (r.recall_date or date.min, r.recall_number),
        reverse=order == "newest",
    )
    start = (page - 1) * limit
    shown = recalls[start : start + limit]
    has_more = start + len(shown) < len(recalls)
    note = None
    if not recalls:
        note = fr_or_en(
            lang,
            "No recall matched; check the model spelling (matched as written).",
            "Aucun rappel ne correspond ; vérifiez l'orthographe du modèle (comparé tel qu'écrit).",
        )
    elif has_more:
        order_fr = "Plus récents" if order == "newest" else "Plus anciens"
        note = fr_or_en(
            lang,
            f"{order.capitalize()} first: recalls {start + 1} to {start + len(shown)} of "
            f"{len(recalls):,}; next page is page={page + 1}.",
            f"{order_fr} d'abord : rappels {start + 1} à {start + len(shown)} sur "
            f"{_count_fr(len(recalls))} ; page suivante : page={page + 1}.",
        )
    if lang == "fr":
        note = " ".join(part for part in (note, french_spacing(_FR_ROWS_NOTE)) if part)
    request = fr_or_en(
        lang,
        f"Request: GET {url}?limit={constants.FETCH_PAGE_SIZE}&page=N for every page "
        f"(the API lists oldest first); sorted here by recall date, {order} first",
        f"Requête : GET {url}?limit={constants.FETCH_PAGE_SIZE}&page=N pour chaque page "
        "(l'API liste les plus anciens d'abord) ; triés ici par date de rappel, "
        f"{'plus récents' if order == 'newest' else 'plus anciens'} d'abord",
    )
    partial = fr_or_en(
        lang,
        f"only the first {len(recalls):,} matching rows were read; narrow the search",
        f"seules les {_count_fr(len(recalls))} premières lignes correspondantes ont été lues ; "
        "resserrez la recherche",
    )
    return RecallSearchResult(
        recalls=shown,
        returned_count=len(shown),
        total_matched=len(recalls),
        has_more=has_more,
        order=order,
        page=page,
        limit=limit,
        note=note,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="tc_recalls.RecallSearchResult",
            limits=join_limits(request, None if complete else partial, note),
            lang=lang,
        ),
    )


async def get_recall(recall_number: str, lang: str = "en") -> RecallDetail:
    number = recall_number.strip()
    if not number.isdigit():
        raise lang_error(
            InvalidInput,
            lang,
            f"recall_number must be digits like '2021001', got {recall_number!r}.",
            f"recall_number doit être composé de chiffres, p. ex. '2021001' ; reçu "
            f"{recall_number!r}.",
        )
    url = _root(lang) + f"recall-summary/recall-number/{number}"
    raw, cached = await _get(url, lang=lang)
    rows = [_named(r) for r in raw]
    if not rows:
        raise lang_error(
            NotFound,
            lang,
            f"No Transport Canada recall {number}.",
            f"aucun rappel {number} chez Transports Canada.",
        )
    first = rows[0]
    suffix = "FTXT" if lang == "fr" else "ETXT"
    vehicles = {
        (r.get("MAKE_NAME_NM"), r.get("MODEL_NAME_NM"), _int(r.get("DATE_YEAR_CD"))) for r in rows
    }
    return RecallDetail(
        recall_number=number,
        manufacturer_recall_number=first.get("MANUFACTURER_RECALL_NO_TXT"),
        recall_date=_date(first.get("RECALL_DATE_DTE")),
        category=first.get(f"CATEGORY_{suffix}"),
        system=first.get(f"SYSTEM_TYPE_{suffix}"),
        notification_type=first.get(f"NOTIFICATION_TYPE_{suffix}"),
        units_affected=_int(first.get("UNIT_AFFECTED_NBR")),
        # English descriptions use CRLF line breaks, French ones LF (live
        # 2026-10-03, recall 2021001); both come back with LF.
        description=(first.get(f"COMMENT_{suffix}") or "").replace("\r\n", "\n").strip() or None,
        affected_vehicles=[
            AffectedVehicle(make=m, model=mo, model_year=y)
            for m, mo, y in sorted(vehicles, key=lambda v: (str(v[0]), str(v[1]), v[2] or 0))
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="tc_recalls.RecallDetail",
            lang=lang,
        ),
    )

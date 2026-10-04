"""HTTP client for the Canadian Trademarks Database (CIPO) search API.

Confirmed live 2026-09-20 against
`https://ised-isde.canada.ca/cipo/trademark-search/srch`. This endpoint
backs the public search UI's own XHR calls and is not documented as a
public API anywhere, but it is a plain unauthenticated JSON POST -- no
session cookie, CSRF token, or API key was required to reproduce it with
a bare `fetch()`, and it stayed reachable outside the browser. Real
quirks found and handled:

1. `searchfield1` accepts only the exact internal codes the search UI's
   dropdown uses (see constants.SEARCH_FIELD_TO_API) -- any other value
   returns HTTP 500 "Internal Server Error" with no detail, not a 400.
2. There is no pagination parameter: `start`/`startRow`/`offset`/`page`/
   `pageNum` were all tried live and every one was silently ignored
   (the response is identical regardless). `maxReturn` only controls how
   many of the top-ranked matches come back in one call; results beyond
   `maxReturn` are not reachable at all through this endpoint.
3. An empty `textfield1` is a deliberate match-all against the entire
   trademark register (confirmed live: >2 million records), the same
   convention this codebase's other search tools already use for an
   empty query.
4. `mediaFileNames` in the response are relative paths (e.g.
   "/media/1137536.png"); this client resolves them to full URLs.
5. Nice classification and CIPO status are not searched through
   `textfield1`: the UI sends them as lists of codes in `nicetextfield1`
   and `cipotextfield1` (its search.js). Checked live 2026-10-03:
   textfield1="45" with the Nice field matched the whole register
   (2,188,587) and nicetextfield1=["45"] matched 97,515; textfield1=
   "REGISTERED" with the status field answered HTTP 500 and
   cipotextfield1=["19"] matched 871,520. A code the UI does not offer
   (Nice "46", status "12") is ignored, giving the whole register or
   nothing, so both are checked here before sending.
6. Number fields given text match nothing ("abc" gave 0 for application,
   registration and international numbers), and an application number
   with thousands separators ("1,244,495") also gave 0, so numbers are
   checked and separators dropped before sending.
"""

from __future__ import annotations

import json
import re
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.ised.cipo import constants
from maplestats_mcp.modules.ised.cipo.schemas import TrademarkRecord, TrademarkSearchResult
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_post
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_TOOL = "ised_cipo:search_trademarks"


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English stays the plain message; French gets the typed template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


_NUMBER_FIELDS = (
    "application_number",
    "original_application_number",
    "international_registration_number",
)
# Registration numbers carry an optional letter prefix: "TMA700000",
# "TMA 700000", "TMA700,000" and "700000" all matched live (2026-10-03).
_REGISTRATION = re.compile(r"^[A-Z]{0,4}\s*[\d,]+$", re.IGNORECASE)
_SEPARATORS = re.compile(r"[\s,]+")


def _nice_classes(criteria: str, context: str, lang: str) -> list[str]:
    parts = [p for p in _SEPARATORS.split(criteria) if p]
    low, high = constants.NICE_CLASS_MIN, constants.NICE_CLASS_MAX
    if not parts or not all(p.isdigit() for p in parts):
        _raise(
            InvalidInput,
            f"{context}: nice_classification criteria must be one or more Nice class "
            f"numbers ({low}-{high}), e.g. '9' or '9, 35'; got {criteria!r}.",
            f"{context} : les critères nice_classification doivent être un ou plusieurs "
            f"numéros de classe de Nice ({low} à {high}), p. ex. '9' ou '9, 35' ; "
            f"reçu {criteria!r}.",
            lang,
        )
    classes = sorted({int(p) for p in parts})
    bad = [c for c in classes if not low <= c <= high]
    if bad:
        _raise(
            InvalidInput,
            f"{context}: Nice classes run from {low} to {high}; got {bad}.",
            f"{context} : les classes de Nice vont de {low} à {high} ; reçu {bad}.",
            lang,
        )
    return [str(c) for c in classes]


def _status_codes(criteria: str, context: str, lang: str) -> list[str]:
    by_label: dict[str, list[int]] = {}
    for code, label in constants.CIPO_STATUS_CODES.items():
        by_label.setdefault(label.lower(), []).append(code)
    codes: set[int] = set()
    for part in (p.strip() for p in criteria.split(",")):
        if not part:
            continue
        if part.isdigit() and int(part) in constants.CIPO_STATUS_CODES:
            codes.add(int(part))
        elif part.lower() in by_label:
            codes.update(by_label[part.lower()])
        else:
            labels = sorted(set(constants.CIPO_STATUS_CODES.values()))
            known = sorted(constants.CIPO_STATUS_CODES)
            _raise(
                InvalidInput,
                f"{context}: unknown cipo_status {part!r}; give status names or codes "
                f"separated by commas, from {labels} (codes {known}).",
                f"{context} : cipo_status inconnu {part!r} ; donnez des noms ou des codes de "
                f"statut séparés par des virgules, parmi {labels} (codes {known}). Les noms "
                "de statut sont ceux, en anglais, de la base de données.",
                lang,
            )
    if not codes:
        _raise(
            InvalidInput,
            f"{context}: cipo_status needs at least one status name or code.",
            f"{context} : cipo_status exige au moins un nom ou un code de statut.",
            lang,
        )
    return [str(c) for c in sorted(codes)]


def _number(search_field: str, criteria: str, context: str, lang: str) -> str:
    if search_field == "registration_number":
        if not _REGISTRATION.match(criteria):
            _raise(
                InvalidInput,
                f"{context}: registration_number must be a number, optionally with its "
                f"prefix (e.g. 'TMA700000' or '700000'); got {criteria!r}.",
                f"{context} : registration_number doit être un numéro, avec ou sans son "
                f"préfixe (p. ex. 'TMA700000' ou '700000') ; reçu {criteria!r}.",
                lang,
            )
        return criteria
    digits = _SEPARATORS.sub("", criteria)
    if not digits.isdigit():
        _raise(
            InvalidInput,
            f"{context}: {search_field} must be digits only; got {criteria!r}.",
            f"{context} : {search_field} ne doit contenir que des chiffres ; reçu {criteria!r}.",
            lang,
        )
    return digits


def _trademark_record(doc: dict[str, Any]) -> TrademarkRecord:
    intl_reg_nos = [value for value in doc.get("intlRegNos") or [] if value]
    media_names = doc.get("mediaFileNames") or []
    return TrademarkRecord(
        id=doc.get("id") or "",
        application_number=doc.get("appNo") or "",
        mark_name=doc.get("markName") or "",
        mark_type=doc.get("type") or None,
        status_code=doc.get("statusCode"),
        status_description=doc.get("statusDesc") or None,
        nice_classes=doc.get("niceCodes") or [],
        international_registration_numbers=intl_reg_nos,
        image_urls=[f"{constants.MEDIA_BASE_URL}{name}" for name in media_names],
    )


async def search_trademarks(
    search_field: str,
    criteria: str,
    *,
    max_return: int = constants.MAX_RETURN_DEFAULT,
    lang: str = "en",
) -> TrademarkSearchResult:
    """Search the Canadian Trademarks Database by one field."""
    api_field = constants.SEARCH_FIELD_TO_API.get(search_field)
    if api_field is None:
        fields = sorted(constants.SEARCH_FIELD_TO_API)
        _raise(
            InvalidInput,
            f"{_TOOL}: search_field must be one of {fields}, got {search_field!r}.",
            f"{_TOOL} : search_field doit valoir l'une de {fields}, reçu {search_field!r}.",
            lang,
        )
    if max_return < 1 or max_return > constants.MAX_RETURN_MAX:
        _raise(
            InvalidInput,
            f"{_TOOL}: max_return must be between 1 and "
            f"{constants.MAX_RETURN_MAX}, got {max_return}.",
            f"{_TOOL} : max_return doit être compris entre 1 et "
            f"{constants.MAX_RETURN_MAX}, reçu {max_return}.",
            lang,
        )

    context = "ised_cipo:search_trademarks"
    criteria = criteria.strip()
    text = criteria
    nice: list[str] | None = None
    status: list[str] | None = None
    # An empty criteria stays the documented match-all for every field.
    if criteria and search_field == "nice_classification":
        nice, text = _nice_classes(criteria, context, lang), ""
    elif criteria and search_field == "cipo_status":
        status, text = _status_codes(criteria, context, lang), ""
    elif criteria and (search_field in _NUMBER_FIELDS or search_field == "registration_number"):
        text = _number(search_field, criteria, context, lang)
    body = {
        "domIntlFilter": "1",
        "searchfield1": api_field,
        "textfield1": text,
        "display": "list",
        "maxReturn": str(max_return),
        "nicetextfield1": nice,
        "cipotextfield1": status,
    }

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_post(constants.BASE_URL, json_body=body)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = exc.response.text[:200]
            _raise(
                UpstreamError,
                f"{_TOOL} returned HTTP {status}: {detail}",
                f"{_TOOL} a renvoyé HTTP {status} : {detail}",
                lang,
            )
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                f"{_TOOL} did not respond in time "
                "(already retried by shared/http.py). Try again shortly.",
                f"{_TOOL} n'a pas répondu à temps (déjà relancé). Réessayez sous peu.",
                lang,
            )

    cache_key = f"ised-cipo:search:{api_field}:{text}:{nice}:{status}:{max_return}"
    payload, was_cached = await cached_fetch(cache_key, constants.CACHE_TTL_SECONDS, fetch)

    if not isinstance(payload, dict) or "docs" not in payload:
        _raise(
            UpstreamError,
            f"{_TOOL}: unexpected response shape (missing 'docs').",
            f"{_TOOL} : forme de réponse inattendue ('docs' absent).",
            lang,
        )

    # The search is a JSON POST, so the URL alone cannot reproduce it.
    request = f"POST {constants.BASE_URL} with JSON body {json.dumps(body)}"
    limits = (
        f"Request: {request}. "
        "No pagination beyond max_return -- results ranked past the "
        "requested count are not reachable through this endpoint."
    )
    if lang == "fr":
        request_fr = f"POST {constants.BASE_URL} avec le corps JSON {json.dumps(body)}"
        limits = french_spacing(
            f"Requête : {request_fr}. Pas de pagination au-delà de max_return : les "
            "résultats classés après le nombre demandé ne sont pas accessibles par ce "
            "point de terminaison. L'API de recherche ne répond qu'en anglais ; les "
            "libellés de statut et de type de marque sont reproduits tels quels."
        )

    docs = payload.get("docs") or []
    return TrademarkSearchResult(
        records=[_trademark_record(doc) for doc in docs],
        returned_count=len(docs),
        total_matched=payload.get("numFound") or 0,
        search_field=search_field,
        criteria=criteria,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.BASE_URL,
            cached=was_cached,
            schema_name="ised_cipo.TrademarkSearchResult",
            limits=limits,
            lang=lang,
        ),
    )

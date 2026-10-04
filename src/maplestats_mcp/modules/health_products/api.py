"""Requests, provenance and streaming shared by the four health products APIs.

Behaviour checked live on 2026-10-03 against health-products.canada.ca:

- Every endpoint takes `type=json` and most take `lang=en|fr`; `lang=fr`
  translates code labels (status, class, schedule, route, licence type)
  but not free text that companies filed (brand names, NHP purposes and
  risk statements stay as filed).
- A lookup by `id=` that matches nothing answers 200 with an object whose
  fields are all null and whose own id is 0 (DPD drug product, company,
  MDALL licence, Canada Vigilance report), not a 404. `is_blank` spots it.
- A lookup by `id=` answers a single object on some endpoints (DPD
  drugproduct, status, packaging; MDALL licence) and a list on others,
  sometimes for the same endpoint depending on how many rows match; LNHPD
  wraps some answers as {"metadata": ..., "data": [...]}. `as_list`
  folds all three shapes.
- Unknown query parameters are ignored, so a misspelt filter returns the
  whole table (15 MB for DPD drug products) rather than an error. Only the
  documented filters are sent.
- The DPD veterinary species endpoint answers 404 for a product with no
  species; a non-numeric `id` answers 400 {"Message": "The request is invalid."}.
- Whole-table answers can be large (LNHPD licences: 148 MB of JSON, about
  60 s before the first byte); `stream_objects` reads such an array one
  object at a time with gzip transfer, so memory stays bounded.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterator, Awaitable
from datetime import datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get, new_client, request_headers
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

BASE_URL = "https://health-products.canada.ca/api"
SOURCE = "health_products"
LICENCE = (
    "Source: Health Canada. Contains information licensed under the Open Government "
    "Licence - Canada (https://open.canada.ca/en/open-government-licence-canada)."
)
LICENCE_FR = (
    "Source : Santé Canada. Contient des informations visées par la Licence du gouvernement "
    "ouvert – Canada (https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada)."
)
# The start of each typed error's French template (shared/i18n), so a message
# already in French is not restated.
_FRENCH_STARTS = ("Entrée invalide", "Aucune correspondance", "La source amont")


def fail(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English as before; French in the typed template ("Entrée invalide : ...")."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


def say(en: str, fr: str, lang: str) -> str:
    """The English text, or the French one with no-break spaces."""
    return french_spacing(fr) if lang == "fr" else en


async def in_lang[T](lang: str, call: Awaitable[T]) -> T:
    """Await `call`; for lang="fr", restate an English error from the shared helpers.

    The request helpers here word their errors in English (they serve every
    language); a French call gets the French template with the English
    detail kept, so nothing is lost.
    """
    try:
        return await call
    except (InvalidInput, NotFound, UpstreamError, UpstreamUnavailable) as exc:
        if lang != "fr" or str(exc).startswith(_FRENCH_STARTS):
            raise
        raise_typed(
            type(exc),
            f"health-products.canada.ca (Santé Canada) : la requête a échoué (détail : {exc})",
            "fr",
        )


# The API answered 20 quick requests in a row without throttling; a modest
# pace keeps a burst of detail lookups (up to 11 per drug product) polite.
_LIMITER = get_limiter(SOURCE, rate=8.0, capacity=12.0)
_STREAM_CLIENT = new_client(timeout=180.0)
# An object larger than this without a closing brace means the array is not
# the flat JSON this reader expects.
_MAX_OBJECT_CHARS = 1_000_000


def url_for(path: str) -> str:
    return f"{BASE_URL}/{path.strip('/')}/"


async def get_json(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    lang: str | None = "en",
    missing_ok: bool = False,
    timeout: float = 60.0,
) -> Any:
    """GET one endpoint as JSON, with typed errors.

    `missing_ok` turns a 404 into an empty list (the veterinary species
    endpoint answers 404 for a product with no species).
    """
    query: dict[str, Any] = {**(params or {}), "type": "json"}
    if lang:
        query["lang"] = lang
    url = url_for(path)
    await _LIMITER.acquire()
    try:
        return await api_get(url, params=query, timeout=timeout)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404 and missing_ok:
            return []
        if status == 400:
            raise InvalidInput(
                f"health-products.canada.ca rejected the request to {path}."
            ) from exc
        if status == 404:
            raise NotFound(
                f"health-products.canada.ca has no {path} matching the request."
            ) from exc
        raise UpstreamError(
            f"health-products.canada.ca answered HTTP {status} for {path}."
        ) from exc
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable(
            f"health-products.canada.ca did not answer {path} within {timeout:.0f} s."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"health-products.canada.ca could not be reached for {path} ({type(exc).__name__})."
        ) from exc
    except ValueError as exc:
        raise UpstreamError(f"health-products.canada.ca sent invalid JSON for {path}.") from exc


def as_list(payload: Any) -> list[dict[str, Any]]:
    """Rows from a list, a single object, or a {"metadata", "data"} wrapper."""
    if isinstance(payload, dict) and "data" in payload and "metadata" in payload:
        payload = payload["data"]
    if payload is None:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise UpstreamError("health-products.canada.ca sent an answer that is not JSON rows.")


def is_blank(row: dict[str, Any], key: str) -> bool:
    """True for the all-null placeholder an unknown id returns (its id is 0)."""
    return not row.get(key)


def text(value: Any) -> str | None:
    """A trimmed string, or None for null and empty values."""
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def provenance(
    url: str,
    *,
    cached: bool,
    schema: str,
    freshness: str,
    coverage: str | None = None,
    limits: str | None = None,
    as_of: datetime | None = None,
    lang: str = "en",
    freshness_fr: str | None = None,
    coverage_fr: str | None = None,
    limits_fr: str | None = None,
) -> Provenance:
    """Provenance in the call's language: the `*_fr` texts are used for lang="fr"."""
    if lang == "fr":
        freshness = french_spacing(freshness_fr or freshness)
        coverage = french_spacing(coverage_fr or coverage) if coverage else None
        chosen = limits_fr or limits
        limits = french_spacing(chosen) if chosen else None
    return make_provenance(
        source=SOURCE,
        url=url,
        cached=cached,
        schema_name=f"health_products.{schema}",
        freshness=freshness,
        coverage=coverage,
        limits=limits,
        as_of=as_of,
        licence=LICENCE_FR if lang == "fr" else LICENCE,
        lang=lang,
    )


async def stream_objects(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    lang: str | None = "en",
) -> AsyncIterator[dict[str, Any]]:
    """Each object of a whole-table JSON array, decoded as it arrives.

    The array is never held whole: bytes are decoded incrementally and each
    object is parsed with `raw_decode` as soon as it is complete.
    """
    query: dict[str, Any] = {**(params or {}), "type": "json"}
    if lang:
        query["lang"] = lang
    url = url_for(path)
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    await _LIMITER.acquire()
    try:
        async with _STREAM_CLIENT.stream(
            "GET",
            url,
            params=query,
            headers=request_headers(url, {"Accept-Encoding": "gzip"}),
        ) as response:
            if response.status_code >= 400:
                raise UpstreamError(
                    f"health-products.canada.ca answered HTTP {response.status_code} for {path}."
                )
            buffer = ""
            async for chunk in response.aiter_bytes():
                buffer += utf8.decode(chunk)
                pos = 0
                while True:
                    start = buffer.find("{", pos)
                    if start < 0:
                        pos = len(buffer)
                        break
                    try:
                        obj, end = decoder.raw_decode(buffer, start)
                    except json.JSONDecodeError:
                        if len(buffer) - start > _MAX_OBJECT_CHARS:
                            raise UpstreamError(
                                f"health-products.canada.ca sent malformed JSON for {path}."
                            ) from None
                        pos = start
                        break
                    if isinstance(obj, dict):
                        yield obj
                    pos = end
                buffer = buffer[pos:]
            if buffer.strip(" \r\n\t,]"):
                raise UpstreamError(f"health-products.canada.ca cut short its answer for {path}.")
    except httpx.TimeoutException as exc:
        raise UpstreamUnavailable(
            f"health-products.canada.ca did not finish sending {path} in time."
        ) from exc
    except httpx.HTTPError as exc:
        raise UpstreamUnavailable(
            f"health-products.canada.ca could not be reached for {path} ({type(exc).__name__})."
        ) from exc

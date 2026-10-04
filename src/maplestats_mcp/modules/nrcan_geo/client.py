"""Client for NRCan's Geolocator and geographical names APIs."""

from __future__ import annotations

from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.nrcan_geo import constants
from maplestats_mcp.modules.nrcan_geo.schemas import (
    Location,
    LocationResult,
    PlaceName,
    PlaceNameResult,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_typed
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.i18n import french_spacing
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

# Said with lang="fr" only: the English answer needs no note.
_FR_NAMES_NOTE = french_spacing(
    "Les noms de lieux sont les toponymes officiels, tels qu'ils sont inscrits ; seules la "
    "catégorie et la province sont traduites."
)
_FR_UNMATCHED_NOTE = french_spacing(
    "Pour certains résultats « locate », le toponyme officiel n'a pas pu être retrouvé : le "
    "Géolocalisateur traduit parfois des mots à l'intérieur du nom (p. ex. « Rapid Ville » "
    "pour Rapid City)."
)


def _raise(exc_cls: type[ValueError], en: str, fr: str, lang: str) -> NoReturn:
    """English text unchanged; French goes through the typed-error template."""
    if lang == "fr":
        raise_typed(exc_cls, fr, "fr")
    raise exc_cls(en)


async def _get(url: str, params: dict[str, Any], ttl: int, lang: str = "en") -> tuple[Any, bool]:
    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 400:
                _raise(
                    InvalidInput,
                    f"nrcan_geo: {url} rejected the request ({status}).",
                    f"nrcan_geo : {url} a rejeté la requête ({status}).",
                    lang,
                )
            if status == 404:
                # Geonames answers a parameter it cannot parse with a Tomcat 404
                # page (radius=5.0 did, radius=5 did not, live 2026-10-03). The
                # parameters are checked here first, so a 404 is the service's.
                _raise(
                    UpstreamError,
                    f"nrcan_geo: {url} answered 404 for {sorted(params)}; the service "
                    "rejected a parameter this client sends.",
                    f"nrcan_geo : {url} a répondu 404 pour {sorted(params)} ; le service a "
                    "rejeté un paramètre envoyé par ce client.",
                    lang,
                )
            _raise(
                UpstreamError,
                f"nrcan_geo: {url} returned HTTP {status}.",
                f"nrcan_geo : {url} a renvoyé HTTP {status}.",
                lang,
            )
        except httpx.DecodingError:
            # DecodingError is an httpx.HTTPError, so without this branch a 200 HTML
            # page was reported as "did not respond in time" (confirmed by
            # test_html_or_non_list_body_is_upstream_error, 2026-10-03).
            _raise(
                UpstreamError,
                f"nrcan_geo: {url} did not return JSON.",
                f"nrcan_geo : {url} n'a pas renvoyé de JSON.",
                lang,
            )
        except httpx.HTTPError:
            _raise(
                UpstreamUnavailable,
                f"nrcan_geo: {url} did not respond in time.",
                f"nrcan_geo : {url} n'a pas répondu à temps.",
                lang,
            )

    return await cached_fetch(f"nrcan-geo:{url}:{sorted(params.items())}", ttl, fetch)


def _check_limit(limit: int, lang: str = "en") -> None:
    if limit < 1 or limit > constants.LIMIT_MAX:
        _raise(
            InvalidInput,
            f"limit must be between 1 and {constants.LIMIT_MAX}, got {limit}.",
            f"limit doit être compris entre 1 et {constants.LIMIT_MAX}, reçu {limit}.",
            lang,
        )


def _has_coordinates(item: dict[str, Any]) -> bool:
    return item.get("lat") is not None and item.get("lng") is not None


def _official_name(en_item: dict[str, Any], fr_item: dict[str, Any]) -> str:
    """The English answer's name, with only its category and province in French.

    With lang=fr the Geolocator's "locate" index translates generic words
    inside proper names word by word ("Rapid City" -> "Rapid Ville",
    "Williams Lake" -> "Williams Lac", "Thunder Bay" -> "Thunder Baie",
    live 2026-10-04), while its "geonames" index keeps the official
    toponym. The lang=en name keeps the toponym; its trailing "(Lake)"
    and province are the only parts that are labels, not names.
    """
    name = str(en_item.get("name") or "")
    en_cat, fr_cat = en_item.get("category"), fr_item.get("category")
    if en_cat and fr_cat and name.endswith(f"({en_cat})"):
        name = f"{name[: -len(en_cat) - 2]}({fr_cat})"
    en_prov, fr_prov = en_item.get("province"), fr_item.get("province")
    if en_prov and fr_prov:
        head, found, tail = name.rpartition(f", {en_prov}")
        if found:
            name = f"{head}, {fr_prov}{tail}"
    return name


def _restore_toponyms(fr_raw: list[Any], en_raw: list[Any]) -> tuple[list[Any], int]:
    """Swap each French "locate" name for its official form; count those left as is.

    The two answers usually list the same items in the same order, but
    not always (Red Deer gave 24 English and 57 French items one minute,
    57 and 57 the next, live 2026-10-04), so an item is paired by
    position only when key and coordinates agree, and otherwise by a
    key-and-coordinates match that is unique in the English answer.
    """
    point = lambda i: (i.get("key"), i.get("lat"), i.get("lng"))
    counts: dict[Any, int] = {}
    for item in en_raw:
        counts[point(item)] = counts.get(point(item), 0) + 1
    unique = {point(i): i for i in en_raw if counts[point(i)] == 1}
    restored: list[Any] = []
    unmatched = 0
    for index, item in enumerate(fr_raw):
        if item.get("key") != "locate" or not _has_coordinates(item):
            restored.append(item)
            continue
        twin = en_raw[index] if index < len(en_raw) else None
        if twin is None or point(twin) != point(item):
            twin = unique.get(point(item))
        if twin is None:
            unmatched += 1
            restored.append(item)
            continue
        restored.append({**item, "name": _official_name(twin, item)})
    return restored, unmatched


async def locate(
    query: str, *, limit: int = constants.LIMIT_DEFAULT, lang: str = "en"
) -> LocationResult:
    if not query.strip():
        _raise(InvalidInput, "query must not be empty.", "query ne doit pas être vide.", lang)
    _check_limit(limit, lang)
    raw, cached = await _get(
        constants.GEOLOCATOR_URL,
        {"q": query.strip(), "lang": lang},
        constants.CACHE_TTL_LOOKUP_SECONDS,
        lang,
    )
    if not isinstance(raw, list):
        _raise(
            UpstreamError,
            "nrcan_geo: the Geolocator did not return a list.",
            "nrcan_geo : le Géolocalisateur n'a pas renvoyé de liste.",
            lang,
        )
    kept = [item for item in raw if _has_coordinates(item)][:limit]
    limits = None
    if lang == "fr":
        limits = _FR_NAMES_NOTE
        if any(item.get("key") == "locate" for item in kept):
            # A second, English request recovers the official toponyms; when it
            # fails the French answer still stands, with a note saying so.
            try:
                en_raw, _ = await _get(
                    constants.GEOLOCATOR_URL,
                    {"q": query.strip(), "lang": "en"},
                    constants.CACHE_TTL_LOOKUP_SECONDS,
                    lang,
                )
            except (InvalidInput, UpstreamError, UpstreamUnavailable):
                en_raw = None
            if isinstance(en_raw, list):
                kept, unmatched = _restore_toponyms(kept, en_raw)
            else:
                unmatched = 1
            if unmatched:
                limits = f"{_FR_NAMES_NOTE} {_FR_UNMATCHED_NOTE}"
    locations = [
        Location(
            name=item.get("name") or "",
            province=item.get("province"),
            category=item.get("category"),
            latitude=item["lat"],
            longitude=item["lng"],
            bbox=item.get("bbox"),
            source=item.get("key"),
        )
        for item in kept
    ]
    return LocationResult(
        query=query,
        locations=locations,
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=constants.GEOLOCATOR_URL,
            cached=cached,
            schema_name="nrcan_geo.LocationResult",
            limits=limits,
            lang=lang,
        ),
    )


async def _concise_terms(lang: str) -> dict[str, str]:
    url = constants.GEONAMES_ROOT.format(lang=lang) + "codes/concise.json"
    raw, _ = await _get(url, {}, constants.CACHE_TTL_CODES_SECONDS, lang)
    return {d["code"]: d.get("term") or d["code"] for d in raw.get("definitions") or []}


def _province_code(value: str, lang: str = "en") -> str:
    value = value.strip().upper()
    if value.isdigit():
        return value
    code = constants.PROVINCE_CODES.get(value)
    if code is None:
        _raise(
            InvalidInput,
            f"province must be an abbreviation like 'AB' or an SGC code like '48', got {value!r}.",
            f"province doit être une abréviation comme 'AB' ou un code de la CGT comme '48', "
            f"reçu {value!r}.",
            lang,
        )
    return code


async def search_names(
    query: str | None = None,
    *,
    province: str | None = None,
    feature_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    bbox: list[float] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: str = "en",
) -> PlaceNameResult:
    _check_limit(limit, lang)
    params: dict[str, Any] = {"num": limit}
    if query and query.strip():
        params["q"] = query.strip()
    if province:
        params["province"] = _province_code(province, lang)
    if feature_type:
        params["concise"] = feature_type.strip().upper()
    if (latitude is None) != (longitude is None):
        _raise(
            InvalidInput,
            "latitude and longitude must be given together.",
            "latitude et longitude doivent être données ensemble.",
            lang,
        )
    if latitude is not None and longitude is not None:
        radius = radius_km or 10
        if not 0 < radius <= constants.RADIUS_MAX_KM:
            _raise(
                InvalidInput,
                f"radius_km must be between 0 and {constants.RADIUS_MAX_KM}.",
                f"radius_km doit être compris entre 0 et {constants.RADIUS_MAX_KM}.",
                lang,
            )
        # Geonames takes whole kilometres only: radius=5.0 is a 404, radius=5
        # works (confirmed live 2026-10-03), and a float arrives from JSON.
        params.update(lat=latitude, lon=longitude, radius=max(1, round(radius)))
    if bbox is not None:
        if len(bbox) != 4:
            _raise(
                InvalidInput,
                "bbox must be [west, south, east, north].",
                "bbox doit être [ouest, sud, est, nord].",
                lang,
            )
        params["bbox"] = ",".join(str(v) for v in bbox)
    if len(params) == 1:
        _raise(
            InvalidInput,
            "Give a query, a province or feature type, a point, or a bbox.",
            "donnez une requête, une province ou un type d'entité, un point ou une bbox.",
            lang,
        )

    url = constants.GEONAMES_ROOT.format(lang=lang) + "geonames.json"
    raw, cached = await _get(url, params, constants.CACHE_TTL_LOOKUP_SECONDS, lang)
    terms = await _concise_terms(lang)
    names = [
        PlaceName(
            id=item["id"],
            name=item.get("name") or "",
            feature_type=terms.get((item.get("concise") or {}).get("code") or ""),
            status=(item.get("status") or {}).get("code"),
            province=(item.get("province") or {}).get("code"),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            location=item.get("location") or None,
            map_sheets=list(item.get("map") or []),
            decision_date=item.get("decision"),
        )
        for item in raw.get("items") or []
    ]
    return PlaceNameResult(
        names=names,
        returned_count=len(names),
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=cached,
            schema_name="nrcan_geo.PlaceNameResult",
            limits=_FR_NAMES_NOTE if lang == "fr" else None,
            lang=lang,
        ),
    )

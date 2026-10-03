"""Client for Open North's Represent API (represent.opennorth.ca).

Quirks confirmed live 2026-10-02 are listed in constants.py. Two matter most
for callers: a boundary set's licence and last-updated date exist only on its
detail endpoint, so lookups fetch the (cached) detail of each distinct set they
return; and representative sets carry no date at all, so staleness can only be
reported for boundaries.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx

from maplestats_mcp.modules.represent import constants
from maplestats_mcp.modules.represent.schemas import (
    BoundaryRef,
    BoundarySetInfo,
    BoundarySetList,
    Level,
    Office,
    PointLookup,
    PostcodeLookup,
    Representative,
    RepresentativeSearchResult,
    RepresentativeSetInfo,
    RepresentativeSetList,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import api_get
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.rate_limiter import get_limiter

Lang = Literal["en", "fr"]

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)
_POSTCODE = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_LIMITS = {
    "en": (
        "Open North allows 60 requests per minute (86,400 a day) and this server paces "
        "itself to 1 a second. Licences differ by boundary set (see licence_url; federal "
        "districts use the Open Government Licence - Canada). Representative records are "
        "scraped from official sites and their licence is unverified. Representative sets "
        "carry no update date and some are stale: confirm on the official page (source_url)."
    ),
    "fr": (
        "Open North permet 60 requêtes par minute (86 400 par jour) et ce serveur se limite à "
        "1 par seconde. Les licences varient selon l'ensemble de limites (voir licence_url; les "
        "circonscriptions fédérales relèvent de la Licence du gouvernement ouvert - Canada). Les "
        "fiches d'élus sont extraites de sites officiels et leur licence n'est pas vérifiée. Les "
        "ensembles d'élus n'ont pas de date de mise à jour et certains sont périmés : vérifier "
        "sur la page officielle (source_url)."
    ),
}
_POSTCODE_NOTE = {
    "en": (
        "A postal code is a mail-sorting unit, not an electoral district: it can match several "
        "boundaries, and the centroid match uses only its centre point. Use a latitude and "
        "longitude (represent_lookup_point) when exact accuracy matters."
    ),
    "fr": (
        "Un code postal sert au tri du courrier et non à délimiter une circonscription : il peut "
        "chevaucher plusieurs limites, et l'appariement par centroïde n'utilise que son point "
        "central. Utiliser une latitude et une longitude (represent_lookup_point) pour une "
        "exactitude totale."
    ),
}
_OLD_ORDER_NOTE = {
    "en": (
        "Older federal representation orders (2003, 2013) and other superseded sets can appear "
        "among the boundaries; the representatives point to the current ones."
    ),
    "fr": (
        "Des ordonnances de représentation fédérales plus anciennes (2003, 2013) et d'autres "
        "ensembles remplacés peuvent figurer parmi les limites; les élus renvoient aux "
        "limites actuelles."
    ),
}
_STALE_NOTE = {
    "en": "These boundary sets were last updated more than 5 years ago: {names}.",
    "fr": "Ces ensembles de limites ont été mis à jour il y a plus de 5 ans : {names}.",
}
_MISSING_LEVEL_NOTE = {
    "en": (
        "No {levels} representative matched this postal code (live example: H3B4W8 returns no "
        "MP). The code may straddle districts or the level may not be covered; try "
        "represent_lookup_point or the sets filter."
    ),
    "fr": (
        "Aucun élu de palier {levels} ne correspond à ce code postal (exemple réel : H3B4W8 ne "
        "renvoie aucun député fédéral). Le code peut chevaucher des circonscriptions ou le palier "
        "n'est pas couvert; essayer represent_lookup_point ou le filtre sets."
    ),
}
_LEVEL_FR = {"federal": "fédéral", "provincial": "provincial", "municipal": "municipal"}
_NO_MATCH_NOTE = {
    "en": "No boundary matched this point; Represent covers Canadian places only.",
    "fr": "Aucune limite ne correspond à ce point; Represent ne couvre que des lieux canadiens.",
}


def _check_lang(lang: str) -> None:
    if lang not in ("en", "fr"):
        raise InvalidInput("represent: lang must be 'en' or 'fr'.")


def _text(value: object) -> str | None:
    """A string field, with the API's empty string read as absent."""
    return value if isinstance(value, str) and value.strip() else None


def _slug_from(path: str | None, marker: str) -> str | None:
    """The slug after `/<marker>/` in a Represent path such as '/boundary-sets/x/'."""
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def level_of(set_slug: str | None) -> Level | None:
    if not set_slug:
        return None
    if set_slug == constants.FEDERAL_SET:
        return "federal"
    if set_slug.endswith(constants.PROVINCIAL_SUFFIX) or set_slug in constants.PROVINCIAL_EXTRA:
        return "provincial"
    return "municipal"


async def _get(path: str, params: dict[str, Any] | None = None, ttl: int = 0) -> tuple[Any, bool]:
    url = f"{constants.BASE_URL}{path}"

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, headers=constants.HEADERS, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise NotFound(f"represent: nothing at {path}.") from exc
            if status == 400:
                raise InvalidInput(
                    f"represent: the API rejected the request ({exc.response.text.strip()[:120]})."
                ) from exc
            if status in (429, 503):
                raise UpstreamUnavailable(
                    f"represent: HTTP {status}; the API allows {constants.RATE_LIMIT_PER_MINUTE} "
                    "requests per minute, try again shortly."
                ) from exc
            raise UpstreamError(f"represent: {url} returned HTTP {status}.") from exc
        except httpx.DecodingError as exc:
            raise UpstreamError(f"represent: {url} did not return JSON.") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"represent: {url} could not be reached.") from exc

    key = f"represent:{path}:{sorted((params or {}).items())}"
    return await cached_fetch(key, ttl or constants.CACHE_TTL_SECONDS, fetch)


def _provenance(
    path: str,
    cached: bool,
    schema_name: str,
    lang: Lang,
    coverage: str | None = None,
    params: dict[str, Any] | None = None,
    request: str | None = None,
) -> Provenance:
    """`url` is the main request with its query string; `request` names any other."""
    return make_provenance(
        source="represent",
        url=str(httpx.URL(f"{constants.BASE_URL}{path}", params=params or None)),
        cached=cached,
        schema_name=schema_name,
        freshness=(
            "representatives are re-scraped by Open North on its own schedule; boundary sets "
            "are updated a few times a year; results cached 1 hour (sets 24 hours)"
            if lang == "en"
            else "les élus sont ré-extraits par Open North selon son propre calendrier; les "
            "limites sont mises à jour quelques fois par an; résultats en cache 1 h (ensembles 24 h)"
        ),
        coverage=coverage,
        limits=join_limits(request, _LIMITS[lang]),
    )


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _office(raw: dict[str, Any]) -> Office:
    return Office(
        type=_text(raw.get("type")),
        postal=_text(raw.get("postal")),
        tel=_text(raw.get("tel")),
        fax=_text(raw.get("fax")),
    )


def _representative(raw: dict[str, Any]) -> Representative:
    related = raw.get("related") or {}
    set_slug = _slug_from(related.get("representative_set_url"), "representative-sets")
    extra = raw.get("extra")
    return Representative(
        name=str(raw.get("name") or ""),
        first_name=_text(raw.get("first_name")),
        last_name=_text(raw.get("last_name")),
        elected_office=_text(raw.get("elected_office")),
        district_name=_text(raw.get("district_name")),
        party_name=_text(raw.get("party_name")),
        level=level_of(set_slug),
        representative_set=set_slug,
        representative_set_name=_text(raw.get("representative_set_name")),
        boundary=_text(related.get("boundary_url")),
        email=_text(raw.get("email")),
        url=_text(raw.get("url")),
        personal_url=_text(raw.get("personal_url")),
        photo_url=_text(raw.get("photo_url")),
        source_url=_text(raw.get("source_url")),
        gender=_text(raw.get("gender")),
        offices=[_office(o) for o in list_or_empty(raw, "offices") if isinstance(o, dict)],
        extra=extra if isinstance(extra, dict) else {},
    )


def _boundary_ref(
    raw: dict[str, Any], matched_by: Literal["centroid", "concordance", "point"]
) -> BoundaryRef:
    path = str(raw.get("url") or "")
    related = raw.get("related") or {}
    set_slug = _slug_from(related.get("boundary_set_url"), "boundary-sets") or _slug_from(
        path, "boundaries"
    )
    external = raw.get("external_id")
    return BoundaryRef(
        name=str(raw.get("name") or ""),
        boundary_set=set_slug or "",
        boundary_set_name=_text(raw.get("boundary_set_name")),
        external_id=str(external) if external not in (None, "") else None,
        path=path,
        matched_by=matched_by,
    )


def _age(updated: date | None) -> tuple[float | None, bool | None]:
    if updated is None:
        return None, None
    years = round((datetime.now(UTC).date() - updated).days / 365.25, 1)
    return years, years > constants.STALE_YEARS


def _set_info(slug: str, raw: dict[str, Any]) -> BoundarySetInfo:
    updated = _parse_date(raw.get("last_updated"))
    age, stale = _age(updated)
    return BoundarySetInfo(
        slug=slug,
        name=_text(raw.get("name_plural")) or _text(raw.get("name")),
        domain=_text(raw.get("domain")),
        authority=_text(raw.get("authority")),
        licence_url=_text(raw.get("licence_url")),
        source_url=_text(raw.get("source_url")),
        last_updated=updated,
        age_years=age,
        possibly_stale=stale,
        start_date=_parse_date(raw.get("start_date")),
        end_date=_parse_date(raw.get("end_date")),
        notes=_text(raw.get("notes")),
        detail_loaded="licence_url" in raw or "last_updated" in raw,
    )


def _check_slug(value: str, what: str) -> str:
    slug = value.strip().strip("/").lower()
    if not _SLUG.match(slug):
        raise InvalidInput(
            f"represent: {what} must be a slug such as 'federal-electoral-districts'."
        )
    return slug


async def _set_details(
    refs: list[BoundaryRef],
) -> tuple[list[BoundarySetInfo], bool]:
    """Licence and last-updated for each distinct boundary set among `refs`."""
    names: dict[str, str | None] = {}
    for ref in refs:
        if ref.boundary_set and ref.boundary_set not in names:
            names[ref.boundary_set] = ref.boundary_set_name
    slugs = list(names)[: constants.MAX_SET_DETAILS]
    infos: list[BoundarySetInfo] = []
    all_cached = True
    for slug in slugs:
        try:
            raw, cached = await _get(f"/boundary-sets/{slug}/", ttl=constants.SETS_TTL_SECONDS)
        except NotFound:
            infos.append(BoundarySetInfo(slug=slug, name=names[slug], detail_loaded=False))
            continue
        all_cached = all_cached and cached
        infos.append(_set_info(slug, raw))
    return infos, all_cached


def _oldest(infos: list[BoundarySetInfo]) -> date | None:
    dates = [i.last_updated for i in infos if i.last_updated]
    return min(dates) if dates else None


def _stale_note(infos: list[BoundarySetInfo], lang: Lang) -> list[str]:
    stale = [f"{i.name or i.slug} ({i.last_updated})" for i in infos if i.possibly_stale]
    return [_STALE_NOTE[lang].format(names="; ".join(stale))] if stale else []


async def lookup_postcode(
    postcode: str,
    sets: str | None = None,
    include_set_details: bool = True,
    lang: Lang = "en",
) -> PostcodeLookup:
    _check_lang(lang)
    code = re.sub(r"\s+", "", postcode or "").upper()
    if not _POSTCODE.match(code):
        raise InvalidInput("represent: postcode must look like T5J0N3 (letter, digit, ...).")
    params: dict[str, Any] = {}
    if sets:
        slugs = [_check_slug(s, "sets") for s in sets.split(",") if s.strip()]
        params["sets"] = ",".join(slugs)
    path = f"/postcodes/{code}/"
    try:
        raw, cached = await _get(path, params or None)
    except NotFound as exc:
        raise NotFound(
            f"represent: postal code {code} is not in Open North's postal code data."
        ) from exc
    # representatives_concordance is absent (not null) on many postal codes
    # and both representative keys are dropped when `sets` is given, so every
    # list goes through list_or_empty.
    boundaries = [
        _boundary_ref(b, "centroid")
        for b in list_or_empty(raw, "boundaries_centroid")
        if isinstance(b, dict)
    ] + [
        _boundary_ref(b, "concordance")
        for b in list_or_empty(raw, "boundaries_concordance")
        if isinstance(b, dict)
    ]
    representatives: list[Representative] = []
    seen: set[tuple[str, str, str]] = set()
    for key in ("representatives_centroid", "representatives_concordance"):
        for r in list_or_empty(raw, key):
            if not isinstance(r, dict):
                continue
            rep = _representative(r)
            ident = (rep.name, rep.representative_set or "", rep.district_name or "")
            if ident not in seen:
                seen.add(ident)
                representatives.append(rep)
    infos: list[BoundarySetInfo] = []
    details_cached = True
    if include_set_details:
        infos, details_cached = await _set_details(boundaries)
    centroid = raw.get("centroid") or {}
    coords = centroid.get("coordinates") if isinstance(centroid, dict) else None
    lon, lat = (
        (coords[0], coords[1]) if isinstance(coords, list) and len(coords) >= 2 else (None, None)
    )
    notes = [_POSTCODE_NOTE[lang], _OLD_ORDER_NOTE[lang], *_stale_note(infos, lang)]
    if not sets:
        present = {r.level for r in representatives}
        missing = [lv for lv in ("federal", "provincial") if lv not in present]
        if missing:
            names = ", ".join(_LEVEL_FR[lv] if lang == "fr" else lv for lv in missing)
            notes.append(_MISSING_LEVEL_NOTE[lang].format(levels=names))
    return PostcodeLookup(
        postcode=code,
        city=_text(raw.get("city")),
        province=_text(raw.get("province")),
        centroid_latitude=lat,
        centroid_longitude=lon,
        boundaries=boundaries,
        representatives=representatives,
        boundary_sets=infos,
        oldest_boundary_update=_oldest(infos),
        notes=notes,
        provenance=_provenance(
            path,
            cached and details_cached,
            "represent.PostcodeLookup",
            lang,
            params=params,
            coverage=(
                "boundary licences and dates not loaded (include_set_details=false)"
                if not include_set_details
                else None
            ),
        ),
    )


def _check_point(latitude: float, longitude: float) -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise InvalidInput("represent: latitude and longitude must be finite numbers.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidInput(
            "represent: latitude must be within -90..90 and longitude within -180..180 "
            "(latitude first, e.g. 53.5412, -113.4903)."
        )


async def lookup_point(
    latitude: float,
    longitude: float,
    include_set_details: bool = True,
    lang: Lang = "en",
) -> PointLookup:
    _check_lang(lang)
    _check_point(latitude, longitude)
    point = f"{latitude},{longitude}"
    boundaries_raw, cached_b = await _get(
        "/boundaries/", {"contains": point, "limit": constants.LIMIT_MAX}
    )
    reps_raw, cached_r = await _get(
        "/representatives/", {"point": point, "limit": constants.LIMIT_MAX}
    )
    boundaries = [
        _boundary_ref(b, "point")
        for b in list_or_empty(boundaries_raw, "objects")
        if isinstance(b, dict)
    ]
    representatives = [
        _representative(r) for r in list_or_empty(reps_raw, "objects") if isinstance(r, dict)
    ]
    infos: list[BoundarySetInfo] = []
    details_cached = True
    if include_set_details:
        infos, details_cached = await _set_details(boundaries)
    notes = [_OLD_ORDER_NOTE[lang], *_stale_note(infos, lang)]
    if not boundaries:
        notes.insert(0, _NO_MATCH_NOTE[lang])
    return PointLookup(
        latitude=latitude,
        longitude=longitude,
        boundaries=boundaries,
        representatives=representatives,
        boundaries_total=int((boundaries_raw.get("meta") or {}).get("total_count") or 0),
        representatives_total=int((reps_raw.get("meta") or {}).get("total_count") or 0),
        boundary_sets=infos,
        oldest_boundary_update=_oldest(infos),
        notes=notes,
        provenance=_provenance(
            "/representatives/",
            cached_b and cached_r and details_cached,
            "represent.PointLookup",
            lang,
            params={"point": point, "limit": constants.LIMIT_MAX},
            request=(
                "Request: also GET "
                + str(
                    httpx.URL(
                        f"{constants.BASE_URL}/boundaries/",
                        params={"contains": point, "limit": constants.LIMIT_MAX},
                    )
                )
                + " for the boundaries"
            ),
        ),
    )


async def _representative_sets() -> tuple[list[RepresentativeSetInfo], bool]:
    raw, cached = await _get(
        "/representative-sets/", {"limit": constants.PAGE_SIZE}, constants.SETS_TTL_SECONDS
    )
    sets: list[RepresentativeSetInfo] = []
    for item in list_or_empty(raw, "objects"):
        if not isinstance(item, dict):
            continue
        slug = _slug_from(item.get("url"), "representative-sets")
        if not slug:
            continue
        related = item.get("related") or {}
        sets.append(
            RepresentativeSetInfo(
                slug=slug,
                name=str(item.get("name") or slug),
                level=level_of(slug) or "municipal",
                boundary_set=_slug_from(related.get("boundary_set_url"), "boundary-sets"),
                data_url=_text(item.get("data_url")),
            )
        )
    return sets, cached


async def list_representative_sets(
    level: Level | None = None, lang: Lang = "en"
) -> RepresentativeSetList:
    _check_lang(lang)
    sets, cached = await _representative_sets()
    if level:
        sets = [s for s in sets if s.level == level]
    return RepresentativeSetList(
        sets=sorted(sets, key=lambda s: (s.level, s.name)),
        total_count=len(sets),
        notes=[
            (
                "Level is derived from the set slug (house-of-commons is federal; "
                "*-legislature and quebec-assemblee-nationale are provincial; the rest municipal)."
            )
        ],
        provenance=_provenance(
            "/representative-sets/",
            cached,
            "represent.RepresentativeSetList",
            lang,
            params={"limit": constants.PAGE_SIZE},
        ),
    )


async def _search_in_set(slug: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Every matching representative of one set (provincial sets hold up to ~125)."""
    raw, cached = await _get(f"/representatives/{slug}/", {**params, "limit": constants.PAGE_SIZE})
    return [r for r in list_or_empty(raw, "objects") if isinstance(r, dict)], cached


async def search_representatives(
    name: str | None = None,
    office: str | None = None,
    district: str | None = None,
    party: str | None = None,
    level: Level | None = None,
    representative_set: str | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> RepresentativeSearchResult:
    _check_lang(lang)
    if not 1 <= limit <= constants.LIMIT_MAX:
        raise InvalidInput(f"represent: limit must be between 1 and {constants.LIMIT_MAX}.")
    if offset < 0:
        raise InvalidInput("represent: offset must be 0 or more.")
    if level not in (None, "federal", "provincial", "municipal"):
        raise InvalidInput("represent: level must be federal, provincial or municipal.")
    filters = {
        "name__icontains": name,
        "elected_office__icontains": office,
        "district_name__icontains": district,
        "party_name__icontains": party,
    }
    params = {k: v.strip() for k, v in filters.items() if v and v.strip()}
    set_slug = _check_slug(representative_set, "representative_set") if representative_set else None
    if not params and not level and not set_slug:
        raise InvalidInput(
            "represent: give at least one of name, office, district, party, level or "
            "representative_set."
        )
    notes: list[str] = []
    cached = True
    rows: list[dict[str, Any]]
    total: int
    path = "/representatives/"
    sent: dict[str, Any] = {**params, "limit": limit, "offset": offset}
    request: str | None = None
    if set_slug:
        path = f"/representatives/{set_slug}/"
        sent = {**params, "limit": constants.PAGE_SIZE}
        if level and level_of(set_slug) != level:
            raise InvalidInput(f"represent: set {set_slug} is {level_of(set_slug)}, not {level}.")
        # An unknown set slug answers 200 with an empty list, so check it exists.
        await _get(f"/representative-sets/{set_slug}/", ttl=constants.SETS_TTL_SECONDS)
        rows, cached = await _search_in_set(set_slug, params)
        total = len(rows)
        rows = rows[offset : offset + limit]
    elif level in ("federal", "provincial"):
        if level == "federal":
            slugs = [constants.FEDERAL_SET]
        else:
            all_sets, cached = await _representative_sets()
            slugs = [s.slug for s in all_sets if s.level == "provincial"]
        merged: list[dict[str, Any]] = []
        for slug in slugs:
            part, part_cached = await _search_in_set(slug, params)
            cached = cached and part_cached
            merged.extend(part)
        total = len(merged)
        rows = merged[offset : offset + limit]
        path = f"/representatives/{slugs[0]}/"
        sent = {**params, "limit": constants.PAGE_SIZE}
        request = (
            f"Request: one GET /representatives/<set>/ per {level} set ({len(slugs)} sets) "
            "with the filters shown in url, merged and paged here"
        )
    elif level == "municipal":
        # Represent has no level filter, so scan the (filtered) list and drop
        # federal and provincial rows here.
        merged = []
        page_offset = 0
        for _ in range(constants.MAX_SCAN_PAGES):
            raw, page_cached = await _get(
                "/representatives/", {**params, "limit": constants.PAGE_SIZE, "offset": page_offset}
            )
            cached = cached and page_cached
            objects = [r for r in list_or_empty(raw, "objects") if isinstance(r, dict)]
            merged.extend(
                r
                for r in objects
                if level_of(
                    _slug_from(
                        (r.get("related") or {}).get("representative_set_url"),
                        "representative-sets",
                    )
                )
                == "municipal"
            )
            if not (raw.get("meta") or {}).get("next") or not objects:
                break
            page_offset += len(objects)
        total = len(merged)
        rows = merged[offset : offset + limit]
        sent = {**params, "limit": constants.PAGE_SIZE, "offset": 0}
        request = (
            "Request: GET /representatives/ pages from offset 0 with the filters shown in "
            "url; federal and provincial rows are dropped here, then paged"
        )
    else:
        raw, cached = await _get("/representatives/", {**params, "limit": limit, "offset": offset})
        rows = [r for r in list_or_empty(raw, "objects") if isinstance(r, dict)]
        total = int((raw.get("meta") or {}).get("total_count") or 0)
    if total == 0:
        notes.append("No representative matched. Matching is a case-insensitive substring.")
    return RepresentativeSearchResult(
        representatives=[_representative(r) for r in rows],
        total_count=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(rows) < total,
        notes=notes,
        provenance=_provenance(
            path,
            cached,
            "represent.RepresentativeSearchResult",
            lang,
            params=sent,
            request=request,
            coverage=(
                "representative records are a scrape of official sites and some sets are stale"
            ),
        ),
    )


async def list_boundary_sets(
    domain: str | None = None,
    name: str | None = None,
    with_details: bool = True,
    limit: int = constants.LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> BoundarySetList:
    _check_lang(lang)
    if not 1 <= limit <= constants.MAX_SET_DETAILS * 2:
        raise InvalidInput(
            f"represent: limit must be between 1 and {constants.MAX_SET_DETAILS * 2}."
        )
    if offset < 0:
        raise InvalidInput("represent: offset must be 0 or more.")
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if domain and domain.strip():
        params["domain__icontains"] = domain.strip()
    if name and name.strip():
        params["name__icontains"] = name.strip()
    raw, cached = await _get("/boundary-sets/", params, constants.SETS_TTL_SECONDS)
    objects = [o for o in list_or_empty(raw, "objects") if isinstance(o, dict)]
    meta = raw.get("meta") or {}
    sets: list[BoundarySetInfo] = []
    for obj in objects:
        slug = _slug_from(obj.get("url"), "boundary-sets")
        if not slug:
            continue
        if with_details and len(sets) < constants.MAX_SET_DETAILS:
            detail, detail_cached = await _get(
                f"/boundary-sets/{slug}/", ttl=constants.SETS_TTL_SECONDS
            )
            cached = cached and detail_cached
            info = _set_info(slug, {**obj, **detail})
            # The detail names the set in the plural; keep the list name too.
            sets.append(info.model_copy(update={"name": _text(obj.get("name")) or info.name}))
        else:
            info = _set_info(slug, obj)
            sets.append(info.model_copy(update={"detail_loaded": False}))
    total = int(meta.get("total_count") or len(sets))
    notes = []
    if not with_details:
        notes.append(
            "Licence and last-updated date are not loaded; call with with_details=true "
            "(at most 25 sets per call)."
        )
    elif any(not s.detail_loaded for s in sets):
        notes.append("Details were loaded for the first 25 sets only; page on with offset.")
    return BoundarySetList(
        sets=sets,
        total_count=total,
        offset=offset,
        limit=limit,
        has_more=bool(meta.get("next")),
        oldest_last_updated=_oldest(sets),
        notes=notes,
        provenance=_provenance(
            "/boundary-sets/", cached, "represent.BoundarySetList", lang, params=params
        ),
    )

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
import unicodedata
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
from maplestats_mcp.shared.fr_typography import fr_or_en, french_spacing, lang_error
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
        "1 par seconde. Les licences varient selon l'ensemble de limites (voir licence_url ; les "
        "circonscriptions fédérales relèvent de la Licence du gouvernement ouvert – Canada). Les "
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
        "among the boundaries; the representatives point to the current ones. The slug "
        "federal-electoral-districts (no year) is the 2013 order; the current federal map is "
        f"{constants.CURRENT_FEDERAL_BOUNDARY_SET}."
    ),
    "fr": (
        "Des ordonnances de représentation fédérales plus anciennes (2003, 2013) et d'autres "
        "ensembles remplacés peuvent figurer parmi les limites ; les élus renvoient aux "
        "limites actuelles. L'ensemble federal-electoral-districts (sans année) est "
        "l'ordonnance de 2013 ; la carte fédérale actuelle est "
        f"{constants.CURRENT_FEDERAL_BOUNDARY_SET}."
    ),
}
_STALE_NOTE = {
    "en": "These boundary sets were last updated more than 5 years ago: {names}.",
    "fr": "Ces ensembles de limites ont été mis à jour il y a plus de 5 ans : {names}.",
}
_SUPERSEDED_NOTE = {
    "en": (
        "Superseded representation orders, not the current map (their old last-updated date "
        "reflects that, not a stale copy of current districts): {names}. Current federal "
        f"ridings are in {constants.CURRENT_FEDERAL_BOUNDARY_SET}."
    ),
    "fr": (
        "Ordonnances de représentation remplacées, et non la carte actuelle (leur date de mise "
        "à jour ancienne vient de là, et non d'une copie périmée des limites actuelles) : "
        "{names}. Les circonscriptions fédérales actuelles sont dans "
        f"{constants.CURRENT_FEDERAL_BOUNDARY_SET}."
    ),
}
_SETS_NO_REPS_NOTE = {
    "en": (
        "No representative came back for these sets. With sets, Represent returns only the "
        "representatives of boundary sets that a representative set uses (e.g. "
        f"{constants.CURRENT_FEDERAL_BOUNDARY_SET} for MPs); superseded orders such as "
        "federal-electoral-districts (2013) and census sets have none. Drop sets to get every "
        "representative."
    ),
    "fr": (
        "Aucun élu n'est renvoyé pour ces ensembles. Avec sets, Represent ne renvoie que les "
        "élus des ensembles de limites utilisés par un ensemble d'élus (p. ex. "
        f"{constants.CURRENT_FEDERAL_BOUNDARY_SET} pour les députés fédéraux) ; les ordonnances "
        "remplacées comme federal-electoral-districts (2013) et les ensembles de recensement "
        "n'en ont aucun. Retirer sets pour obtenir tous les élus."
    ),
}
_SEARCH_NO_MATCH_NOTE = {
    "en": "No representative matched. Matching is a case-insensitive substring.",
    "fr": (
        "Aucun élu ne correspond. La recherche porte sur une sous-chaîne, sans égard à la casse."
    ),
}
_PARTY_ALIAS_NOTE = {
    "en": "party '{party}' was matched as any of: {needles}.",
    "fr": "Le parti « {party} » a été cherché sous l'une de ces formes : {needles}.",
}
_PARTY_CAUCUS_NOTE = {
    "en": (
        "Party names come from each legislature's site: Saskatchewan lists caucuses (Government "
        "Caucus, Opposition Caucus) and the Northwest Territories has no parties, so party "
        "filters miss their members."
    ),
    "fr": (
        "Les noms de parti viennent du site de chaque assemblée : la Saskatchewan indique des "
        "caucus (Government Caucus, Opposition Caucus) et les Territoires du Nord-Ouest n'ont pas "
        "de partis ; le filtre de parti ne trouve donc pas leurs élus."
    ),
}
_LEVEL_NOTE = {
    "en": (
        "Level is derived from the set slug (house-of-commons is federal; "
        "*-legislature and quebec-assemblee-nationale are provincial; the rest municipal)."
    ),
    "fr": (
        "Le palier est déduit de l'identifiant de l'ensemble (house-of-commons est fédéral ; "
        "*-legislature et quebec-assemblee-nationale sont provinciaux ; les autres municipaux)."
    ),
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
        "n'est pas couvert ; essayer represent_lookup_point ou le filtre sets."
    ),
}
_LEVEL_FR = {"federal": "fédéral", "provincial": "provincial", "municipal": "municipal"}
_NO_MATCH_NOTE = {
    "en": "No boundary matched this point; Represent covers Canadian places only.",
    "fr": "Aucune limite ne correspond à ce point ; Represent ne couvre que des lieux canadiens.",
}


def _bad_offset(lang: str) -> InvalidInput:
    return lang_error(
        InvalidInput,
        lang,
        "represent: offset must be 0 or more.",
        "represent : offset doit être 0 ou plus.",
    )


def _check_lang(lang: str) -> None:
    if lang not in ("en", "fr"):
        raise InvalidInput("represent: lang must be 'en' or 'fr'.")


def _text(value: object) -> str | None:
    """A string field, with the API's empty string read as absent."""
    return value if isinstance(value, str) and value.strip() else None


def _fold(value: str) -> str:
    """Lower case without accents or dots, so 'N.P.D.' and 'Québec' compare loosely."""
    decomposed = unicodedata.normalize("NFKD", value)
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(bare.replace(".", "").casefold().split())


def _party_needles(party: str) -> tuple[tuple[str, ...], bool]:
    """Substrings to match party_name against, and whether an alias was used."""
    aliases = constants.PARTY_ALIASES.get(_fold(party))
    if aliases:
        return aliases, True
    return (party.strip(),), False


def _party_matches(raw: dict[str, Any], needles: tuple[str, ...]) -> bool:
    party_name = _fold(str(raw.get("party_name") or ""))
    return any(_fold(n) in party_name for n in needles)


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


async def _get(
    path: str, params: dict[str, Any] | None = None, ttl: int = 0, lang: str = "en"
) -> tuple[Any, bool]:
    url = f"{constants.BASE_URL}{path}"

    async def fetch() -> Any:
        await _LIMITER.acquire()
        try:
            return await api_get(url, params=params, headers=constants.HEADERS, timeout=60.0)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                raise lang_error(
                    NotFound,
                    lang,
                    f"represent: nothing at {path}.",
                    f"represent : rien à {path}.",
                ) from exc
            if status == 400:
                body = exc.response.text.strip()[:120]
                raise lang_error(
                    InvalidInput,
                    lang,
                    f"represent: the API rejected the request ({body}).",
                    f"represent : l'API a refusé la requête (message de l'API : {body}).",
                ) from exc
            if status in (429, 503):
                per_minute = constants.RATE_LIMIT_PER_MINUTE
                raise lang_error(
                    UpstreamUnavailable,
                    lang,
                    f"represent: HTTP {status}; the API allows {per_minute} "
                    "requests per minute, try again shortly.",
                    f"represent : HTTP {status} ; l'API permet {per_minute} requêtes par "
                    "minute, réessayez sous peu.",
                ) from exc
            raise lang_error(
                UpstreamError,
                lang,
                f"represent: {url} returned HTTP {status}.",
                f"represent : {url} a renvoyé HTTP {status}.",
            ) from exc
        except httpx.DecodingError as exc:
            raise lang_error(
                UpstreamError,
                lang,
                f"represent: {url} did not return JSON.",
                f"represent : {url} n'a pas renvoyé de JSON.",
            ) from exc
        except httpx.HTTPError as exc:
            raise lang_error(
                UpstreamUnavailable,
                lang,
                f"represent: {url} could not be reached.",
                f"represent : {url} est injoignable.",
            ) from exc

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
        freshness=fr_or_en(
            lang,
            "representatives are re-scraped by Open North on its own schedule; boundary sets "
            "are updated a few times a year; results cached 1 hour (sets 24 hours)",
            "les élus sont ré-extraits par Open North selon son propre calendrier ; les "
            "limites sont mises à jour quelques fois par an ; résultats en cache 1 h (ensembles "
            "24 h)",
        ),
        coverage=coverage,
        limits=_spaced(lang, join_limits(request, _LIMITS[lang])),
        lang=lang,
    )


def _spaced(lang: str, text: str | None) -> str | None:
    """French text with French spacing (the source strings use plain spaces)."""
    return french_spacing(text) if text and lang == "fr" else text


def _spaced_notes(lang: str, notes: list[str]) -> list[str]:
    return [french_spacing(n) for n in notes] if lang == "fr" else notes


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
        superseded_by=(
            constants.CURRENT_FEDERAL_BOUNDARY_SET if slug in constants.SUPERSEDED_SETS else None
        ),
    )


def _check_slug(value: str, what: str, lang: str = "en") -> str:
    slug = value.strip().strip("/").lower()
    if not _SLUG.match(slug):
        example = constants.CURRENT_FEDERAL_BOUNDARY_SET
        raise lang_error(
            InvalidInput,
            lang,
            f"represent: {what} must be a slug such as '{example}'.",
            f"represent : {what} doit être un identifiant comme « {example} ».",
        )
    return slug


async def _set_details(
    refs: list[BoundaryRef], lang: str = "en"
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
            raw, cached = await _get(
                f"/boundary-sets/{slug}/", ttl=constants.SETS_TTL_SECONDS, lang=lang
            )
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
    """Stale-set note, with superseded representation orders named as such.

    The unsuffixed federal set (2013 order) is dated 2017-08-23, so a plain
    "last updated more than 5 years ago" read as if the current federal map
    were stale (seen live 2026-10-03 on every postcode lookup).
    """
    notes: list[str] = []
    order = "{year} order" if lang == "en" else "ordonnance de {year}"
    superseded = [
        f"{i.slug} ({order.format(year=constants.SUPERSEDED_SETS[i.slug])})"
        for i in infos
        if i.slug in constants.SUPERSEDED_SETS
    ]
    if superseded:
        notes.append(_SUPERSEDED_NOTE[lang].format(names="; ".join(superseded)))
    stale = [
        f"{i.name or i.slug} ({i.last_updated})"
        for i in infos
        if i.possibly_stale and i.slug not in constants.SUPERSEDED_SETS
    ]
    if stale:
        notes.append(_STALE_NOTE[lang].format(names="; ".join(stale)))
    return notes


async def lookup_postcode(
    postcode: str,
    sets: str | None = None,
    include_set_details: bool = True,
    lang: Lang = "en",
) -> PostcodeLookup:
    _check_lang(lang)
    code = re.sub(r"\s+", "", postcode or "").upper()
    if not _POSTCODE.match(code):
        raise lang_error(
            InvalidInput,
            lang,
            "represent: postcode must look like T5J0N3 (letter, digit, ...).",
            "represent : postcode doit avoir la forme T5J0N3 (lettre, chiffre, ...).",
        )
    params: dict[str, Any] = {}
    if sets:
        slugs = [_check_slug(s, "sets", lang) for s in sets.split(",") if s.strip()]
        params["sets"] = ",".join(slugs)
    path = f"/postcodes/{code}/"
    try:
        raw, cached = await _get(path, params or None, lang=lang)
    except NotFound as exc:
        raise lang_error(
            NotFound,
            lang,
            f"represent: postal code {code} is not in Open North's postal code data.",
            f"represent : le code postal {code} ne figure pas dans les données d'Open North.",
        ) from exc
    # representatives_concordance is absent (not null) on many postal codes.
    # With `sets`, Represent keeps only representatives_centroid, and only for
    # sets a representative set uses (live 2026-10-03, K2J6B6: the 2023 order
    # returns Mark Carney, federal-electoral-districts drops the key), so every
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
        infos, details_cached = await _set_details(boundaries, lang)
    centroid = raw.get("centroid") or {}
    coords = centroid.get("coordinates") if isinstance(centroid, dict) else None
    lon, lat = (
        (coords[0], coords[1]) if isinstance(coords, list) and len(coords) >= 2 else (None, None)
    )
    notes = [_POSTCODE_NOTE[lang], _OLD_ORDER_NOTE[lang], *_stale_note(infos, lang)]
    if sets and not representatives:
        notes.append(_SETS_NO_REPS_NOTE[lang])
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
        notes=_spaced_notes(lang, notes),
        provenance=_provenance(
            path,
            cached and details_cached,
            "represent.PostcodeLookup",
            lang,
            params=params,
            coverage=(
                fr_or_en(
                    lang,
                    "boundary licences and dates not loaded (include_set_details=false)",
                    "licences et dates des limites non chargées (include_set_details=false)",
                )
                if not include_set_details
                else None
            ),
        ),
    )


def _check_point(latitude: float, longitude: float, lang: str = "en") -> None:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise lang_error(
            InvalidInput,
            lang,
            "represent: latitude and longitude must be finite numbers.",
            "represent : latitude et longitude doivent être des nombres finis.",
        )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise lang_error(
            InvalidInput,
            lang,
            "represent: latitude must be within -90..90 and longitude within -180..180 "
            "(latitude first, e.g. 53.5412, -113.4903).",
            "represent : latitude doit être entre -90 et 90 et longitude entre -180 et 180 "
            "(latitude d'abord, p. ex. 53.5412, -113.4903).",
        )


async def lookup_point(
    latitude: float,
    longitude: float,
    include_set_details: bool = True,
    lang: Lang = "en",
) -> PointLookup:
    _check_lang(lang)
    _check_point(latitude, longitude, lang)
    point = f"{latitude},{longitude}"
    boundaries_raw, cached_b = await _get(
        "/boundaries/", {"contains": point, "limit": constants.LIMIT_MAX}, lang=lang
    )
    reps_raw, cached_r = await _get(
        "/representatives/", {"point": point, "limit": constants.LIMIT_MAX}, lang=lang
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
        infos, details_cached = await _set_details(boundaries, lang)
    notes = [_OLD_ORDER_NOTE[lang], *_stale_note(infos, lang)]
    if not boundaries:
        notes.insert(0, _NO_MATCH_NOTE[lang])
    boundaries_url = str(
        httpx.URL(
            f"{constants.BASE_URL}/boundaries/",
            params={"contains": point, "limit": constants.LIMIT_MAX},
        )
    )
    return PointLookup(
        latitude=latitude,
        longitude=longitude,
        boundaries=boundaries,
        representatives=representatives,
        boundaries_total=int((boundaries_raw.get("meta") or {}).get("total_count") or 0),
        representatives_total=int((reps_raw.get("meta") or {}).get("total_count") or 0),
        boundary_sets=infos,
        oldest_boundary_update=_oldest(infos),
        notes=_spaced_notes(lang, notes),
        provenance=_provenance(
            "/representatives/",
            cached_b and cached_r and details_cached,
            "represent.PointLookup",
            lang,
            params={"point": point, "limit": constants.LIMIT_MAX},
            request=fr_or_en(
                lang,
                "Request: also GET " + boundaries_url + " for the boundaries",
                "Requête : aussi GET " + boundaries_url + " pour les limites",
            ),
        ),
    )


async def _representative_sets(lang: str = "en") -> tuple[list[RepresentativeSetInfo], bool]:
    raw, cached = await _get(
        "/representative-sets/", {"limit": constants.PAGE_SIZE}, constants.SETS_TTL_SECONDS, lang
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
    sets, cached = await _representative_sets(lang)
    if level:
        sets = [s for s in sets if s.level == level]
    return RepresentativeSetList(
        sets=sorted(sets, key=lambda s: (s.level, s.name)),
        total_count=len(sets),
        notes=_spaced_notes(lang, [_LEVEL_NOTE[lang]]),
        provenance=_provenance(
            "/representative-sets/",
            cached,
            "represent.RepresentativeSetList",
            lang,
            params={"limit": constants.PAGE_SIZE},
        ),
    )


async def _search_in_set(
    slug: str, params: dict[str, Any], lang: str = "en"
) -> tuple[list[dict[str, Any]], bool]:
    """Every matching representative of one set (provincial sets hold up to ~125)."""
    raw, cached = await _get(
        f"/representatives/{slug}/", {**params, "limit": constants.PAGE_SIZE}, lang=lang
    )
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
        raise lang_error(
            InvalidInput,
            lang,
            f"represent: limit must be between 1 and {constants.LIMIT_MAX}.",
            f"represent : limit doit être compris entre 1 et {constants.LIMIT_MAX}.",
        )
    if offset < 0:
        raise _bad_offset(lang)
    if level not in (None, "federal", "provincial", "municipal"):
        raise lang_error(
            InvalidInput,
            lang,
            "represent: level must be federal, provincial or municipal.",
            "represent : level doit être federal, provincial ou municipal.",
        )
    filters = {
        "name__icontains": name,
        "elected_office__icontains": office,
        "district_name__icontains": district,
    }
    params = {k: v.strip() for k, v in filters.items() if v and v.strip()}
    set_slug = (
        _check_slug(representative_set, "representative_set", lang) if representative_set else None
    )
    notes: list[str] = []
    # One party substring goes upstream as party_name__icontains. An alias with
    # several forms ("NDP" -> "NDP" or "New Democratic") is matched here
    # instead, because Represent has no OR filter.
    local_party: tuple[str, ...] = ()
    if party and party.strip():
        needles, aliased = _party_needles(party)
        if aliased:
            notes.append(
                _PARTY_ALIAS_NOTE[lang].format(party=party.strip(), needles=", ".join(needles))
            )
        if len(needles) == 1:
            params["party_name__icontains"] = needles[0]
        else:
            local_party = needles
        if not set_slug and level in (None, "provincial"):
            notes.append(_PARTY_CAUCUS_NOTE[lang])
    if not params and not local_party and not level and not set_slug:
        raise lang_error(
            InvalidInput,
            lang,
            "represent: give at least one of name, office, district, party, level or "
            "representative_set.",
            "represent : donnez au moins name, office, district, party, level ou "
            "representative_set.",
        )

    def party_ok(raw: dict[str, Any]) -> bool:
        return not local_party or _party_matches(raw, local_party)

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
            raise lang_error(
                InvalidInput,
                lang,
                f"represent: set {set_slug} is {level_of(set_slug)}, not {level}.",
                f"represent : l'ensemble {set_slug} est de palier {level_of(set_slug)}, pas "
                f"{level}.",
            )
        # An unknown set slug answers 200 with an empty list, so check it exists.
        await _get(f"/representative-sets/{set_slug}/", ttl=constants.SETS_TTL_SECONDS, lang=lang)
        rows, cached = await _search_in_set(set_slug, params, lang)
        rows = [r for r in rows if party_ok(r)]
        total = len(rows)
        rows = rows[offset : offset + limit]
    elif level in ("federal", "provincial"):
        if level == "federal":
            slugs = [constants.FEDERAL_SET]
        else:
            all_sets, cached = await _representative_sets(lang)
            slugs = [s.slug for s in all_sets if s.level == "provincial"]
        merged: list[dict[str, Any]] = []
        for slug in slugs:
            part, part_cached = await _search_in_set(slug, params, lang)
            cached = cached and part_cached
            merged.extend(r for r in part if party_ok(r))
        total = len(merged)
        rows = merged[offset : offset + limit]
        path = f"/representatives/{slugs[0]}/"
        sent = {**params, "limit": constants.PAGE_SIZE}
        request = fr_or_en(
            lang,
            f"Request: one GET /representatives/<set>/ per {level} set ({len(slugs)} sets) "
            "with the filters shown in url, merged and paged here",
            f"Requête : un GET /representatives/<set>/ par ensemble de palier {level} "
            f"({len(slugs)} ensembles) avec les filtres de url, fusionnés et paginés ici",
        )
    elif level == "municipal":
        # Represent has no level filter, so scan the (filtered) list and drop
        # federal and provincial rows here.
        merged = []
        page_offset = 0
        for _ in range(constants.MAX_SCAN_PAGES):
            raw, page_cached = await _get(
                "/representatives/",
                {**params, "limit": constants.PAGE_SIZE, "offset": page_offset},
                lang=lang,
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
                and party_ok(r)
            )
            if not (raw.get("meta") or {}).get("next") or not objects:
                break
            page_offset += len(objects)
        total = len(merged)
        rows = merged[offset : offset + limit]
        sent = {**params, "limit": constants.PAGE_SIZE, "offset": 0}
        request = fr_or_en(
            lang,
            "Request: GET /representatives/ pages from offset 0 with the filters shown in "
            "url; federal and provincial rows are dropped here, then paged",
            "Requête : pages GET /representatives/ à partir de l'offset 0 avec les filtres de "
            "url ; les lignes fédérales et provinciales sont retirées ici, puis paginées",
        )
    elif local_party:
        # One upstream query per party form, merged; a party never reaches
        # PAGE_SIZE members (the largest, Liberal, had 169 MPs on 2026-10-03).
        merged = []
        seen: set[tuple[str, str, str]] = set()
        for needle in local_party:
            raw, part_cached = await _get(
                "/representatives/",
                {**params, "party_name__icontains": needle, "limit": constants.PAGE_SIZE},
                lang=lang,
            )
            cached = cached and part_cached
            for r in list_or_empty(raw, "objects"):
                if not isinstance(r, dict):
                    continue
                ident = (
                    str(r.get("name") or ""),
                    str((r.get("related") or {}).get("representative_set_url") or ""),
                    str(r.get("district_name") or ""),
                )
                if ident not in seen:
                    seen.add(ident)
                    merged.append(r)
        total = len(merged)
        rows = merged[offset : offset + limit]
        sent = {**params, "limit": constants.PAGE_SIZE}
        request = fr_or_en(
            lang,
            "Request: one GET /representatives/ per party spelling "
            f"(party_name__icontains={', '.join(local_party)}) with the other filters "
            "shown in url, merged and paged here",
            "Requête : un GET /representatives/ par graphie du parti "
            f"(party_name__icontains={', '.join(local_party)}) avec les autres filtres de "
            "url, fusionnés et paginés ici",
        )
    else:
        raw, cached = await _get(
            "/representatives/", {**params, "limit": limit, "offset": offset}, lang=lang
        )
        rows = [r for r in list_or_empty(raw, "objects") if isinstance(r, dict)]
        total = int((raw.get("meta") or {}).get("total_count") or 0)
    if total == 0:
        notes.append(_SEARCH_NO_MATCH_NOTE[lang])
    return RepresentativeSearchResult(
        representatives=[_representative(r) for r in rows],
        total_count=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(rows) < total,
        notes=_spaced_notes(lang, notes),
        provenance=_provenance(
            path,
            cached,
            "represent.RepresentativeSearchResult",
            lang,
            params=sent,
            request=request,
            coverage=fr_or_en(
                lang,
                "representative records are a scrape of official sites and some sets are stale",
                "les fiches d'élus sont extraites de sites officiels et certains ensembles sont "
                "périmés",
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
        top = constants.MAX_SET_DETAILS * 2
        raise lang_error(
            InvalidInput,
            lang,
            f"represent: limit must be between 1 and {top}.",
            f"represent : limit doit être compris entre 1 et {top}.",
        )
    if offset < 0:
        raise _bad_offset(lang)
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if domain and domain.strip():
        params["domain__icontains"] = domain.strip()
    if name and name.strip():
        params["name__icontains"] = name.strip()
    raw, cached = await _get("/boundary-sets/", params, constants.SETS_TTL_SECONDS, lang)
    objects = [o for o in list_or_empty(raw, "objects") if isinstance(o, dict)]
    meta = raw.get("meta") or {}
    sets: list[BoundarySetInfo] = []
    for obj in objects:
        slug = _slug_from(obj.get("url"), "boundary-sets")
        if not slug:
            continue
        if with_details and len(sets) < constants.MAX_SET_DETAILS:
            detail, detail_cached = await _get(
                f"/boundary-sets/{slug}/", ttl=constants.SETS_TTL_SECONDS, lang=lang
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
            fr_or_en(
                lang,
                "Licence and last-updated date are not loaded; call with with_details=true "
                "(at most 25 sets per call).",
                "La licence et la date de mise à jour ne sont pas chargées ; appelez avec "
                "with_details=true (25 ensembles au plus par appel).",
            )
        )
    elif any(not s.detail_loaded for s in sets):
        notes.append(
            fr_or_en(
                lang,
                "Details were loaded for the first 25 sets only; page on with offset.",
                "Les détails ne sont chargés que pour les 25 premiers ensembles ; continuez "
                "avec offset.",
            )
        )
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

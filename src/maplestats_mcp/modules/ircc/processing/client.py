"""Client for IRCC's processing-times JSON files (see constants.py for their shapes).

The files have no documented contract, so each one is checked for the shape
read here and a change raises UpstreamError naming the file and what was
expected, rather than returning a partial or empty answer. A file is parsed
once into a small dict (the forward-looking file is about 500 KB, mostly
per-month keys this module does not read) and cached for an hour.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import unicodedata
from datetime import UTC, date, datetime
from typing import Any, NoReturn

import httpx

from maplestats_mcp.modules.ircc.processing import constants
from maplestats_mcp.modules.ircc.processing.schemas import (
    ApplicationType,
    ApplicationTypeList,
    CountryTime,
    ProcessingTime,
    ProcessingTimeResult,
    Qualifier,
    TimeUnit,
)
from maplestats_mcp.shared.cache import cached_fetch
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.http import get_raw
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.rate_limiter import get_limiter

_LIMITER = get_limiter(
    constants.RATE_LIMIT_SOURCE,
    rate=constants.RATE_LIMIT_PER_SECOND,
    capacity=constants.RATE_LIMIT_CAPACITY,
)

_MONTHS = {
    name: i
    for i, names in enumerate(
        (
            ("january", "janvier"),
            ("february", "fevrier"),
            ("march", "mars"),
            ("april", "avril"),
            ("may", "mai"),
            ("june", "juin"),
            ("july", "juillet"),
            ("august", "aout"),
            ("september", "septembre"),
            ("october", "octobre"),
            ("november", "novembre"),
            ("december", "decembre"),
        ),
        start=1,
    )
    for name in names
}
_UNITS: dict[str, TimeUnit] = {
    "minute": "minutes",
    "minutes": "minutes",
    "hour": "hours",
    "hours": "hours",
    "heure": "hours",
    "heures": "hours",
    "day": "days",
    "days": "days",
    "jour": "days",
    "jours": "days",
    "week": "weeks",
    "weeks": "weeks",
    "semaine": "weeks",
    "semaines": "weeks",
    "month": "months",
    "months": "months",
    "mois": "months",
    "year": "years",
    "years": "years",
    "an": "years",
    "ans": "years",
    "annee": "years",
    "annees": "years",
}
_QUALIFIERS: dict[str, Qualifier] = {
    "about": "about",
    "environ": "about",
    "more than": "more_than",
    "plus de": "more_than",
    "less than": "less_than",
    "moins de": "less_than",
}
_DURATION = re.compile(
    r"(?:(?P<q>about|environ|more than|plus de|less than|moins de)\s+)?"
    r"(?P<n>\d+(?:[.,]\d+)?)\s*(?P<u>[a-z]+)\b"
)
_NUMBER = re.compile(r"\d[\d,\s  ]*")


# ---------------------------------------------------------------- text helpers


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", stripped.casefold()).split())


def _clean(value: Any) -> str:
    """IRCC's text with HTML entities decoded (the French files escape accents)."""
    return " ".join(html.unescape(str(value)).replace(" ", " ").split())


def parse_time(raw: Any) -> ProcessingTime:
    text = _clean(raw)
    folded = _fold(text)
    if "no processing time" in folded or "aucun delai" in folded:
        return ProcessingTime(text=text, status="no_time_available")
    if "not enough data" in folded or "pas assez de donnees" in folded:
        return ProcessingTime(text=text, status="not_enough_data")
    # "Part 1: 4 months" (citizenship for adopted persons): the duration is the
    # last number in the text, so the part number is skipped.
    matches = list(_DURATION.finditer(folded.replace(" part ", " ")))
    for match in reversed(matches):
        unit = _UNITS.get(match.group("u"))
        if unit is None:
            continue
        amount = float(match.group("n").replace(",", "."))
        qualifier = _QUALIFIERS.get(match.group("q") or "")
        return ProcessingTime(
            text=text,
            status="available",
            amount=amount,
            unit=unit,
            qualifier=qualifier,
            approx_days=round(amount * constants.DAYS_PER_UNIT[unit], 4),
        )
    return ProcessingTime(text=text, status="unparsed")


def parse_people(raw: Any) -> int | None:
    match = _NUMBER.search(_clean(raw))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def parse_update_date(raw: Any) -> date | None:
    """'October 29, 2026' or '29 octobre 2026' -> date; None for anything else."""
    folded = _fold(_clean(raw)) if raw else ""
    en = re.fullmatch(r"([a-z]+) (\d{1,2}) (\d{4})", folded)
    fr = re.fullmatch(r"(\d{1,2}) ([a-z]+) (\d{4})", folded)
    if en and en.group(1) in _MONTHS:
        month, day, year = _MONTHS[en.group(1)], int(en.group(2)), int(en.group(3))
    elif fr and fr.group(2) in _MONTHS:
        month, day, year = _MONTHS[fr.group(2)], int(fr.group(1)), int(fr.group(3))
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------- fetching


def _url(file: str, lang: str) -> str:
    return f"{constants.JSON_BASE}{file}-{lang}.json"


def _shape_error(file: str, lang: str, expected: str) -> NoReturn:
    url = _url(file, lang)
    page = pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR)
    raise_localized(
        UpstreamError,
        f"IRCC's processing-times file {url} is no longer shaped as MapleStats reads it "
        f"({expected}). IRCC documents no API for these files; check the times on {page}.",
        f"le fichier des délais de traitement d'IRCC {url} n'a plus la forme que MapleStats "
        f"lit ({expected}). IRCC ne documente aucune API pour ces fichiers ; consultez les "
        f"délais sur {page}.",
        lang,
    )


async def _download(file: str, lang: str) -> Any:
    url = _url(file, lang)
    await _LIMITER.acquire()
    try:
        response = await get_raw(url)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 404:
            raise_localized(
                UpstreamError,
                f"IRCC's processing-times file {url} is gone (HTTP 404): IRCC may have moved it. "
                f"Check the times on {constants.PAGE_URL_EN}.",
                f"le fichier des délais de traitement d'IRCC {url} n'existe plus (HTTP 404) : "
                f"IRCC l'a peut-être déplacé. Consultez les délais sur {constants.PAGE_URL_FR}.",
                lang,
            )
        if status >= 500:
            raise_localized(
                UpstreamUnavailable,
                f"canada.ca returned HTTP {status} for {url}. Try again shortly.",
                f"canada.ca a renvoyé HTTP {status} pour {url}. Réessayez sous peu.",
                lang,
            )
        raise_localized(
            UpstreamError,
            f"canada.ca returned HTTP {status} for {url}.",
            f"canada.ca a renvoyé HTTP {status} pour {url}.",
            lang,
        )
    except httpx.HTTPError:
        raise_localized(
            UpstreamUnavailable,
            f"canada.ca did not answer for {url} after the shared retries. Try again shortly.",
            f"canada.ca n'a pas répondu pour {url} malgré les nouvelles tentatives. "
            "Réessayez sous peu.",
            lang,
        )
    try:
        return json.loads(response.content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _shape_error(file, lang, "the body is not JSON")


def _str_map(value: Any) -> dict[str, str]:
    return {str(k): _clean(v) for k, v in value.items() if isinstance(v, str | int | float)}


def _parse_ptime(payload: Any, lang: str) -> dict[str, Any]:
    """{type: {"updated": text|None, "countries": {code: text | {part: text}}}}."""
    if not isinstance(payload, dict) or not payload:
        _shape_error(constants.FILE_PTIME, lang, "a JSON object of application types")
    types: dict[str, Any] = {}
    for key, group in payload.items():
        if not isinstance(group, dict):
            continue
        countries: dict[str, Any] = {}
        for code, value in group.items():
            if code == "lastupdated":
                continue
            if isinstance(value, str):
                countries[str(code)] = _clean(value)
            elif isinstance(value, dict):
                parts = _str_map(value)
                if parts:
                    countries[str(code)] = parts
        if countries:
            updated = group.get("lastupdated")
            types[str(key)] = {
                "updated": _clean(updated) if isinstance(updated, str) else None,
                "countries": countries,
            }
    if not types:
        _shape_error(constants.FILE_PTIME, lang, "application types mapping country codes to times")
    return types


def _parse_non_country(payload: Any, lang: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _shape_error(constants.FILE_NON_COUNTRY, lang, "a JSON object")
    update = payload.get("default-update")
    updated = update.get("lastupdated") if isinstance(update, dict) else None
    times: dict[str, str] = {}
    for key, group in payload.items():
        if key == "default-update" or not isinstance(group, dict):
            continue
        for type_id, value in group.items():
            if isinstance(value, str):
                times[str(type_id)] = _clean(value)
    if not times:
        _shape_error(constants.FILE_NON_COUNTRY, lang, "groups of application type -> time")
    return {"updated": _clean(updated) if isinstance(updated, str) else None, "times": times}


def _parse_flpt(file: str, payload: Any, lang: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("current-flpt"), dict):
        _shape_error(file, lang, "a 'current-flpt' object of application type -> time")
    times = _str_map(payload["current-flpt"])
    if not times:
        _shape_error(file, lang, "a non-empty 'current-flpt' object")
    people_raw = payload.get("total-people")
    people = _str_map(people_raw) if isinstance(people_raw, dict) else {}
    update = payload.get("default-update")
    if isinstance(update, dict):
        updated = update.get("flpt_lastupdated")
        interval = update.get("flpt_interval")
    else:
        updated, interval = payload.get("tr-last-updated"), None
    return {
        "updated": _clean(updated) if isinstance(updated, str) else None,
        "interval": _clean(interval) if isinstance(interval, str) else None,
        "times": times,
        "people": people,
    }


def _parse(file: str, payload: Any, lang: str) -> dict[str, Any]:
    if file == constants.FILE_PTIME:
        return _parse_ptime(payload, lang)
    if file == constants.FILE_NON_COUNTRY:
        return _parse_non_country(payload, lang)
    if file == constants.FILE_COUNTRIES:
        names = payload.get("country-name") if isinstance(payload, dict) else None
        if not isinstance(names, dict) or not names:
            _shape_error(file, lang, "a 'country-name' object of code -> name")
        return _str_map(names)
    return _parse_flpt(file, payload, lang)


async def _file(file: str, lang: str) -> tuple[dict[str, Any], bool]:
    async def fetch() -> dict[str, Any]:
        return _parse(file, await _download(file, lang), lang)

    return await cached_fetch(f"ircc:ptime:{file}:{lang}", constants.CACHE_TTL_SECONDS, fetch)


# ---------------------------------------------------------------- shaping


def _note(lang: str) -> str:
    return pick(
        lang,
        "Point-in-time estimates from IRCC's 'Check processing times' tool, not a time series: "
        "IRCC replaces them when it updates its files (weekly for most temporary residence "
        "and document times, monthly for permanent residence and citizenship) and keeps no "
        "history there; last_updated is the date IRCC states. A time starts when IRCC "
        "receives a complete application and ends with a decision; it varies with "
        "application volumes and complexity. Forward-looking times estimate an application "
        "submitted now; IRCC's page says the others reflect how long it took to process 80% "
        "of applications in the past.",
        "Estimations ponctuelles de l'outil « Vérifiez les délais de traitement » d'IRCC, et "
        "non une série chronologique : IRCC les remplace à chaque mise à jour de ses fichiers "
        "(chaque semaine pour la plupart des délais de résidence temporaire et des documents, "
        "chaque mois pour la résidence permanente et la citoyenneté) sans en garder "
        "l'historique ; last_updated est la date qu'indique IRCC. Un délai commence à la "
        "réception d'une demande complète et se termine par une décision ; il varie selon le "
        "volume et la complexité des demandes. Les délais prospectifs estiment une demande "
        "présentée maintenant ; selon la page d'IRCC, les autres reflètent le temps qu'il a "
        "fallu pour traiter 80 % des demandes par le passé.",
    )


def _type_model(type_id: str, file: str, data: dict[str, Any], lang: str) -> ApplicationType:
    known = constants.TYPES.get(type_id)
    category = known[1] if known else "other"
    label = pick(lang, known[2], known[3]) if known else type_id
    cat_en, cat_fr = constants.CATEGORIES[category]
    if file == constants.FILE_PTIME:
        updated = data.get(type_id, {}).get("updated")
    else:
        updated = data.get("updated")
    if file == constants.FILE_FLPT:
        cadence = data.get("interval") or pick(lang, "monthly", "mensuelle")
    elif file == constants.FILE_FLPT_WEEK:
        # This file states no interval (its name is about application weeks).
        cadence = None
    else:
        # The page shows "Updated weekly" next to these times (read 2026-11-03).
        cadence = pick(lang, "weekly", "hebdomadaire")
    return ApplicationType(
        type_id=type_id,
        label=label,
        category=category,
        category_label=pick(lang, cat_en, cat_fr),
        by_country=file == constants.FILE_PTIME,
        basis="forward_looking"
        if file in (constants.FILE_FLPT, constants.FILE_FLPT_WEEK)
        else "processing_time",
        last_updated=updated,
        last_updated_date=parse_update_date(updated),
        update_cadence=cadence,
        source_url=_url(file, lang),
    )


def _types_in(file: str, data: dict[str, Any]) -> list[str]:
    if file == constants.FILE_PTIME:
        return list(data)
    return list(data.get("times", {}))


def _as_of(types: list[ApplicationType]) -> datetime | None:
    dates = [t.last_updated_date for t in types if t.last_updated_date]
    if not dates:
        return None
    newest = max(dates)
    return datetime(newest.year, newest.month, newest.day, tzinfo=UTC)


def _freshness(lang: str) -> str:
    return pick(
        lang,
        "IRCC updates these files weekly (temporary residence, documents) or monthly "
        "(permanent residence, citizenship); MapleStats caches each for an hour",
        "IRCC met à jour ces fichiers chaque semaine (résidence temporaire, documents) ou "
        "chaque mois (résidence permanente, citoyenneté) ; MapleStats garde chacun en cache "
        "une heure",
    )


async def _all_files(lang: str) -> tuple[dict[str, dict[str, Any]], bool]:
    results = await asyncio.gather(*(_file(f, lang) for f in constants.TIME_FILES))
    files = {f: data for f, (data, _) in zip(constants.TIME_FILES, results, strict=True)}
    return files, all(cached for _, cached in results)


def _all_types(files: dict[str, dict[str, Any]], lang: str) -> list[ApplicationType]:
    seen: set[str] = set()
    types: list[ApplicationType] = []
    for file in constants.TIME_FILES:
        for type_id in _types_in(file, files[file]):
            if type_id in seen:
                continue
            seen.add(type_id)
            types.append(_type_model(type_id, file, files[file], lang))
    order = list(constants.CATEGORIES)
    types.sort(key=lambda t: order.index(t.category))
    return types


def _resolve_type(query: str, types: list[ApplicationType], lang: str) -> ApplicationType:
    text = query.strip()
    if not text:
        raise_localized(
            InvalidInput,
            "application_type must not be empty. List the types with "
            "ircc_processing_list_application_types.",
            "application_type ne doit pas être vide. Listez les types avec "
            "ircc_processing_list_application_types.",
            lang,
        )
    key = _fold(text)
    exact = [t for t in types if _fold(t.type_id) == key]
    if exact:
        return exact[0]
    words = key.split()
    hits = [t for t in types if all(w in _fold(f"{t.type_id} {t.label}") for w in words)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise_localized(
            NotFound,
            f"No IRCC application type matches {query!r}. List them with "
            "ircc_processing_list_application_types and pass a type_id.",
            f"aucun type de demande d'IRCC ne correspond à {query!r}. Listez-les avec "
            "ircc_processing_list_application_types et passez un type_id.",
            lang,
        )
    options = "; ".join(f"{t.type_id} ({t.label})" for t in hits[:12])
    raise_localized(
        InvalidInput,
        f"application_type {query!r} matches several types: {options}. Pass one type_id.",
        f"application_type {query!r} correspond à plusieurs types : {options}. Passez un seul "
        "type_id.",
        lang,
    )


def _provenance(
    url: str, cached: bool, schema: str, as_of: datetime | None, lang: str, coverage: str
):
    return make_provenance(
        source=constants.RATE_LIMIT_SOURCE,
        url=url,
        cached=cached,
        schema_name=f"ircc.{schema}",
        as_of=as_of,
        freshness=_freshness(lang),
        coverage=coverage,
        lang=lang,
    )


# ---------------------------------------------------------------- public API


async def list_application_types(
    category: str | None = None, lang: str = "en"
) -> ApplicationTypeList:
    wanted = category.strip().lower() if category and category.strip() else None
    if wanted and wanted not in constants.CATEGORIES:
        raise_localized(
            InvalidInput,
            f"category must be one of {', '.join(constants.CATEGORIES)}, got {category!r}.",
            f"category doit être l'une des valeurs {', '.join(constants.CATEGORIES)} "
            f"(reçu : {category!r}).",
            lang,
        )
    files, cached = await _all_files(lang)
    types = _all_types(files, lang)
    if wanted:
        types = [t for t in types if t.category == wanted]
    return ApplicationTypeList(
        types=types,
        returned_count=len(types),
        category=wanted,
        page_url=pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR),
        note=_note(lang),
        provenance=_provenance(
            constants.JSON_BASE,
            cached,
            "ApplicationTypeList",
            _as_of(types),
            lang,
            pick(
                lang,
                f"{len(types)} application types in IRCC's four processing-times files",
                f"{len(types)} types de demande dans les quatre fichiers des délais d'IRCC",
            ),
        ),
    )


def _resolve_country(
    query: str, available: dict[str, Any], names: dict[str, str], lang: str
) -> str:
    text = query.strip()
    if text.upper() in available:
        return text.upper()
    key = _fold(text)
    exact = [c for c in available if _fold(names.get(c, "")) == key]
    if len(exact) == 1:
        return exact[0]
    partial = [c for c in available if key and key in _fold(names.get(c, ""))]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise_localized(
            NotFound,
            f"No country matches {query!r} for this application type. Pass a two-letter "
            "ISO code (IN, PH, NG) or a country name, or leave country out to get every country.",
            f"aucun pays ne correspond à {query!r} pour ce type de demande. Passez un code ISO "
            "de deux lettres (IN, PH, NG) ou un nom de pays, ou omettez country pour obtenir "
            "tous les pays.",
            lang,
        )
    options = "; ".join(f"{c} {names.get(c, c)}" for c in partial[:12])
    raise_localized(
        InvalidInput,
        f"country {query!r} matches several countries: {options}. Pass its ISO code.",
        f"le pays {query!r} correspond à plusieurs pays : {options}. Passez son code ISO.",
        lang,
    )


async def get_processing_time(
    application_type: str, country: str | None = None, lang: str = "en"
) -> ProcessingTimeResult:
    files, cached = await _all_files(lang)
    chosen = _resolve_type(application_type, _all_types(files, lang), lang)
    file = next(f for f in constants.TIME_FILES if chosen.type_id in _types_in(f, files[f]))
    data = files[file]
    page = pick(lang, constants.PAGE_URL_EN, constants.PAGE_URL_FR)
    as_of = _as_of([chosen])
    url = _url(file, lang)
    if not chosen.by_country:
        if country and country.strip():
            raise_localized(
                InvalidInput,
                f"{chosen.type_id} has one processing time for everyone, not one per country; "
                "leave country out.",
                f"{chosen.type_id} a un seul délai pour tous, et non un par pays ; omettez "
                "country.",
                lang,
            )
        people_text = data.get("people", {}).get(chosen.type_id)
        return ProcessingTimeResult(
            application_type=chosen,
            time=parse_time(data["times"][chosen.type_id]),
            people_waiting=parse_people(people_text) if people_text else None,
            people_waiting_text=people_text,
            countries=[],
            returned_count=1,
            page_url=page,
            note=_note(lang),
            provenance=_provenance(
                url,
                cached,
                "ProcessingTimeResult",
                as_of,
                lang,
                pick(
                    lang,
                    f"IRCC's current time for {chosen.type_id}",
                    f"délai actuel d'IRCC pour {chosen.type_id}",
                ),
            ),
        )
    names_data, names_cached = await _file(constants.FILE_COUNTRIES, lang)
    names = dict(names_data)
    for code, (en, fr) in constants.EXTRA_COUNTRIES.items():
        names.setdefault(code, pick(lang, en, fr))
    by_country: dict[str, Any] = data[chosen.type_id]["countries"]
    codes = list(by_country)
    if country and country.strip():
        codes = [_resolve_country(country, by_country, names, lang)]
    entries: list[CountryTime] = []
    for code in codes:
        value = by_country[code]
        parts = value.items() if isinstance(value, dict) else [(None, value)]
        for component, text in parts:
            entries.append(
                CountryTime(
                    country_code=code,
                    country_name=names.get(code, code),
                    component=component,
                    time=parse_time(text),
                )
            )
    entries.sort(key=lambda e: (-(e.time.approx_days or -1), e.country_name))
    available = sum(e.time.status == "available" for e in entries)
    return ProcessingTimeResult(
        application_type=chosen,
        time=None,
        countries=entries,
        country=country.strip() if country and country.strip() else None,
        returned_count=len(entries),
        page_url=page,
        note=_note(lang),
        provenance=_provenance(
            url,
            cached and names_cached,
            "ProcessingTimeResult",
            as_of,
            lang,
            pick(
                lang,
                f"{len(entries)} country entries for {chosen.type_id}, {available} with a "
                "published time; longest first",
                f"{len(entries)} entrées par pays pour {chosen.type_id}, dont {available} avec "
                "un délai publié ; les plus longs d'abord",
            ),
        ),
    )

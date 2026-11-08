"""Curated reads of City of Toronto DataStore tables (see the module docstring).

Every request goes through `ckan.client.datastore_search`, so the Toronto
portal's rate limit, retries, cache and typed errors are the ones `ckan_*`
uses. Whole tables are read in pages of 1,000 rows (the RentSafeTO table is
8 pages, the 2016 profiles 3 for the few columns asked for) and filtered
here, because the DataStore has no "contains" filter or ranges and the
latest evaluation per building needs every row of that building.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import statistics
import unicodedata
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from maplestats_mcp.modules.ckan import client as ckan_client
from maplestats_mcp.modules.ckan.constants import PORTALS
from maplestats_mcp.modules.toronto import constants as c
from maplestats_mcp.modules.toronto.schemas import (
    ApartmentEvaluation,
    ApartmentEvaluations,
    ApartmentScoreSummary,
    CountGroup,
    DatasetSource,
    Inspection,
    InspectionSearch,
    NeighbourhoodProfile,
    ProfileRow,
    ScoreGroup,
    ShortTermRentalSummary,
)
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.i18n import pick

EvaluationSort = Literal["score_asc", "score_desc", "date_desc", "address"]


# --- shared helpers ---------------------------------------------------------


async def _page(
    resource_id: str,
    lang: str,
    *,
    fields: str | None = None,
    filters: dict[str, str] | None = None,
    query: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, bool]:
    """One datastore_search page (a full page by default): records, total, cached."""
    result = await ckan_client.datastore_search(
        c.PORTAL,
        resource_id,
        filters=filters,
        query=query,
        sort=sort,
        fields=fields,
        limit=limit or c.PAGE_ROWS,
        offset=offset,
        lang=lang,
    )
    return result.records, result.total_count, result.provenance.cached


async def _all_rows(
    resource_id: str, fields: tuple[str, ...], lang: str
) -> tuple[list[dict[str, Any]], bool]:
    """Every row of a table, `fields` only, in `_id` order (pages of 1,000)."""
    joined = ",".join(fields)
    rows, total, cached = await _page(resource_id, lang, fields=joined, sort="_id")
    while len(rows) < total:
        more, total, page_cached = await _page(
            resource_id, lang, fields=joined, sort="_id", offset=len(rows)
        )
        if not more:
            break
        rows.extend(more)
        cached = cached and page_cached
    return rows, cached


def _url(params: dict[str, Any]) -> str:
    return str(httpx.URL(f"{PORTALS[c.PORTAL].base_url}datastore_search", params=params))


def _source(dataset: str, resource_id: str, lang: str) -> DatasetSource:
    title = c.DATASET_TITLES[dataset]
    landing = c.DATASET_URL.format(name=dataset)
    today = datetime.now(UTC).date().isoformat()
    return DatasetSource(
        dataset=title,
        landing_page=landing,
        resource_id=resource_id,
        licence=pick(
            lang,
            f"Open Government Licence - Toronto ({c.LICENCE_URL})",
            f"Licence du gouvernement ouvert – Toronto ({c.LICENCE_URL})",
        ),
        citation=pick(
            lang,
            f"City of Toronto, {title}, open.toronto.ca ({landing}), DataStore resource "
            f"{resource_id}, retrieved {today}. Contains information licensed under the Open "
            "Government Licence - Toronto.",
            f"Ville de Toronto, {title}, open.toronto.ca ({landing}), ressource DataStore "
            f"{resource_id}, consultée le {today}. Contient des renseignements visés par la "
            "Licence du gouvernement ouvert – Toronto (Open Government Licence – Toronto).",
        ),
    )


def _provenance(
    params: dict[str, Any], cached: bool, schema: str, lang: str, limits_en: str, limits_fr: str
):
    return make_provenance(
        source=c.SOURCE,
        url=_url(params),
        cached=cached,
        schema_name=f"toronto.{schema}",
        limits=pick(
            lang,
            limits_en,
            f"{limits_fr} Contenu publié par la Ville de Toronto en anglais seulement ; les "
            "valeurs et libellés sont donnés tels que publiés.",
        ),
        lang=lang,
    )


def _fold(text: str) -> str:
    """Lower case, accents and punctuation removed: 'Mimico (includes...)' -> 'mimicoincludes...'."""
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]", "", plain.casefold())


def _text(value: Any) -> str | None:
    if value is None:
        return None
    out = str(value).strip()
    return out or None


def _number(value: Any) -> float | None:
    """A published value as a number: '525,835' -> 525835.0, '46.8' -> 46.8, 'N/A' -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    else:
        cleaned = str(value).strip().replace(",", "").replace("$", "").rstrip("%").strip()
        if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            return None
        number = float(cleaned)
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _check_paging(limit: int, offset: int, lang: str) -> None:
    if limit < 1 or limit > c.ROWS_MAX:
        raise_localized(
            InvalidInput,
            f"limit must be between 1 and {c.ROWS_MAX}, got {limit}.",
            f"limit doit être entre 1 et {c.ROWS_MAX} (reçu : {limit}).",
            lang,
        )
    if offset < 0:
        raise_localized(
            InvalidInput,
            f"offset must be >= 0, got {offset}.",
            f"offset doit être positif ou nul (reçu : {offset}).",
            lang,
        )


# --- Neighbourhood Profiles -------------------------------------------------


async def _profile_columns(table: c.ProfileTable, lang: str) -> list[str]:
    """The neighbourhood columns of a profile table (every column but the labels)."""
    result = await ckan_client.datastore_search(c.PORTAL, table.resource_id, limit=1, lang=lang)
    return [
        f.id
        for f in result.fields
        if f.id not in c.PROFILE_META_COLUMNS and f.id not in (c.CITY_COLUMN, "_full_text")
    ]


async def _neighbourhood_numbers(lang: str) -> dict[str, str]:
    """Neighbourhood number -> name, from the 2016 table's 'Neighbourhood Number' row."""
    table = c.PROFILE_TABLES[2016]
    rows, _, _ = await _page(
        table.resource_id,
        lang,
        filters={table.label_column: c.NEIGHBOURHOOD_NUMBER_LABEL},
        limit=1,
    )
    if not rows:
        return {}
    return {
        str(int(number)): name
        for name, value in rows[0].items()
        if name not in c.PROFILE_META_COLUMNS
        and (number := _number(value)) is not None
        and number.is_integer()
    }


async def _resolve_neighbourhood(
    neighbourhood: str, columns: list[str], lang: str
) -> tuple[str, str | None]:
    """The table column for a name or number, and the 2016 number when known."""
    wanted = neighbourhood.strip()
    if not wanted:
        raise_localized(
            InvalidInput,
            "neighbourhood must not be empty: give a name ('Annex') or a 140-model number "
            "('95'), or 'City of Toronto' for the city.",
            "neighbourhood ne doit pas être vide : donnez un nom ('Annex') ou un numéro du "
            "modèle à 140 quartiers ('95'), ou 'City of Toronto' pour la ville.",
            lang,
        )
    numbers = await _neighbourhood_numbers(lang)
    number_of = {name: number for number, name in numbers.items()}
    # "95" or "Annex (95)", the form the City's boundary files use.
    numbered = re.fullmatch(r"(?:.*?\()?\s*(\d+)\s*\)?", wanted)
    if numbered:
        name = numbers.get(str(int(numbered.group(1))))
        if name and name in columns:
            return name, number_of[name]
    folded = _fold(wanted)
    if folded == _fold(c.CITY_COLUMN) or folded == "toronto":
        return c.CITY_COLUMN, None
    exact = [col for col in columns if _fold(col) == folded]
    partial = [col for col in columns if folded and folded in _fold(col)]
    matches = exact or partial
    if len(matches) == 1:
        return matches[0], number_of.get(matches[0])
    if len(matches) > 1:
        raise_localized(
            InvalidInput,
            f"neighbourhood {neighbourhood!r} matches several: {matches}. Give the full name.",
            f"neighbourhood {neighbourhood!r} correspond à plusieurs quartiers : {matches}. "
            "Donnez le nom complet.",
            lang,
        )
    close = difflib.get_close_matches(wanted, columns, n=5, cutoff=0.5)
    raise_localized(
        NotFound,
        f"No neighbourhood {neighbourhood!r} in the 140-neighbourhood model. Closest: {close}. "
        "The profiles use the City's 140 neighbourhoods (before the 2021 158-neighbourhood "
        "model).",
        f"aucun quartier {neighbourhood!r} dans le modèle à 140 quartiers. Les plus proches : "
        f"{close}. Les profils utilisent les 140 quartiers de la Ville (avant le modèle à 158 "
        "quartiers de 2021).",
        lang,
    )


async def get_neighbourhood_profile(
    neighbourhood: str,
    topic: str | None = None,
    characteristic: str | None = None,
    census_year: int = 2016,
    limit: int = c.ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> NeighbourhoodProfile:
    table = c.PROFILE_TABLES.get(census_year)
    if table is None:
        years = sorted(c.PROFILE_TABLES, reverse=True)
        raise_localized(
            InvalidInput,
            f"census_year must be one of {years}. The 2021 profiles (158 neighbourhoods) are "
            "published only as an Excel file, which this server does not download from "
            "Toronto's portal.",
            f"census_year doit être l'une de {years}. Les profils de 2021 (158 quartiers) ne "
            "sont publiés qu'en fichier Excel, que ce serveur ne télécharge pas du portail de "
            "Toronto.",
            lang,
        )
    _check_paging(limit, offset, lang)
    columns = await _profile_columns(table, lang)
    column, number = await _resolve_neighbourhood(neighbourhood, columns, lang)
    fields = ["_id", "Category", "Topic", table.label_column]
    if table.has_source_column:
        fields.append("Data Source")
    fields.append(c.CITY_COLUMN)
    if column != c.CITY_COLUMN:
        fields.append(column)
    rows, cached = await _all_rows(table.resource_id, tuple(fields), lang)

    topics: list[str] = []
    for row in rows:
        name = _text(row.get("Topic"))
        if name and name not in topics:
            topics.append(name)
    topic_key = _fold(topic) if topic else None
    if topic_key and not any(topic_key in _fold(name) for name in topics):
        raise_localized(
            InvalidInput,
            f"no topic matches {topic!r} in the {census_year} profiles; topics are {topics}.",
            f"aucun sujet ne correspond à {topic!r} dans les profils de {census_year} ; les "
            f"sujets sont {topics}.",
            lang,
        )
    wanted = characteristic.strip().casefold() if characteristic else None
    selected: list[ProfileRow] = []
    for row in rows:
        label_raw = str(row.get(table.label_column) or "")
        label = label_raw.strip()
        if topic_key and topic_key not in _fold(str(row.get("Topic") or "")):
            continue
        if wanted and wanted not in label.casefold():
            continue
        value = row.get(column)
        city = row.get(c.CITY_COLUMN)
        selected.append(
            ProfileRow(
                category=_text(row.get("Category")),
                topic=_text(row.get("Topic")),
                characteristic=label,
                level=(len(label_raw) - len(label_raw.lstrip(" "))) // 2,
                data_source=_text(row.get("Data Source")) if table.has_source_column else None,
                value=_text(value),
                value_number=_number(value),
                city_value=_text(city),
                city_value_number=_number(city),
            )
        )
    page = selected[offset : offset + limit]
    params: dict[str, Any] = {
        "resource_id": table.resource_id,
        "fields": ",".join(fields),
        "sort": "_id",
        "limit": c.PAGE_ROWS,
    }
    return NeighbourhoodProfile(
        census_year=census_year,
        neighbourhood=column,
        neighbourhood_number=number,
        topic_filter=topic,
        characteristic_filter=characteristic,
        total_matched=len(selected),
        returned_count=len(page),
        offset=offset,
        rows=page,
        topics=topics,
        source=_source(c.PROFILE_DATASET, table.resource_id, lang),
        provenance=_provenance(
            params,
            cached,
            "NeighbourhoodProfile",
            lang,
            f"Census {census_year} figures compiled by the City for its 140 neighbourhoods "
            "(the model used before 2021). Values as published; value_number is parsed from "
            "them. Topic matches part of a topic name, characteristic part of a label.",
            f"Données du recensement de {census_year} compilées par la Ville pour ses 140 "
            "quartiers (le modèle d'avant 2021). Valeurs telles que publiées ; value_number en "
            "est tiré. topic correspond à une partie du nom d'un sujet, characteristic à une "
            "partie d'un libellé.",
        ),
    )


# --- RentSafeTO apartment building evaluations ------------------------------


def _evaluation(row: dict[str, Any], count: int) -> ApartmentEvaluation:
    completed = _text(row.get("EVALUATION COMPLETED ON"))
    return ApartmentEvaluation(
        rsn=str(row.get("RSN") or "").strip(),
        address=_text(row.get("SITE ADDRESS")),
        ward=_text(row.get("WARD")),
        ward_name=_text(row.get("WARDNAME")),
        property_type=_text(row.get("PROPERTY TYPE")),
        year_built=_int(row.get("YEAR BUILT")),
        year_registered=_int(row.get("YEAR REGISTERED")),
        storeys=_int(row.get("CONFIRMED STOREYS")),
        units=_int(row.get("CONFIRMED UNITS")),
        evaluation_date=completed[:10] if completed else None,
        score=_number(row.get("CURRENT BUILDING EVAL SCORE")),
        proactive_score=_number(row.get("PROACTIVE BUILDING SCORE")),
        reactive_score=_number(row.get("CURRENT REACTIVE SCORE")),
        areas_evaluated=_int(row.get("NO OF AREAS EVALUATED")),
        latitude=_number(row.get("LATITUDE")),
        longitude=_number(row.get("LONGITUDE")),
        evaluations_on_record=count,
    )


async def _evaluations(lang: str, latest_only: bool) -> tuple[list[ApartmentEvaluation], bool]:
    rows, cached = await _all_rows(c.EVALUATION_RESOURCE, ("_id", *c.EVALUATION_FIELDS), lang)
    counts: dict[str, int] = {}
    for row in rows:
        rsn = str(row.get("RSN") or "").strip()
        counts[rsn] = counts.get(rsn, 0) + 1
    evaluations = [_evaluation(row, counts[str(row.get("RSN") or "").strip()]) for row in rows]
    if not latest_only:
        return evaluations, cached
    # YEAR EVALUATED holds one 202510, so the latest evaluation is chosen by the
    # completion date; rows come in _id order, so a tie keeps the later row.
    latest: dict[str, ApartmentEvaluation] = {}
    for evaluation in evaluations:
        kept = latest.get(evaluation.rsn)
        if kept is None or (evaluation.evaluation_date or "") >= (kept.evaluation_date or ""):
            latest[evaluation.rsn] = evaluation
    return list(latest.values()), cached


def _ward_key(ward: str, evaluations: list[ApartmentEvaluation], lang: str) -> str:
    """'5', '05', 'Ward 5' or a ward name -> the table's two-digit ward number."""
    wards = {e.ward: e.ward_name for e in evaluations if e.ward}
    digits = re.sub(r"\D", "", ward)
    if digits and _fold(ward).removeprefix("ward") == digits:
        key = digits.zfill(2)
        if key in wards:
            return key
    folded = _fold(ward)
    for key, name in wards.items():
        if name and _fold(name) == folded:
            return key
    listing = ", ".join(f"{key} {name}" for key, name in sorted(wards.items()))
    raise_localized(
        InvalidInput,
        f"unknown ward {ward!r}; Toronto's 25 wards are: {listing}.",
        f"quartier électoral {ward!r} inconnu ; les 25 quartiers de Toronto sont : {listing}.",
        lang,
    )


_SORTS = ("score_asc", "score_desc", "date_desc", "address")


def _sort(evaluations: list[ApartmentEvaluation], sort: str) -> None:
    """Sort in place; buildings without a score go last for the score orders."""
    if sort == "date_desc":
        evaluations.sort(key=lambda e: e.evaluation_date or "", reverse=True)
    elif sort == "address":
        evaluations.sort(key=lambda e: e.address or "")
    else:
        sign = 1.0 if sort == "score_asc" else -1.0
        evaluations.sort(key=lambda e: (e.score is None, sign * (e.score or 0.0)))


async def get_apartment_evaluations(
    ward: str | None = None,
    address: str | None = None,
    latest_only: bool = True,
    sort: EvaluationSort = "score_asc",
    limit: int = c.ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> ApartmentEvaluations:
    _check_paging(limit, offset, lang)
    if sort not in _SORTS:
        raise_localized(
            InvalidInput,
            f"sort must be one of {list(_SORTS)}, got {sort!r}.",
            f"sort doit être l'une de {list(_SORTS)} (reçu : {sort!r}).",
            lang,
        )
    evaluations, cached = await _evaluations(lang, latest_only)
    if ward:
        key = _ward_key(ward, evaluations, lang)
        evaluations = [e for e in evaluations if e.ward == key]
    if address:
        wanted = address.strip().casefold()
        evaluations = [e for e in evaluations if wanted in (e.address or "").casefold()]
    _sort(evaluations, sort)
    page = evaluations[offset : offset + limit]
    params = {
        "resource_id": c.EVALUATION_RESOURCE,
        "fields": ",".join(("_id", *c.EVALUATION_FIELDS)),
        "sort": "_id",
        "limit": c.PAGE_ROWS,
    }
    return ApartmentEvaluations(
        latest_only=latest_only,
        ward_filter=ward,
        address_filter=address,
        sort=sort,
        total_matched=len(evaluations),
        returned_count=len(page),
        offset=offset,
        evaluations=page,
        source=_source(c.EVALUATION_DATASET, c.EVALUATION_RESOURCE, lang),
        provenance=_provenance(
            params,
            cached,
            "ApartmentEvaluations",
            lang,
            "RentSafeTO evaluations since 2023 of apartment buildings with 3+ storeys or 10+ "
            "units; each building is evaluated at least every two years. With latest_only, "
            "one row per building (its most recent evaluation). Evaluations before 2023, under "
            "the earlier process with fewer categories, are in the dataset's other resource.",
            "Évaluations RentSafeTO depuis 2023 des immeubles d'appartements de 3 étages et "
            "plus ou de 10 logements et plus ; chaque immeuble est évalué au moins tous les "
            "deux ans. Avec latest_only, une ligne par immeuble (sa dernière évaluation). Les "
            "évaluations d'avant 2023, selon l'ancien processus à moins de catégories, sont "
            "dans l'autre ressource du jeu.",
        ),
    )


def _score_group(key: str, label: str | None, group: list[ApartmentEvaluation]) -> ScoreGroup:
    scores = sorted(e.score for e in group if e.score is not None)
    return ScoreGroup(
        key=key,
        label=label,
        buildings=len(group),
        units=sum(e.units or 0 for e in group),
        mean_score=round(statistics.fmean(scores), 2) if scores else None,
        median_score=round(statistics.median(scores), 2) if scores else None,
        p25_score=(
            round(statistics.quantiles(scores, n=4, method="inclusive")[0], 2)
            if len(scores) > 1
            else (scores[0] if scores else None)
        ),
        min_score=scores[0] if scores else None,
        max_score=scores[-1] if scores else None,
    )


async def summarize_apartment_scores(
    group_by: Literal["ward", "property_type"] = "ward",
    evaluated_since: int | None = None,
    lang: str = "en",
) -> ApartmentScoreSummary:
    if group_by not in ("ward", "property_type"):
        raise_localized(
            InvalidInput,
            f"group_by must be 'ward' or 'property_type', got {group_by!r}.",
            f"group_by doit être 'ward' ou 'property_type' (reçu : {group_by!r}).",
            lang,
        )
    evaluations, cached = await _evaluations(lang, latest_only=True)
    if evaluated_since is not None:
        evaluations = [
            e for e in evaluations if (e.evaluation_date or "")[:4] >= str(evaluated_since)
        ]
    groups: dict[str, list[ApartmentEvaluation]] = {}
    labels: dict[str, str | None] = {}
    for evaluation in evaluations:
        key = (evaluation.ward if group_by == "ward" else evaluation.property_type) or "unknown"
        groups.setdefault(key, []).append(evaluation)
        if group_by == "ward":
            labels[key] = evaluation.ward_name
    params = {
        "resource_id": c.EVALUATION_RESOURCE,
        "fields": ",".join(("_id", *c.EVALUATION_FIELDS)),
        "sort": "_id",
        "limit": c.PAGE_ROWS,
    }
    return ApartmentScoreSummary(
        group_by=group_by,
        evaluated_since=evaluated_since,
        buildings=len(evaluations),
        groups=[_score_group(k, labels.get(k), groups[k]) for k in sorted(groups)],
        city=_score_group("all", None, evaluations),
        source=_source(c.EVALUATION_DATASET, c.EVALUATION_RESOURCE, lang),
        provenance=_provenance(
            params,
            cached,
            "ApartmentScoreSummary",
            lang,
            "Each building counts once, at its most recent RentSafeTO evaluation since 2023 "
            "(0 to 100). Means and percentiles are of building scores, not weighted by units.",
            "Chaque immeuble compte une fois, à sa dernière évaluation RentSafeTO depuis 2023 "
            "(0 à 100). Moyennes et centiles portent sur les notes des immeubles, sans "
            "pondération par logement.",
        ),
    )


# --- Short-term rental registrations ----------------------------------------

_RENTAL_COLUMNS = {
    "ward": "ward_number",
    "property_type": "property_type",
    "postal_code": "postal_code",
}


async def summarize_short_term_rentals(
    group_by: Literal["ward", "property_type", "postal_code"] = "ward",
    lang: str = "en",
) -> ShortTermRentalSummary:
    column = _RENTAL_COLUMNS.get(group_by)
    if column is None:
        raise_localized(
            InvalidInput,
            f"group_by must be one of {sorted(_RENTAL_COLUMNS)}, got {group_by!r}.",
            f"group_by doit être l'une de {sorted(_RENTAL_COLUMNS)} (reçu : {group_by!r}).",
            lang,
        )
    rows, cached = await _all_rows(c.RENTAL_RESOURCE, ("_id", *c.RENTAL_FIELDS), lang)
    counts: dict[str, int] = {}
    labels: dict[str, str | None] = {}
    for row in rows:
        key = _text(row.get(column)) or "unknown"
        if group_by == "ward" and key.isdigit():
            key = key.zfill(2)
        counts[key] = counts.get(key, 0) + 1
        if group_by == "ward":
            labels[key] = _text(row.get("ward_name"))
    total = sum(counts.values())
    order = sorted(counts) if group_by == "ward" else sorted(counts, key=lambda k: (-counts[k], k))
    params = {
        "resource_id": c.RENTAL_RESOURCE,
        "fields": ",".join(("_id", *c.RENTAL_FIELDS)),
        "sort": "_id",
        "limit": c.PAGE_ROWS,
    }
    return ShortTermRentalSummary(
        group_by=group_by,
        registrations=total,
        groups=[
            CountGroup(
                key=key,
                label=labels.get(key),
                registrations=counts[key],
                share=round(counts[key] / total, 4) if total else 0.0,
            )
            for key in order
        ],
        source=_source(c.RENTAL_DATASET, c.RENTAL_RESOURCE, lang),
        provenance=_provenance(
            params,
            cached,
            "ShortTermRentalSummary",
            lang,
            "Registrations in force with the City's short-term rental program (refreshed "
            "daily); a registration is not a booking or a night stayed. Counts only: the "
            "table's operator registration numbers and addresses are not returned.",
            "Inscriptions en vigueur au programme de location à court terme de la Ville (mises "
            "à jour chaque jour) ; une inscription n'est ni une réservation ni une nuitée. "
            "Décomptes seulement : les numéros d'inscription et adresses des exploitants ne "
            "sont pas renvoyés.",
        ),
    )


# --- DineSafe ---------------------------------------------------------------


def _inspection(row: dict[str, Any]) -> Inspection:
    address = _text(row.get("address"))
    if address:
        # An empty unit is written as the word "None" inside the address.
        address = re.sub(r"\s+None\s+", " ", f" {address} ").strip()
    outcome_date = _text(row.get("OutcomeDate"))
    inspected = _text(row.get("inspectionDate"))
    return Inspection(
        establishment_id=_text(row.get("estId")),
        establishment=_text(row.get("estName")),
        address=address,
        inspection_date=inspected[:10] if inspected else None,
        status=_text(row.get("inspectionStatus")),
        severity=_text(row.get("severity")),
        infraction=_text(row.get("typeDesc")),
        deficiency=_text(row.get("deficiencyDesc")),
        outcome=_text(row.get("OutcomeDesc")),
        outcome_date=outcome_date[:10] if outcome_date else None,
        amount_fined=_number(row.get("amountFined")),
        latitude=_number(row.get("latitude")),
        longitude=_number(row.get("longitude")),
    )


async def search_dinesafe(
    establishment: str | None = None,
    address: str | None = None,
    status: str | None = None,
    limit: int = c.ROWS_DEFAULT,
    offset: int = 0,
    lang: str = "en",
) -> InspectionSearch:
    _check_paging(limit, offset, lang)
    filters: dict[str, str] | None = None
    if status:
        known = {s.casefold(): s for s in c.DINESAFE_STATUSES}
        exact = known.get(status.strip().casefold())
        if exact is None:
            raise_localized(
                InvalidInput,
                f"status must be one of {list(c.DINESAFE_STATUSES)}, got {status!r}.",
                f"status doit être l'une de {list(c.DINESAFE_STATUSES)} (reçu : {status!r}).",
                lang,
            )
        filters = {"inspectionStatus": exact}
    words = {
        column: value.strip()
        for column, value in (("estName", establishment), ("address", address))
        if value and value.strip()
    }
    # A JSON object makes `q` a per-column full-text search (checked live).
    query = json.dumps(words) if words else None
    sort = "inspectionDate desc, _id asc"
    fields = ",".join(c.DINESAFE_FIELDS)
    rows, total, cached = await _page(
        c.DINESAFE_RESOURCE,
        lang,
        fields=fields,
        filters=filters,
        query=query,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    params: dict[str, Any] = {
        "resource_id": c.DINESAFE_RESOURCE,
        "fields": fields,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
    if query:
        params["q"] = query
    if filters:
        params["filters"] = json.dumps(filters)
    return InspectionSearch(
        establishment_filter=establishment,
        address_filter=address,
        status_filter=filters["inspectionStatus"] if filters else None,
        total_matched=total,
        returned_count=len(rows),
        offset=offset,
        inspections=[_inspection(row) for row in rows],
        source=_source(c.DINESAFE_DATASET, c.DINESAFE_RESOURCE, lang),
        provenance=_provenance(
            params,
            cached,
            "InspectionSearch",
            lang,
            "Toronto Public Health DineSafe inspections, newest first: one row per infraction "
            "(an inspection with none has one row, severity 'None'). The table holds recent "
            "inspections only (from 2023-11-10 when checked on 2026-11-08); older ones are in "
            "a historical ZIP file not read here. establishment and address match whole words "
            "of the name and address.",
            "Inspections DineSafe de Santé publique Toronto, les plus récentes d'abord : une "
            "ligne par infraction (une inspection sans infraction a une ligne, severity "
            "'None'). Le tableau ne garde que les inspections récentes (depuis le 2023-11-10 "
            "au 2026-11-08) ; les plus anciennes sont dans un fichier ZIP historique non lu "
            "ici. establishment et address correspondent à des mots entiers du nom et de "
            "l'adresse.",
        ),
    )

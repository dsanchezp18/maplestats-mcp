"""MCP tools for City of Toronto open data (open.toronto.ca DataStore tables)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.toronto import client
from maplestats_mcp.modules.toronto.constants import ROWS_DEFAULT
from maplestats_mcp.modules.toronto.schemas import (
    ApartmentEvaluations,
    ApartmentScoreSummary,
    InspectionSearch,
    NeighbourhoodProfile,
    ShortTermRentalSummary,
)

Lang = Literal["en", "fr"]


@tool
async def toronto_get_neighbourhood_profile(
    neighbourhood: str,
    topic: str | None = None,
    characteristic: str | None = None,
    census_year: Literal[2016, 2011, 2006, 2001] = 2016,
    limit: int = ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> NeighbourhoodProfile:
    """Get one neighbourhood's indicators from the City of Toronto's Neighbourhood Profiles.

    Use for: a named neighbourhood of the City's 140 ("Annex", "Regent
    Park", "Thorncliffe Park") or its number ("95"): population, age,
    renters and owners, income, languages, education and commuting, beside
    the city total, as the City compiled them from the 2016, 2011, 2006 or
    2001 census (2,383 indicators in 2016). `topic` keeps topics whose name
    contains it ("Household characteristics"; the response lists every
    topic), `characteristic` keeps labels containing it ("Renter"). Rows:
    label, level in the hierarchy, value as published and as a number, city
    value, census product. The 2021 profiles (158 neighbourhoods) are an
    Excel file and are not read; for a municipality, CMA or census tract use
    statcan_census_profile_get_data. English only.
    Keywords: neighbourhood profile, neighbourhood, neighbourhoods, 140
    neighbourhoods, Neighbourhood Profiles, neighbourhood indicators, Annex,
    Regent Park, open.toronto.ca.
    Mots-clés : profil de quartier, quartier, quartiers, 140 quartiers,
    profils de quartier, indicateurs de quartier, Regent Park,
    open.toronto.ca.
    """
    return await client.get_neighbourhood_profile(
        neighbourhood,
        topic=topic,
        characteristic=characteristic,
        census_year=census_year,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def toronto_get_apartment_evaluations(
    ward: str | None = None,
    address: str | None = None,
    latest_only: bool = True,
    sort: Literal["score_asc", "score_desc", "date_desc", "address"] = "score_asc",
    limit: int = ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> ApartmentEvaluations:
    """List RentSafeTO apartment building evaluation scores, by ward or address.

    Use for: which apartment buildings score lowest (or highest) on
    RentSafeTO, the City of Toronto's bylaw evaluation of rental buildings
    with 3+ storeys or 10+ units; one building's score and evaluation date
    by address ("263 PHARMACY AVE"); every evaluated building in a ward
    (ward number "5" or name "York South-Weston"). Each row: registration
    number (RSN), address, ward, private / TCHC / social housing, year
    built, storeys, units, evaluation date, score out of 100 with its
    proactive and reactive parts, coordinates. `latest_only` (default)
    keeps each building's most recent evaluation; false lists every
    evaluation since 2023. Worst score first by default. English only.
    Keywords: RentSafeTO, apartment building evaluation, building score,
    apartment standards, landlord, tenant, ward, TCHC.
    Mots-clés : RentSafeTO, évaluation des immeubles d'appartements, note
    d'immeuble, normes des immeubles, propriétaire, locataires, quartier
    électoral, TCHC.
    """
    return await client.get_apartment_evaluations(
        ward=ward,
        address=address,
        latest_only=latest_only,
        sort=sort,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def toronto_summarize_apartment_scores(
    group_by: Literal["ward", "property_type"] = "ward",
    evaluated_since: int | None = None,
    lang: Lang = "en",
) -> ApartmentScoreSummary:
    """Summarize RentSafeTO apartment building scores by ward or property type.

    Use for: comparing the City of Toronto's 25 wards (or private, TCHC and
    social housing buildings) on RentSafeTO evaluation scores: buildings,
    units, mean, median, 25th percentile, lowest and highest score, plus
    all buildings together. Each building counts once, at its latest
    evaluation since 2023; `evaluated_since` (a year) drops buildings last
    evaluated earlier. toronto_get_apartment_evaluations lists the
    buildings behind a group. English only.
    Keywords: RentSafeTO, apartment scores by ward, building evaluation
    summary, apartment building quality, wards, TCHC, average score,
    landlord.
    Mots-clés : RentSafeTO, notes des immeubles par quartier électoral,
    résumé des évaluations, qualité des immeubles d'appartements, quartiers
    électoraux, TCHC, note moyenne, propriétaires.
    """
    return await client.summarize_apartment_scores(
        group_by=group_by, evaluated_since=evaluated_since, lang=lang
    )


@tool
async def toronto_summarize_short_term_rentals(
    group_by: Literal["ward", "property_type", "postal_code"] = "ward",
    lang: Lang = "en",
) -> ShortTermRentalSummary:
    """Count registered short-term rentals by ward, property type or postal area (Toronto).

    Use for: how many short-term rentals (Airbnb-style listings registered
    with the City of Toronto) there are and where: counts and shares by
    ward (25 wards), property type (condominium, house, townhouse...) or
    forward sortation area ("M5A"), from the City's registration table,
    refreshed daily. A registration is not a booking. Counts only;
    operators' registration numbers and addresses are not returned.
    English only.
    Keywords: short-term rental, short-term rentals, Airbnb, STR
    registration, vacation rental, registrations by ward, FSA, listings.
    Mots-clés : location à court terme, locations à court terme, Airbnb,
    inscription, location de vacances, inscriptions par quartier, RTA,
    annonces.
    """
    return await client.summarize_short_term_rentals(group_by=group_by, lang=lang)


@tool
async def toronto_search_dinesafe(
    establishment: str | None = None,
    address: str | None = None,
    status: Literal["Pass", "Conditional Pass", "Closed"] | None = None,
    limit: int = ROWS_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> InspectionSearch:
    """Search DineSafe restaurant and food premises inspections (Toronto), newest first.

    Use for: a restaurant's inspection history by name words ("pizza",
    "tim hortons") or address words ("Queen St W"); recent closures
    (`status` "Closed") or conditional passes. One row per infraction:
    date, Pass / Conditional Pass / Closed, severity (minor, significant,
    crucial), infraction and deficiency text, court outcome and fine,
    coordinates. Toronto Public Health's DineSafe table keeps recent
    inspections only. English only.
    Keywords: DineSafe, restaurant inspection, food safety, public health
    inspection, closed restaurant, infraction, fine, food premises.
    Mots-clés : DineSafe, inspection des restaurants, salubrité
    alimentaire, inspection de santé publique, restaurant fermé,
    infraction, amende, établissement alimentaire.
    """
    return await client.search_dinesafe(
        establishment=establishment,
        address=address,
        status=status,
        limit=limit,
        offset=offset,
        lang=lang,
    )

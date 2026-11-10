"""MCP tools for CMHC's Housing Market Information Portal (HMIP).

Every tool returns a typed Pydantic model (see schemas.py) - FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

Unlike most modules in this project, `lang` is NOT a no-op here:
confirmed live, HMIP's `/en/`/`/fr/` path prefix genuinely changes the
category taxonomy's own text (e.g. "Primary Rental Market" vs "Marché
locatif primaire" as the literal `category_level_1` value to pass into
other tools), while the numeric ids (`table_id`, province `id`, etc.)
stay identical across languages.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cmhc import client
from maplestats_mcp.modules.cmhc.schemas import (
    CategoryList,
    CmhcSurvey,
    MethodologyResult,
    MetroAreaList,
    ProvinceList,
    TableDataResult,
    TableOptions,
)

Lang = Literal["en", "fr"]


@tool
async def cmhc_list_categories(
    geography_type: str = "Country", geography_id: str = "1", lang: Lang = "en"
) -> CategoryList:
    """List CMHC housing-data categories available at a geography.

    Use for: discovering what CMHC covers before requesting data - new
    housing construction (housing starts / mises en chantier, and
    completions / achèvements), primary and secondary
    rental market (vacancy rates, rents), seniors' rental housing,
    population/households/housing stock, and core housing need. Read
    docs://cmhc/well-known-categories first - it already lists the
    common categories with their exact spelling.
    `geography_type`/`geography_id` default to "Country"/"1" (Canada);
    pass geography_type="Province" with an id from cmhc_list_provinces,
    or geography_type="MetropolitanMajorArea" ("CMA" also works) with an
    id from cmhc_list_metropolitan_areas (Toronto is "2270"; the name
    "Toronto" is accepted too). Category names are language-dependent strings
    (not fixed codes) - the values this returns for lang="fr" must be
    passed back with lang="fr" to other cmhc_ tools.
    Keywords: cmhc, housing, hmip, category, discover, rental market,
    vacancy rate, rent, housing starts, completions, seniors housing,
    core housing need, mortgage, corporation.
    Mots-clés : Société canadienne d'hypothèques et de logement (SCHL),
    logement, Portail de l'information sur le marché de l'habitation (PIMH),
    catégorie, découvrir, marché locatif, taux d'inoccupation, loyer, mises
    en chantier, achèvements, logements pour personnes âgées, besoins
    impérieux, hypothèque.
    """
    return await client.list_categories(
        geography_type=geography_type, geography_id=geography_id, lang=lang
    )


@tool
async def cmhc_get_table_options(
    category_level_1: str,
    category_level_2: str,
    geography_type: str = "Country",
    geography_id: str = "1",
    lang: Lang = "en",
) -> TableOptions:
    """Get the valid breakdown options for a CMHC category before requesting data.

    Use for: finding which `column_field`/`row_field` pairs
    cmhc_get_table_data will accept for a given category (e.g. "Bedroom
    Type" vs "Year of Construction" as the column breakdown, "Historical
    Time Periods" for a time series vs "Provinces" for a current
    cross-tabulation) - a category/geography this doesn't return an
    option for will not resolve in cmhc_get_table_data either.
    Keywords: cmhc, housing, hmip, table options, column field, row
    field, breakdown, bedroom type, time series, historical, provinces,
    discover, housing starts.
    Mots-clés : Société canadienne d'hypothèques et de logement (SCHL),
    logement, Portail de l'information sur le marché de l'habitation (PIMH),
    options de tableau, champ colonne, champ ligne, répartition, type de
    chambre, série chronologique, historique, provinces, découvrir, mises en
    chantier.
    """
    return await client.get_table_options(
        category_level_1,
        category_level_2,
        geography_type=geography_type,
        geography_id=geography_id,
        lang=lang,
    )


@tool
async def cmhc_list_provinces(lang: Lang = "en") -> ProvinceList:
    """List Canadian provinces/territories with their CMHC HMIP geography id.

    Use for: getting a `geography_id` (with `geography_type="Province"`)
    to pass to cmhc_list_categories/cmhc_get_table_options/
    cmhc_get_table_data for province-level data instead of national
    Canada-wide data. For a city or CMA use cmhc_list_metropolitan_areas.
    Keywords: cmhc, housing, hmip, province, territory, geography,
    geography id, list, canada.
    Mots-clés : Société canadienne d'hypothèques et de logement (SCHL),
    logement, Portail de l'information sur le marché de l'habitation (PIMH),
    province, territoire, géographie, identifiant géographique, liste,
    Canada.
    """
    return await client.list_provinces(lang=lang)


@tool
async def cmhc_list_metropolitan_areas(
    province_id: str | None = None, name: str | None = None, lang: Lang = "en"
) -> MetroAreaList:
    """List CMHC's metropolitan areas (CMAs, census agglomerations, centres) with their id.

    Use for: getting the `geography_id` of a city or CMA to pass with
    `geography_type="MetropolitanMajorArea"` to cmhc_list_categories,
    cmhc_get_table_options and cmhc_get_table_data, for city-level rents,
    vacancy rates and housing starts. `name` keeps the areas whose name
    contains that word; `province_id`
    (an id or name from cmhc_list_provinces) keeps one province. Without
    either, every province is read (a few seconds the first time, then
    cached a day). Ids are text and some start with zero ("0120" is Barrie): pass
    them as returned.
    Keywords: cmhc, housing, hmip, cma, census metropolitan area, city,
    metropolitan area, centre, geography id, average rent, vacancy rate.
    Mots-clés : Société canadienne d'hypothèques et de logement (SCHL),
    logement, Portail de l'information sur le marché de l'habitation (PIMH),
    région métropolitaine de recensement (RMR), agglomération de
    recensement, ville, centre, identifiant géographique, loyer, taux
    d'inoccupation.
    """
    return await client.list_metropolitan_areas(province_id=province_id, name=name, lang=lang)


@tool
async def cmhc_get_table_data(
    category_level_1: str,
    category_level_2: str,
    column_field: str,
    row_field: str,
    geography_type: str = "Country",
    geography_id: str = "1",
    filters: dict[str, str] | None = None,
    aggregate: Literal["annual", "ytd"] | None = None,
    lang: Lang = "en",
) -> TableDataResult:
    """Get CMHC housing data for a category as a table (time series, cross-tab, or annual totals).

    Use for: fetching actual CMHC Rental Market Survey vacancy rates/
    rents, housing starts/completions (mises en chantier, achèvements),
    seniors' rental housing data, or
    any other category's numeric data - e.g. national historical rental
    vacancy rates by bedroom type, or current vacancy rates broken down
    by province, or a city's average rent by bedroom type
    (geography_type="MetropolitanMajorArea", geography_id from
    cmhc_list_metropolitan_areas, or its name: "Toronto"). Pass `row_field="TIMESERIES"` for a historical time
    series (one row per period) or a province/centre-breakdown field
    from cmhc_get_table_options for a current cross-tabulation (one row
    per province/centre, then a total row for the requested geography,
    labelled with its name, e.g. "Canada"); `reference_period` dates it
    ("October 2025"). Each returned cell carries CMHC's own
    reliability flag (a/b/c/d = Excellent/Very good/Good/Poor, use with
    caution) alongside the value, `value: 0` where CMHC prints "-" (no
    units in the universe), or `value: null` with the raw marker in
    `flag` when data were suppressed ("**"), not applicable ("n/a") or a
    rent change was not significant ("++"). `flag_legend` explains every
    flag the result carries; cmhc_get_methodology has the survey's timing,
    scope, definitions and CMHC's release rules. `category_level_1`/
    `category_level_2`/`column_field`/`row_field` must come from
    cmhc_list_categories/cmhc_get_table_options first - an unrecognized
    combination raises a clear error rather than guessing. Labels
    ("Bedroom Type", "Historical Time Periods") are accepted for the
    codes, and the same column label works across a category's tables
    (Average Rent ($) and % Change of Average Rent); a wrong one is
    refused with every valid label and code. The result's
    `available_filters` lists extra narrowing dimensions this
    particular table supports beyond column_field/row_field (e.g.
    `season`: April/October, `dwelling_type_desc_en`: Row/Apartment for
    a Rental Market Survey table) - these genuinely change the returned
    values, not just a label; pass a subset as `filters` (e.g.
    `{"dwelling_type_desc_en": "Apartment"}`) to narrow to that slice.
    Without one, CMHC applies its own default (Rental Market Survey
    rents and vacancy rates: "Row / Apartment", both structure types
    combined); `applied_filters`, `default_filters` and `filter_notes`
    say which values the figures are for. An unrecognized filter
    key/value raises a clear error rather than being silently ignored.
    `aggregate="annual"` (calendar-year totals) or `"ytd"` (January to
    the latest month, every year) sums a monthly flow time series -
    housing starts (actual), completions, absorbed units, with
    row_field="TIMESERIES" - server-side; `aggregation_note` says the
    sums are MapleStats', not CMHC's. Stocks, rates (SAAR), prices and
    rental values are refused, never summed.
    Keywords: cmhc, housing, hmip, rental market, vacancy rate, rent,
    average rent, housing starts, completions, time series, historical,
    data, table, province, bedroom type, reliability flag, filter,
    dwelling type, season, annual total, year to date.
    Mots-clés : Société canadienne d'hypothèques et de logement (SCHL),
    logement, Portail de l'information sur le marché de l'habitation (PIMH),
    marché locatif, taux d'inoccupation, loyer, loyers, loyer moyen, mises en
    chantier, achèvements, série chronologique, historique, données,
    tableau, province, type de chambre, indicateur de fiabilité, filtre,
    type de logement, saison, total annuel, cumul annuel.
    """
    return await client.get_table_data(
        category_level_1,
        category_level_2,
        column_field,
        row_field,
        geography_type=geography_type,
        geography_id=geography_id,
        filters=filters,
        aggregate=aggregate,
        lang=lang,
    )


@tool
async def cmhc_get_methodology(
    survey: CmhcSurvey = "rental_market", lang: Lang = "en"
) -> MethodologyResult:
    """CMHC survey methodology and definitions: reliability codes, absorbed, sold, starts.

    Use for: what a CMHC term or code means, from CMHC's own methodology
    pages, before answering from memory. survey="rental_market": the Rental
    Market Survey (October timing, scope of private structures of 3+ units,
    vacant, available, turnover, average rent, same-sample rent change, the
    a/b/c/d reliability codes and their CV thresholds, ** suppression, the
    release rule of 4 or more responding entities, the secondary rental
    market). survey="starts_completions_absorption": the Starts and
    Completions Survey and the Market Absorption Survey (which centres are
    surveyed and how often, what counts as a start, under construction or a
    completion, an absorbed unit (sold and completed), when a unit counts as
    sold, unabsorbed units, prices, SAAR, dwelling types, intended markets).
    Answers from text kept in this server, read from CMHC's pages on the date
    in read_on; cite source_urls.
    Keywords: CMHC methodology, definition, reliability code, data quality,
    coefficient of variation, suppressed, responding entities, RMS
    methodology, vacancy definition, Market Absorption Survey, absorbed units,
    unabsorbed inventory, sold, housing starts definition, completions, SAAR.
    Mots-clés : méthodologie de la SCHL, définition, code de fiabilité,
    qualité des données, coefficient de variation, donnée supprimée, entités
    répondantes, méthodologie de l'ELL, définition de l'inoccupation,
    Enquête sur l'écoulement des logements, logements écoulés, non écoulés,
    vendu, mises en chantier, achèvements, DTA.
    """
    return client.get_methodology(survey, lang=lang)

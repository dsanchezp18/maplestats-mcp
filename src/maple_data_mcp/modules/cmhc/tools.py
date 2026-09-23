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

from maple_data_mcp.modules.cmhc import client
from maple_data_mcp.modules.cmhc.schemas import (
    CategoryList,
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
    housing construction (starts/completions), primary and secondary
    rental market (vacancy rates, rents), seniors' rental housing,
    population/households/housing stock, and core housing need. Read
    docs://cmhc/well-known-categories first - it already lists the
    common categories with their exact spelling.
    `geography_type`/`geography_id` default to "Country"/"1" (Canada);
    pass a province id from cmhc_list_provinces for province-level
    categories instead. Category names are language-dependent strings
    (not fixed codes) - the values this returns for lang="fr" must be
    passed back with lang="fr" to other cmhc_ tools.
    Keywords: cmhc, housing, hmip, category, discover, rental market,
    vacancy rate, rent, housing starts, completions, seniors housing,
    core housing need, mortgage, corporation.
    Mots-clés : schl, logement, pimh, catégorie, découvrir, marché
    locatif, taux d'inoccupation, loyer, mises en chantier,
    achèvements, logements pour personnes âgées, besoins impérieux,
    hypothèque, société.
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
    discover.
    Mots-clés : schl, logement, pimh, options de tableau, champ colonne,
    champ ligne, répartition, type de chambre, série chronologique,
    historique, provinces, découvrir.
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
    Canada-wide data. CMA/city-level geography is not yet supported by
    this module - only Canada and provinces.
    Keywords: cmhc, housing, hmip, province, territory, geography,
    geography id, list, canada.
    Mots-clés : schl, logement, pimh, province, territoire, géographie,
    identifiant géographique, liste, canada.
    """
    return await client.list_provinces(lang=lang)


@tool
async def cmhc_get_table_data(
    category_level_1: str,
    category_level_2: str,
    column_field: str,
    row_field: str,
    geography_type: str = "Country",
    geography_id: str = "1",
    filters: dict[str, str] | None = None,
    lang: Lang = "en",
) -> TableDataResult:
    """Get CMHC housing data for a category as a table (time series or cross-tab).

    Use for: fetching actual CMHC Rental Market Survey vacancy rates/
    rents, housing starts/completions, seniors' rental housing data, or
    any other category's numeric data - e.g. national historical rental
    vacancy rates by bedroom type, or current vacancy rates broken down
    by province. Pass `row_field="TIMESERIES"` for a historical time
    series (one row per period) or a province/centre-breakdown field
    from cmhc_get_table_options for a current cross-tabulation (one row
    per province/centre). Each returned cell carries CMHC's own
    reliability flag (a/b/c/d = Excellent/Very good/Good/Poor) alongside
    the value, `value: 0` for a real, counted zero (flagged "-" by
    CMHC), or `value: null` with the raw marker in `flag` when data was
    suppressed ("**"/"n/a") or not applicable ("++") - see
    docs://cmhc/gotchas for the full legend. `category_level_1`/
    `category_level_2`/`column_field`/`row_field` must come from
    cmhc_list_categories/cmhc_get_table_options first - an unrecognized
    combination raises a clear error rather than guessing. The result's
    `available_filters` lists extra narrowing dimensions this
    particular table supports beyond column_field/row_field (e.g.
    `season`: April/October, `dwelling_type_desc_en`: Row/Apartment for
    a Rental Market Survey table) - these genuinely change the returned
    values, not just a label; pass a subset as `filters` (e.g.
    `{"dwelling_type_desc_en": "Row"}`) on a follow-up call to narrow
    to just that slice. An unrecognized filter key/value raises a clear
    error rather than being silently ignored.
    Keywords: cmhc, housing, hmip, rental market, vacancy rate, rent,
    average rent, housing starts, completions, time series, historical,
    data, table, province, bedroom type, reliability flag, filter,
    dwelling type, season.
    Mots-clés : schl, logement, pimh, marché locatif, taux
    d'inoccupation, loyer, loyer moyen, mises en chantier, achèvements,
    série chronologique, historique, données, tableau, province, type
    de chambre, indicateur de fiabilité, filtre, type de logement,
    saison.
    """
    return await client.get_table_data(
        category_level_1,
        category_level_2,
        column_field,
        row_field,
        geography_type=geography_type,
        geography_id=geography_id,
        filters=filters,
        lang=lang,
    )

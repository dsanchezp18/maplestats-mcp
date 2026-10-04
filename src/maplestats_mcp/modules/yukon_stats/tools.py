"""MCP tools for the Yukon Bureau of Statistics."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.yukon_stats import client, constants
from maplestats_mcp.modules.yukon_stats.schemas import TableList, TableRows

Lang = Literal["en", "fr"]


@tool
async def yukon_stats_list_tables(
    query: str | None = None,
    dataset: str | None = None,
    limit: int = constants.TABLES_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> TableList:
    """List the CSV tables of the Yukon Bureau of Statistics (about 100, incl. three Census profiles).

    Use for: finding a Yukon statistics table (population estimates by age
    and sex, median age, vital statistics, rent and vacancy rates, building
    permits, fuel prices, community spatial price index, Whitehorse real
    estate, aircraft movements, businesses and workers, employment insurance
    benefits, crime, school enrolment, 2011/2016/2021 Census profile tables)
    and its URL for yukon_stats_query_table. `query` keeps tables whose title
    or dataset contains every word; `dataset` matches a dataset name or title
    (e.g. economic-statistics, demographic-statistics, census-2021).
    Keywords: Yukon, Bureau of Statistics, Whitehorse, population, rent,
    vacancy, building permits, fuel prices, census, community, territory,
    CSV.
    Mots-clés : Yukon, Bureau de la statistique du Yukon, Whitehorse,
    estimations de la population, âge médian, loyer médian, taux
    d'inoccupation, permis de bâtir, permis de construire, prix de
    l'essence, prix des carburants, indice spatial des prix, immobilier,
    assurance-emploi, criminalité, effectifs scolaires, profil du
    recensement, collectivité, territoire, tableaux CSV.
    """
    return await client.list_tables(query=query, dataset=dataset, limit=limit, lang=lang)


@tool
async def yukon_stats_query_table(
    url: str,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> TableRows:
    """Read rows of a Yukon Bureau of Statistics CSV table, filtered and with chosen columns.

    Use for: getting Yukon figures such as monthly population by age and sex,
    median rent and vacancy by community, building permit values, fuel
    prices by community, or a Census 2021 profile table. `url` must be a
    table URL exactly as yukon_stats_list_tables gives it (other URLs are
    refused, since the portal would serve a table by its resource id under
    any file name). `filters` are exact, case-insensitive matches
    on column values (for example {"region": "Whitehorse", "year": "2025"});
    `columns` picks and orders the columns. Rows are text. The long
    'footnotes' column is dropped and other cells are cut at 300 characters.
    The first read of a large file can take a while (the portal asks for a
    10 second pause between requests); later reads use the cache. Open
    Government Licence - Yukon.
    Keywords: Yukon, Bureau of Statistics, rows, filter, population, rent,
    vacancy, permits, prices, census, Whitehorse, community, monthly.
    Mots-clés : Yukon, Bureau de la statistique du Yukon, lire un tableau,
    lignes, filtrer, population par âge et sexe, loyer médian, taux
    d'inoccupation, valeur des permis de bâtir, prix
    des carburants, profil du recensement 2021, Whitehorse, collectivité,
    données mensuelles.
    """
    return await client.query_table(
        url=url, filters=filters, columns=columns, limit=limit, offset=offset, lang=lang
    )

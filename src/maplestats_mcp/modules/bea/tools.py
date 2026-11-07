"""MCP tools for the US Bureau of Economic Analysis Data API.

bea_get_nipa (GDP, personal income, PCE prices), bea_get_regional (states and
counties) and bea_get_international_transactions (US trade with Canada) are
the data tools; bea_list_datasets and bea_list_parameter_values find tables,
lines and indicator codes. Every tool needs the server's MAPLE_BEA_API_KEY.
BEA publishes in English; `lang="fr"` gives this server's own text in French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bea import client
from maplestats_mcp.modules.bea.schemas import DataResult, DatasetList, ParameterValueList

Lang = Literal["en", "fr"]


@tool
async def bea_get_nipa(
    table: str = "T10101",
    frequency: str = "Q",
    years: list[int] | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get a US national accounts (NIPA) table from the Bureau of Economic Analysis.

    Use for: the American side of a comparison of GDP, growth, personal
    income or consumer prices with Canada: US real GDP growth (table
    T10101, percent change at annual rates), US GDP in current dollars
    (T10105), real GDP (T10106), year-over-year real GDP growth (T10111),
    personal income and saving (T20100, monthly T20600), PCE price
    indexes (T20804), exports and imports (T40100). `frequency` is A, Q
    or M (comma list allowed); `years` defaults to the last 5. Rows carry
    line, series code, unit, multiplier and notes. Other table names:
    bea_list_parameter_values(dataset="NIPA", parameter="TableName").
    Keywords: BEA, Bureau of Economic Analysis, US GDP, United States
    economic growth, NIPA, national income and product accounts, US
    personal income, PCE price index, US saving rate, American economy.
    Mots-clés : BEA, PIB américain, croissance économique des États-Unis,
    comptes nationaux américains, NIPA, revenu personnel américain, indice
    des prix PCE, taux d'épargne américain, économie américaine.
    """
    return await client.get_nipa(table, frequency=frequency, years=years, lang=lang)


@tool
async def bea_get_regional(
    table: str = "SAINC1",
    line_code: str = "1",
    geo_fips: str = "STATE",
    years: list[int] | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get US state, county or metro area income and GDP from the Bureau of Economic Analysis.

    Use for: comparing a Canadian province with US states (or border
    states such as Washington, Michigan, New York) on personal income,
    per capita income, population or GDP. `table` is a Regional table:
    SAINC1 (state personal income summary: line 1 personal income, 2
    population, 3 per capita income), SAGDP2 (GDP by state), SQINC1
    (quarterly), CAINC1 (counties), SARPP (regional price parities).
    `geo_fips` is STATE, COUNTY, MSA, a state code (53000 for Washington)
    or a comma list; `years` defaults to the last 5. Line codes for a
    table: bea_list_parameter_values(dataset="Regional",
    parameter="LineCode", filters={"TableName": "SAINC1"}).
    Keywords: BEA, US states, state personal income, per capita income
    by state, state GDP, county income, metropolitan areas, regional
    economic accounts, border states, American states.
    Mots-clés : BEA, États américains, revenu personnel par État, revenu
    par habitant des États, PIB des États, revenu des comtés, régions
    métropolitaines, comptes économiques régionaux, États frontaliers.
    """
    return await client.get_regional(
        table, line_code=line_code, geo_fips=geo_fips, years=years, lang=lang
    )


@tool
async def bea_get_international_transactions(
    indicators: list[str] | None = None,
    area_or_country: str = "Canada",
    frequency: str = "QSA",
    years: list[int] | None = None,
    lang: Lang = "en",
) -> DataResult:
    """Get US international transactions with Canada (or another country) from the BEA.

    Use for: US exports to, imports from and trade balance with Canada in
    goods, services, or both, on a balance-of-payments basis in US
    dollars, quarterly seasonally adjusted (QSA), not adjusted (QNSA) or
    annual (A). Default indicators: ExpGdsServ, ImpGdsServ, BalGdsServ,
    ExpGds, ImpGds, BalGds, ExpServ, ImpServ, BalServ; other codes come
    from bea_list_parameter_values(dataset="ITA", parameter="Indicator").
    `area_or_country` is a BEA name (Canada, Mexico, China, EuropeanUnion,
    AllCountries). `years` defaults to the last 5. For Canada's own
    customs-basis trade by commodity use the cimt_ tools.
    Keywords: BEA, international transactions, US trade with Canada,
    Canada US trade balance, US exports to Canada, US imports from Canada,
    trade in services, balance of payments, current account, ITA.
    Mots-clés : BEA, transactions internationales, commerce
    États-Unis-Canada, balance commerciale avec les États-Unis,
    exportations américaines vers le Canada, importations américaines,
    commerce des services, balance des paiements, compte courant.
    """
    return await client.get_international_transactions(
        indicators,
        area_or_country=area_or_country,
        frequency=frequency,
        years=years,
        lang=lang,
    )


@tool
async def bea_list_datasets(lang: Lang = "en") -> DatasetList:
    """List the US Bureau of Economic Analysis API datasets.

    Use for: which BEA dataset holds a US statistic before listing its
    parameters: NIPA (national accounts), NIUnderlyingDetail, FixedAssets,
    GDPbyIndustry, Regional (states, counties, metros), ITA (international
    transactions), IIP (international investment position), IntlServTrade
    (services trade), MNE (multinational enterprises), InputOutput.
    Keywords: BEA, Bureau of Economic Analysis, datasets, US economic
    accounts, national accounts, regional accounts, international
    accounts, GDP by industry, input-output, data catalogue.
    Mots-clés : BEA, jeux de données, comptes économiques américains,
    comptes nationaux, comptes régionaux, comptes internationaux, PIB par
    industrie, entrées-sorties, catalogue de données.
    """
    return await client.list_datasets(lang=lang)


@tool
async def bea_list_parameter_values(
    dataset: str,
    parameter: str,
    filters: dict[str, str] | None = None,
    lang: Lang = "en",
) -> ParameterValueList:
    """List the valid values of a BEA dataset parameter: table names, line codes, indicators.

    Use for: finding a BEA table, line or code before fetching data: NIPA
    TableName (every national accounts table), Regional TableName or
    LineCode (with filters={"TableName": "SAINC1"}), Regional GeoFips, ITA
    Indicator or AreaOrCountry, IntlServTrade TypeOfService. `filters`
    narrows the values to those valid with other parameters
    (GetParameterValuesFiltered, supported by Regional and some others).
    Keywords: BEA, parameter values, table names, line codes, indicator
    codes, NIPA tables, regional tables, country codes, GeoFips, BEA
    metadata.
    Mots-clés : BEA, valeurs des paramètres, noms de tableaux, codes de
    ligne, codes d'indicateur, tableaux NIPA, tableaux régionaux, codes de
    pays, métadonnées du BEA.
    """
    return await client.list_parameter_values(dataset, parameter, filters=filters, lang=lang)

"""MCP tools for the European Central Bank Data Portal.

ecb_get_indicator is the Canada-centred entry point: ECB key rates, €STR,
the euro against the Canadian and US dollars, euro area inflation, money,
credit and yields, each with the Canadian series to set beside it.
ecb_list_datasets, ecb_describe_dataset, ecb_search_series and
ecb_get_series reach any series of the ECB's datasets by SDMX key. The ECB
publishes in English only; `lang="fr"` gives this server's own text in
French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.ecb import client
from maplestats_mcp.modules.ecb.schemas import (
    DatasetList,
    DatasetStructure,
    SeriesData,
    SeriesList,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "deposit_facility_rate",
    "main_refinancing_rate",
    "marginal_lending_rate",
    "estr",
    "eur_cad",
    "eur_cad_monthly",
    "eur_usd",
    "hicp_inflation",
    "hicp_core_inflation",
    "m3_growth",
    "household_loan_growth",
    "mortgage_rate",
    "euro_area_10y_yield",
]


@tool
async def ecb_get_indicator(
    indicator: IndicatorName,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesData:
    """Get a European Central Bank headline series to compare with Canada.

    Use for: the ECB deposit facility, main refinancing and marginal
    lending rates beside the Bank of Canada's policy rate, €STR beside
    CORRA, the euro in Canadian dollars (EUR/CAD reference rate) or US
    dollars, euro area HICP inflation (headline and core), M3 growth,
    household loan growth, mortgage rates and the euro area 10-year
    yield. Each result names the Canadian series to set beside it.
    Periods are `2024`, `2024-Q1`, `2024-06` or `2024-06-30`; without
    them the latest values come back (the last 10 changes for key rates).
    Rows are tidy: date, value, unit, frequency, series id.
    Keywords: European Central Bank, ECB, euro area, eurozone, ECB
    interest rates, deposit facility rate, EUR/CAD exchange rate, euro
    reference rate, HICP inflation, comparison with Canada.
    Mots-clés : Banque centrale européenne, BCE, zone euro, taux
    directeurs de la BCE, taux de la facilité de dépôt, taux de change
    euro dollar canadien, taux de référence de l'euro, inflation IPCH,
    comparaison avec le Canada.
    """
    return await client.get_indicator(
        indicator, start_period=start_period, end_period=end_period, last_n=last_n, lang=lang
    )


@tool
async def ecb_list_datasets(query: str | None = None, lang: Lang = "en") -> DatasetList:
    """List the European Central Bank's statistical datasets (dataflows).

    Use for: finding which ECB dataset holds a series before describing
    it: exchange rates (EXR), financial market data and key rates (FM),
    €STR (EST), consumer prices (HICP), monetary aggregates and bank
    balance sheets (BSI), bank interest rates (MIR), the yield curve (YC),
    the Bank Lending Survey, property prices, the Survey of Professional
    Forecasters, balance of payments and government finance. `query`
    keeps datasets whose name or description has every word.
    Keywords: ECB, European Central Bank, datasets, dataflows, SDMX, ECB
    Data Portal, euro area statistics, catalogue.
    Mots-clés : BCE, Banque centrale européenne, jeux de données, flux
    SDMX, portail de données de la BCE, statistiques de la zone euro,
    catalogue, liste des jeux.
    """
    return await client.list_datasets(query=query, lang=lang)


@tool
async def ecb_describe_dataset(
    dataset: str, code_query: str | None = None, lang: Lang = "en"
) -> DatasetStructure:
    """Describe an ECB dataset's dimensions and codes, to build a series key.

    Use for: the order of an ECB dataset's key dimensions and the codes
    each may take (frequencies, areas, currencies, instruments, units),
    before calling ecb_search_series or ecb_get_series. `dataset` is an id
    from ecb_list_datasets (e.g. EXR); `code_query` keeps codes whose id
    or label has the words (e.g. "Canadian dollar").
    Keywords: ECB, dataset structure, dimensions, code list, series key,
    SDMX key, data structure definition, codes, metadata.
    Mots-clés : BCE, structure du jeu de données, dimensions, liste de
    codes, clé de série, clé SDMX, définition de structure, métadonnées.
    """
    return await client.describe_dataset(dataset, code_query=code_query, lang=lang)


@tool
async def ecb_search_series(
    dataset: str,
    key: str = "",
    query: str | None = None,
    limit: int = 50,
    lang: Lang = "en",
) -> SeriesList:
    """List the series of an ECB dataset that match a key and title words.

    Use for: finding the exact ECB series key: every euro reference rate
    (EXR key `D..EUR.SP00.A`), the HICP items for the euro area (HICP key
    `M.U2.N..4D0.ANR`), a bank interest rate. `key` has one part per
    dimension (empty or `*` for all, codes joined by `+`); empty lists
    the whole dataset. `query` keeps series whose title has every word
    (English, e.g. "Canadian dollar", "services").
    Keywords: ECB, series search, series key, find series, series titles,
    euro area series, SDMX, ECB Data Portal.
    Mots-clés : BCE, recherche de séries, clé de série, trouver une série,
    titres des séries, séries de la zone euro, portail de données de la
    BCE, SDMX.
    """
    return await client.search_series(dataset, key=key, query=query, limit=limit, lang=lang)


@tool
async def ecb_get_series(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesData:
    """Get ECB time series by dataset and SDMX key, as tidy rows.

    Use for: any ECB series beyond the preset indicators: another
    currency's euro reference rate, a member state's HICP, a bank lending
    rate, a monetary aggregate. `key` has one part per dimension in the
    order ecb_describe_dataset gives, codes joined by `+` (e.g. EXR
    `M.CAD+USD.EUR.SP00.A`). Periods are `2024`, `2024-Q1`, `2024-06` or
    `2024-06-30`; `last_n` keeps the last N per series. The result has a
    csv_url that opens the same query as CSV.
    Keywords: ECB, European Central Bank, time series, SDMX key, euro
    area data, exchange rates, monetary statistics, CSV download.
    Mots-clés : BCE, Banque centrale européenne, séries chronologiques,
    clé SDMX, données de la zone euro, taux de change, statistiques
    monétaires, téléchargement CSV.
    """
    return await client.get_series(
        dataset,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )

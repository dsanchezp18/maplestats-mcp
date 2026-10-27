"""MCP tools for the Bank for International Settlements statistics.

bis_compare_countries is the Canada-centred entry point: a short list of
preset indicators, Canada always first. bis_list_datasets,
bis_describe_dataset and bis_get_series reach any series of the 28 BIS
datasets by SDMX key. The BIS publishes in English only; `lang="fr"` gives
this server's own text (descriptions, notes, errors) in French.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.bis import client
from maplestats_mcp.modules.bis.schemas import (
    ComparisonResult,
    DatasetList,
    DatasetStructure,
    SeriesResult,
)

Lang = Literal["en", "fr"]
IndicatorName = Literal[
    "policy_rate",
    "household_debt_service_ratio",
    "private_debt_service_ratio",
    "credit_to_gdp_gap",
    "household_credit_to_gdp",
    "private_credit_to_gdp",
    "government_debt_to_gdp",
    "real_house_price_growth",
    "nominal_house_price_growth",
    "real_house_price_index",
    "cpi_inflation",
    "real_effective_exchange_rate",
    "nominal_effective_exchange_rate",
]


@tool
async def bis_compare_countries(
    indicator: IndicatorName,
    compare_with: list[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> ComparisonResult:
    """Compare Canada with G7 or other economies on a BIS financial indicator.

    Use for: how Canada's household debt service ratio, credit-to-GDP gap,
    household or government debt as a share of GDP, real house price
    growth, policy rate, inflation or effective exchange rate compares
    with the United States, the United Kingdom, Australia, the euro area
    or the G7. `indicator` is one of the preset names; Canada is always
    first. `compare_with` takes "G7", "EURO_AREA" or two-letter BIS area
    codes ("US", "GB", "AU", "NZ", "SE", "NO"). Periods are SDMX
    (`2020`, `2020-Q1`, `2020-01`); without them the last 5 years come
    back. The result gives Canada's rank (1 = highest) in the period most
    of them report. Bank of Canada Valet and StatCan are better for
    Canada's own latest figures.
    Keywords: BIS, Bank for International Settlements, international
    comparison, debt service ratio, household debt, credit-to-GDP gap,
    house prices, policy rates, central banks, G7, peer countries,
    effective exchange rate.
    Mots-clés : BRI, Banque des règlements internationaux, comparaison
    internationale, ratio du service de la dette, endettement des ménages,
    écart crédit/PIB, prix des logements, taux directeurs, banques
    centrales, pays du G7, taux de change effectif.
    """
    return await client.compare_countries(
        indicator,
        compare_with=compare_with,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )


@tool
async def bis_list_datasets(lang: Lang = "en") -> DatasetList:
    """List the Bank for International Settlements statistical datasets.

    Use for: finding which BIS dataset holds a series before describing it
    and fetching it: central bank policy rates (WS_CBPOL), debt service
    ratios (WS_DSR), total credit (WS_TC), credit-to-GDP gaps
    (WS_CREDIT_GAP), residential and commercial property prices (WS_SPP,
    WS_DPP, WS_CPP), consumer prices (WS_LONG_CPI), exchange rates
    (WS_EER, WS_XRU), international banking (WS_LBS_D_PUB, WS_CBS_PUB),
    debt securities, derivatives and CPMI payment statistics.
    Keywords: BIS, Bank for International Settlements, datasets,
    dataflows, SDMX, international banking statistics, payment
    statistics, CPMI, derivatives, debt securities, global liquidity.
    Mots-clés : BRI, Banque des règlements internationaux, jeux de
    données, flux SDMX, statistiques bancaires internationales,
    statistiques de paiement, CPIM, produits dérivés, titres de créance,
    liquidité mondiale.
    """
    return await client.list_datasets(lang=lang)


@tool
async def bis_describe_dataset(dataset: str, lang: Lang = "en") -> DatasetStructure:
    """Describe a BIS dataset's dimensions and codes, to build a series key.

    Use for: the order of a BIS dataset's key dimensions and the codes
    each takes (areas, sectors, units, frequencies), before calling
    bis_get_series. `dataset` is an id from bis_list_datasets (e.g.
    WS_DSR). The result gives a key template and an example key for
    Canada.
    Keywords: BIS, dataset structure, dimensions, code list, series key,
    SDMX key, data structure definition, DSD, reference area codes,
    metadata.
    Mots-clés : BRI, structure du jeu de données, dimensions, liste de
    codes, clé de série, clé SDMX, définition de structure, codes de
    zone, métadonnées.
    """
    return await client.describe_dataset(dataset, lang=lang)


@tool
async def bis_get_series(
    dataset: str,
    key: str,
    start_period: str | None = None,
    end_period: str | None = None,
    last_n: int | None = None,
    lang: Lang = "en",
) -> SeriesResult:
    """Get BIS time series by dataset and SDMX key.

    Use for: any BIS series beyond the preset comparisons: Canada's
    cross-border bank claims, debt securities outstanding, CPMI cashless
    payment volumes, daily policy rates (WS_CBPOL key D.CA), US dollar
    exchange rates, OTC derivatives. `key` has one part per dimension in
    the order bis_describe_dataset gives, codes joined by `+`, `*` for
    all (e.g. WS_DSR `Q.CA+US.H`). Periods are SDMX (`2020`, `2020-Q1`,
    `2020-01`, `2020-01-31`); `last_n` keeps the last N per series. The
    result has a csv_url that opens the same query as CSV.
    Keywords: BIS, Bank for International Settlements, time series, SDMX
    key, banking statistics, payment statistics, exchange rates, policy
    rate, debt securities, CSV download.
    Mots-clés : BRI, Banque des règlements internationaux, séries
    chronologiques, clé SDMX, statistiques bancaires, statistiques de
    paiement, taux de change, taux directeur, titres de créance,
    téléchargement CSV.
    """
    return await client.get_series(
        dataset,
        key,
        start_period=start_period,
        end_period=end_period,
        last_n=last_n,
        lang=lang,
    )

"""MCP tools for the World Bank's World Development Indicators, centred on Canada.

Every series tool returns Canada first; comparisons are limited to G7 and
OECD member countries and the World Bank's OECD members aggregate, so the
module stays a Canadian data source rather than a world data browser.
`lang="fr"` asks the API's French edition (indicator, topic and country
names in French; definitions stay English upstream).
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.worldbank import client
from maplestats_mcp.modules.worldbank.schemas import (
    CanadaSeriesResult,
    IndicatorDetail,
    IndicatorSearchResult,
    TopicList,
)

Lang = Literal["en", "fr"]


@tool
async def worldbank_search_indicators(
    query: str | None = None,
    topic: str | None = None,
    limit: int = 25,
    lang: Lang = "en",
) -> IndicatorSearchResult:
    """Find a World Bank World Development Indicators code to compare Canada internationally.

    Use for: finding the WDI code for an international comparison of
    Canada (GDP per capita, real GDP growth, inflation, unemployment,
    exports as a share of GDP, government debt, CO2 emissions, life
    expectancy, R&D spending, population ageing). `query` matches every
    word against the name, code and definition; `topic` (an id or name
    from worldbank_list_topics, e.g. 3 or "Economy & Growth") narrows to
    one theme. Then call worldbank_get_canada_series with the code.
    Keywords: world bank, world development indicators, WDI, international
    comparison, indicator code, cross-country, G7, OECD countries, peer
    countries, global ranking, GDP per capita, development indicators.
    Mots-clés : Banque mondiale, Indicateurs du développement dans le monde
    (IDM), comparaison internationale, code d'indicateur, comparaison entre
    pays, pays du G7, pays de l'OCDE, pays comparables, classement mondial,
    PIB par habitant, indicateurs internationaux.
    """
    return await client.search_indicators(query=query, topic=topic, limit=limit, lang=lang)


@tool
async def worldbank_list_topics(lang: Lang = "en") -> TopicList:
    """List the World Bank WDI topics (themes) with how many indicators each has.

    Use for: browsing World Development Indicators by theme before a
    search (economy and growth, trade, health, education, environment,
    climate change, energy, financial sector, public sector, labour and
    social protection, science and technology), to pick the `topic` for
    worldbank_search_indicators.
    Keywords: world bank, WDI topics, themes, indicator categories,
    international indicators, browse, economy and growth, climate change,
    trade, health, education.
    Mots-clés : Banque mondiale, thèmes WDI, catégories d'indicateurs,
    indicateurs internationaux, parcourir, économie et croissance,
    changement climatique, échanges commerciaux, santé, éducation.
    """
    return await client.list_topics(lang=lang)


@tool
async def worldbank_get_indicator(indicator: str, lang: Lang = "en") -> IndicatorDetail:
    """Get the definition and original source of one World Bank WDI indicator.

    Use for: checking what a World Development Indicators code measures
    and who compiles it (e.g. NY.GDP.PCAP.PP.KD is GDP per capita at
    constant PPP dollars from the World Bank's national accounts;
    SL.UEM.TOTL.ZS is the ILO modelled unemployment rate, not
    Statistics Canada's Labour Force Survey rate) before comparing Canada
    with other countries.
    Keywords: world bank, WDI, indicator definition, methodology, source
    organization, metadata, ILO modelled estimate, purchasing power
    parity, international data.
    Mots-clés : Banque mondiale, WDI, définition de l'indicateur,
    méthodologie, organisme source, métadonnées, estimation modélisée de
    l'OIT, parité de pouvoir d'achat, données internationales.
    """
    return await client.get_indicator(indicator, lang=lang)


@tool
async def worldbank_get_canada_series(
    indicator: str,
    compare_with: list[str] | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    most_recent: int | None = None,
    lang: Lang = "en",
) -> CanadaSeriesResult:
    """Get Canada's annual World Bank WDI series, optionally beside G7 or OECD peers.

    Use for: how Canada compares internationally on one indicator over
    time: real GDP growth (NY.GDP.MKTP.KD.ZG), GDP per capita at PPP
    (NY.GDP.PCAP.PP.KD), inflation (FP.CPI.TOTL.ZG), unemployment
    (SL.UEM.TOTL.ZS), exports (NE.EXP.GNFS.ZS), population
    (SP.POP.TOTL), CO2 emissions per capita (EN.GHG.CO2.PC.CE.AR5).
    Canada is always included, first. `compare_with` takes "G7",
    "OECD" (the World Bank's OECD members aggregate), "OECD_MEMBERS"
    (all 38) or ISO3 codes of OECD members ("USA", "AUS"); other
    countries are refused. Years: `start_year`/`end_year`, or
    `most_recent` (the last N years with a value). With comparisons the
    result gives Canada's rank (1 = highest). Canadian sources (StatCan,
    Bank of Canada) are better for Canada's own latest figures.
    Keywords: world bank, Canada compared, international comparison, G7
    comparison, OECD comparison, peer countries, cross-country, ranking,
    GDP per capita, annual series, Canada vs United States.
    Mots-clés : Banque mondiale, Canada comparé, comparaison internationale,
    comparaison avec le G7, comparaison avec l'OCDE, pays comparables,
    classement du Canada, PIB par habitant, série annuelle, Canada et
    États-Unis.
    """
    return await client.get_canada_series(
        indicator,
        compare_with=compare_with,
        start_year=start_year,
        end_year=end_year,
        most_recent=most_recent,
        lang=lang,
    )

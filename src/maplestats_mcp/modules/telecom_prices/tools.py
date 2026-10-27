"""MCP tools for the CRTC Communications Market Reports (telecom prices and markets)."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.telecom_prices import client
from maplestats_mcp.modules.telecom_prices.schemas import (
    MarketTable,
    MarketTableList,
    PlanPrices,
    QuarterlyTrends,
)

Lang = Literal["en", "fr"]


@tool
async def telecom_get_plan_prices(
    service: Literal["mobile", "internet"] = "mobile",
    plan: str | None = None,
    province: str = "Canada",
    region: Literal["national", "urban", "rural", "all"] = "national",
    technology: Literal["lowest", "3G", "LTE", "5G", "all"] = "lowest",
    from_year: int | None = None,
    to_year: int | None = None,
    limit: int = 500,
    lang: Lang = "en",
) -> PlanPrices:
    """Average advertised monthly prices of cell phone and home Internet plans in Canada (CRTC).

    Use for: how mobile plan prices have changed since 2016 or 2020, what a
    5 GB, 10 GB, 20 GB, 50 GB or 100 GB mobile plan (or a talk-only plan)
    costs on average, and what a 50/10 Mbps or gigabit Internet plan costs,
    by province or territory and in urban or rural areas, at the end of each
    year from 2016 (CRTC year-end price survey, part of the Communications
    Market Reports). `plan` is a data allowance ('5 GB', '5', 'talk') or a
    speed ('50/10 Mbps'); omit it for every plan. `province` is a code (ON,
    QC...), 'Canada', 'Provinces', 'Territories', 'North', 'South' or 'all'.
    For mobile, `technology='lowest'` (the default) averages each provider's
    lowest price whatever the network; '3G', 'LTE' or '5G' keep one network.
    Prices are list prices before taxes, without promotions. For the
    monthly price index, read StatCan's cellular services CPI (vector
    v1212387935; Internet access services v41693216) with
    wds_get_data_from_vectors.
    Keywords: mobile plan prices, cell phone plan cost, wireless prices,
    data plan price by GB, Internet plan prices, broadband price, telecom
    affordability, CRTC price survey, rural vs urban prices.
    Mots-clés : prix des forfaits mobiles, coût d'un forfait cellulaire,
    prix du sans-fil, forfait de données, prix des forfaits Internet, prix de
    la large bande, abordabilité des télécommunications, CRTC, prix en
    milieu rural.
    """
    return await client.get_plan_prices(
        service,
        plan=plan,
        province=province,
        region=region,
        technology=technology,
        from_year=from_year,
        to_year=to_year,
        limit=limit,
        lang=lang,
    )


@tool
async def telecom_list_market_tables(
    sector: Literal["mobile", "internet"] = "mobile", lang: Lang = "en"
) -> MarketTableList:
    """List the CRTC's annual retail mobile or fixed Internet sector tables (tab ids and titles).

    Use for: finding which Communications Market Report table holds a
    telecom market indicator before reading it with
    telecom_get_market_table: revenue per GB of data, ARPU, monthly data
    usage, number of mobile subscribers, market shares of Bell, Rogers,
    TELUS, flanker brands and other providers, churn, distribution of
    subscribers by plan size, Internet subscriptions by speed or
    technology, overage fees. `sector` is 'mobile' or 'internet'. lang='fr'
    reads the French workbook (figures are 'G' tabs there, MB-G12).
    Keywords: CRTC communications market report, telecom market data,
    wireless competition indicators, mobile market share, broadband
    subscriptions, telecom sector statistics, CMR tables, ISP market.
    Mots-clés : rapport sur le marché des communications, CRTC, données du
    marché des télécommunications, concurrence sans fil, parts de marché
    mobile, abonnements à large bande, statistiques des télécoms, RMC.
    """
    return await client.list_market_tables(sector, lang=lang)


@tool
async def telecom_get_market_table(
    table: str,
    sector: Literal["mobile", "internet"] = "mobile",
    series: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    lang: Lang = "en",
) -> MarketTable:
    """One CRTC retail mobile or fixed Internet sector table as a tidy series by year.

    Use for: annual telecom competition and usage indicators since 2013:
    average revenue per GB of mobile data ('MB-S3'), national mobile ARPU
    ('MB-F12'), average monthly data usage per subscriber ('MB-F15'),
    number of mobile subscribers ('MB-S5'), revenue and subscriber market
    shares of Bell, TELUS, Rogers and others ('MB-S1'), share of
    subscribers by plan size ('MB-F7'), ARPU by province ('MB-S4'), churn
    ('MB-S13'); for Internet, revenue per GB ('N-S4'), revenues ('N-S1'),
    usage ('N-F12'), overage fees ('N-S3'). `table` is a tab id from
    telecom_list_market_tables; `series` keeps rows whose label holds
    those words ('Top 3', 'Bell'). Years marked mobile_phone_only (2020 on)
    count mobile phone services only. Growth and CAGR columns are left out.
    Keywords: revenue per GB, mobile ARPU, data usage per subscriber,
    wireless subscribers Canada, mobile market share Bell Rogers TELUS,
    churn rate, CRTC communications market report, telecom competition.
    Mots-clés : revenu par Go, RMPU mobile, utilisation de données par
    abonné, abonnés au sans-fil, part de marché Bell Rogers TELUS, taux de
    résiliation, rapport sur le marché des communications, concurrence.
    """
    return await client.get_market_table(
        table, sector, series=series, from_year=from_year, to_year=to_year, lang=lang
    )


@tool
async def telecom_get_quarterly_trends(
    service: Literal["mobile", "internet", "wireline", "tv_distribution"] = "mobile",
    metric: str | None = None,
    market: Literal["combined", "residential", "business", "all"] = "all",
    measure: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    limit: int = 500,
    lang: Lang = "en",
) -> QuarterlyTrends:
    """Quarterly telecom revenues, subscribers and data traffic in Canada since 2014 (CRTC).

    Use for: the latest quarter of mobile or Internet revenues, the number
    of mobile phone or high-speed Internet subscribers, wireless data
    traffic in GB (divide revenues by GB for revenue per GB by quarter),
    flanker brand revenues, Internet subscribers by speed tier, wireline
    lines and minutes, and cable, IPTV and satellite TV distribution
    revenues and subscribers, from 2014 Q1 to the latest quarter (CRTC
    Current Trends, about five months after the quarter). `metric` keeps
    metrics or subcategories holding those words ('Mobile phone',
    'Wireless data traffic', 'Data only'); `measure` keeps 'Revenues',
    'Subscribers', 'Lines', 'Minutes' or 'GB'; `market` is 'all' (default),
    'combined', 'residential' or 'business': each row names its market,
    and Combined rows are totals, so do not add them to the other two.
    Revenues are in dollars.
    Keywords: quarterly telecom revenues, mobile subscribers by quarter,
    wireless data traffic GB, Internet subscribers by speed, CRTC current
    trends, telecom industry quarterly results, cable TV subscribers,
    latest telecom revenue quarter.
    Mots-clés : revenus trimestriels des télécommunications, abonnés mobiles
    par trimestre, trafic de données sans fil, abonnés Internet par vitesse,
    tendances actuelles CRTC, résultats trimestriels, abonnés au câble,
    dernier trimestre des télécoms.
    """
    return await client.get_quarterly_trends(
        service,
        metric=metric,
        market=market,
        measure=measure,
        from_year=from_year,
        to_year=to_year,
        limit=limit,
        lang=lang,
    )

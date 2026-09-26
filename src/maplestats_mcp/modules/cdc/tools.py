"""MCP tools for Canadian Dairy Commission (CDC) data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cdc import client, constants
from maplestats_mcp.modules.cdc.schemas import (
    CdcCatalogue,
    ComponentPriceResult,
    MarketDataResult,
    MarketDataset,
    MarketSegment,
    MilkClassResult,
    QuotaResult,
    SupportPriceResult,
)

Lang = Literal["en", "fr"]


@tool
async def cdc_list_datasets(lang: Lang = "en") -> CdcCatalogue:
    """List the Canadian Dairy Commission datasets available here, and the marketing boards checked.

    Use for: seeing which dairy supply management data this server
    reaches (component prices, butter support price, national total
    quota, milk classes, production and milk class sales) and which tool
    returns each; and learning why provincial milk marketing boards
    (Dairy Farmers of Ontario, Les Producteurs de lait du Québec,
    Alberta Milk, BC Milk Marketing Board) and the national egg,
    chicken, turkey and hatching egg agencies have no tool (PDF only,
    captcha, or terms), with StatCan tables to use instead. No upstream
    call is made. `lang="fr"` returns French titles, notes and names
    (organizations without an official French name keep their own).
    Keywords: Canadian Dairy Commission, CDC, dairy, supply management,
    marketing board, milk, quota, egg farmers, chicken farmers, turkey,
    catalogue.
    Mots-clés : Commission canadienne du lait, CCL, produits laitiers,
    gestion de l'offre, office de commercialisation, lait, quota,
    Producteurs de lait du Québec, producteurs d'œufs, producteurs de
    poulet, dindon, volaille, catalogue.
    """
    return client.catalogue(lang)


@tool
async def cdc_get_component_prices(
    year_from: int | None = None,
    year_to: int | None = None,
    milk_class: str | None = None,
    lang: Lang = "en",
) -> ComponentPriceResult:
    """Get CDC special milk class component prices ($/kg butterfat, protein, other solids), monthly.

    Use for: the price of milk components in classes 3(d) (restaurant
    pizza mozzarella), 4(a) (butter, powders), 4(m) (animal feed), and
    5(a), 5(b), 5(c) (dairy ingredients for further processing and
    confectionery), from January 2002 to the latest announced month.
    `year_from`/`year_to` pick calendar years (default: the current
    year); `milk_class` filters one class ("5(a)", "5a", "3D"). Rows are
    sorted by month and class; a price the CDC does not set (0 or blank
    in its file) is None. For the butter support price use
    cdc_get_butter_support_prices; for class definitions,
    cdc_get_milk_classes. `lang` switches notes and the linked page.
    Keywords: milk price, component pricing, special milk class,
    butterfat price, protein price, other solids, class 5, class 4(a),
    Canadian Dairy Commission, dairy ingredients, SMCPP.
    Mots-clés : prix du lait, prix des composants, classes spéciales,
    prix de la matière grasse, prix des protéines, autres solides,
    classe 5, classe 4(a), Commission canadienne du lait, ingrédients
    laitiers.
    """
    return await client.get_component_prices(year_from, year_to, milk_class, lang)


@tool
async def cdc_get_butter_support_prices(lang: Lang = "en") -> SupportPriceResult:
    """Get the Canadian Dairy Commission's butter support price ($/kg) since 2010.

    Use for: the price at which the CDC buys and sells butter, set each
    year (usually effective February 1, sometimes mid-year such as May
    2024 or September 2022) after its cost of production study and
    consultations. Each row keeps the published label ("2024 (May)",
    "2024 (mai)" with `lang="fr"`) and an effective date. The CDC has
    not bought skim milk powder since 2017, so there is no powder
    support price. `lang` switches labels, notes and the linked page;
    values are identical in both languages.
    Keywords: butter support price, support price, butter price,
    Canadian Dairy Commission, CDC, dairy policy, farm gate milk price,
    supply management.
    Mots-clés : prix de soutien du beurre, prix de soutien, prix du
    beurre, Commission canadienne du lait, CCL, politique laitière, prix
    du lait à la ferme, gestion de l'offre.
    """
    return await client.get_butter_support_prices(lang)


@tool
async def cdc_get_national_quota(
    year_from: int | None = None, year_to: int | None = None, lang: Lang = "en"
) -> QuotaResult:
    """Get Canada's national milk production target (total quota), monthly, in kg of butterfat.

    Use for: the monthly total quota the CDC sets for Canada under the
    Canadian Milk Supply Management Committee, from January 2017 (the
    CDC publishes earlier years only by email request). Default: the
    latest year. Rows give year, month, kilograms of butterfat, the
    figure exactly as published and, for 2017-2018, the change from a
    year earlier. Notes flag months the pages omit (December 2018) and
    figures that are not valid numbers (March 2023). For actual farm
    production by province use cdc_query_market_data(dataset=
    "production"). `lang` switches notes and the linked pages.
    Keywords: national milk production target, total quota, milk
    quota, butterfat, dairy production, supply management, CMSMC,
    Canadian Dairy Commission.
    Mots-clés : cible nationale de production laitière, quota total,
    quota de lait, matière grasse, production laitière, gestion de
    l'offre, CCGAL, Commission canadienne du lait.
    """
    return await client.get_national_quota(year_from, year_to, lang)


@tool
async def cdc_get_milk_classes(milk_class: str | None = None, lang: Lang = "en") -> MilkClassResult:
    """Get the Harmonized Milk Classification System: which products belong to each milk class.

    Use for: looking up what dairy products fall in classes 1 to 5 and
    their subclasses (1(a) fluid milk, 2(a) yogurt, 3(a)-3(d) cheeses,
    4(a) butter and powders, 4(m) animal feed, 5(a)-5(c) ingredients
    for further processing), which provincial boards use to bill milk
    components. `milk_class` filters by class or prefix ("3", "3(c)",
    "4a"). `lang="fr"` returns the French product descriptions.
    Keywords: milk class, harmonized milk classification, dairy product
    classes, class 1 fluid milk, cheese class, butter, yogurt, Canadian
    Dairy Commission.
    Mots-clés : classe de lait, classification harmonisée du lait,
    classes de produits laitiers, lait de consommation, crème, fromage,
    beurre, yogourt, Commission canadienne du lait.
    """
    return await client.get_milk_classes(milk_class, lang)


@tool
async def cdc_query_market_data(
    dataset: MarketDataset,
    province: str | None = None,
    region: str | None = None,
    milk_class: str | None = None,
    segment: MarketSegment | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = constants.MARKET_DATA_DEFAULT_LIMIT,
    lang: Lang = "en",
) -> MarketDataResult:
    """Query CDC market data: milk production by province, milk class sales, farms shipping milk.

    Use for: monthly farm milk production in litres by province
    (dataset="production", since January 2016); monthly milk sales by
    class and subclass for the ten provinces ("sales_p10") or the East
    and West pools ("sales_by_region", with `region`), since July 2020,
    as litres, kg and dollars of butterfat, protein and other solids
    (`segment`, e.g. "butterfat_revenue"); and farms shipping milk on
    August 1 by province ("farms"). Filters: `province` (two-letter
    code), `milk_class` ("4", "4A", "3(b)"), dates as YYYY, YYYY-MM or
    YYYY-MM-DD. Newest rows first, up to `limit` (max 5000). Revenue
    divided by kg sold gives an average price per kg. `lang="fr"`
    returns French labels (region "Est"/"Ouest" is accepted too).
    Keywords: milk production, dairy sales, milk class sales, butterfat
    sales, dairy farms, P10, milk pool, Canadian Dairy Commission,
    provincial milk production.
    Mots-clés : production de lait, production laitière par province,
    ventes de produits laitiers, ventes par classe, ventes de matière
    grasse, fermes laitières, producteurs de lait, P10, mise en commun du
    lait, Commission canadienne du lait.
    """
    return await client.query_market_data(
        dataset,
        province=province,
        region=region,
        milk_class=milk_class,
        segment=segment,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        lang=lang,
    )

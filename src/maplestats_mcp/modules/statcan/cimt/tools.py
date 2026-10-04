"""MCP tools for StatCan's Canadian International Merchandise Trade (CIMT) API."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.cimt import client, constants
from maplestats_mcp.modules.statcan.cimt.schemas import (
    CimtPeriods,
    CommoditySearchResult,
    PartnerSearchResult,
    ProvinceBreakdownResult,
    SeriesResult,
    TopCommoditiesResult,
    TopPartnersResult,
    TradeResult,
)

Lang = Literal["en", "fr"]
Direction = Literal["exports", "imports"]
HsLevel = Literal["hs6", "national"]


@tool
async def cimt_get_periods(lang: Lang = "en") -> CimtPeriods:
    """Get the first and latest month covered by the merchandise trade database (CIMT).

    Use for: finding the latest published month of detailed Canadian
    exports and imports before querying them. Data starts in 1988-01.
    This is an undocumented web-application API: WDS has no
    commodity-level trade, only aggregates by section and partner.
    Keywords: CIMT, merchandise trade, exports, imports, latest month,
    coverage, reference period, Canadian international merchandise trade.
    Mots-clés : CICM, commerce de marchandises, exportations, importations,
    dernier mois, couverture, période de référence, commerce international
    canadien de marchandises, données disponibles.
    """
    return await client.get_periods()


@tool
async def cimt_search_commodities(
    query: str = "",
    direction: Direction = "exports",
    level: Literal["chapter", "heading", "hs6", "national"] = "hs6",
    lang: Lang = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> CommoditySearchResult:
    """Search Harmonized System (HS) commodity codes by code prefix or by words.

    Use for: turning a product ("crude petroleum", "pétrole brut") into the
    HS code that cimt_get_trade needs, or listing the codes under
    a chapter ("27"). Matches words in English and French. `level` is
    chapter (2 digits), heading (4), hs6 (6, the international level) or
    national (Canada's detail: 8 digits for exports, 10 for imports; the
    import list is a 16 MB file on first use). Each hit carries the unit
    of measure and the months the code was in use (codes change with HS
    revisions).
    Keywords: HS code, harmonized system, commodity, product, tariff,
    classification, trade, exports, imports, CIMT, search, chapter,
    heading.
    Mots-clés : code SH, Système harmonisé, marchandise, produit, tarif,
    classification, commerce, exportations, importations, CICM, recherche,
    chapitre, position.
    """
    return await client.search_commodities(
        query, direction=direction, level=level, lang=lang, limit=limit
    )


@tool
async def cimt_search_partners(
    query: str = "",
    kind: Literal["country", "us_state", "province"] = "country",
    lang: Lang = "en",
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
) -> PartnerSearchResult:
    """Search trading-partner countries, US states or Canadian provinces and their codes.

    Use for: finding the partner, US state or province to pass to
    cimt_get_trade and the other CIMT tools. They also accept a
    country's two-letter code ("CN"), a province's abbreviation ("AB")
    or a name directly. Country ids include historical partners
    (Czechoslovakia, West Germany) with the months they were reported.
    Exports are attributed to the US state of destination and imports to
    the state of origin.
    Keywords: trading partner, country code, US state, province, origin,
    destination, CIMT, trade, exports, imports, partner code, geography.
    Mots-clés : partenaire commercial, code de pays, État américain,
    province, origine, destination, CICM, commerce, exportations,
    importations, code de partenaire, géographie.
    """
    return await client.search_partners(query, kind=kind, lang=lang, limit=limit)


@tool
async def cimt_get_trade(
    direction: Direction,
    from_period: str,
    to_period: str,
    hs_code: str = "",
    partner: str = "",
    us_state: str = "",
    provinces: list[str] | None = None,
    hs_level: HsLevel = "hs6",
    annualize: bool = False,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> TradeResult:
    """Get Canadian merchandise exports or imports by month, HS commodity, partner and province.

    Use for: commodity-level trade values and quantities, for example
    "crude oil exports to the US by month in 2025" or "vehicle imports
    from Mexico by province". `from_period` and `to_period` are months
    (YYYY-MM, 1988-01 to the latest, see cimt_get_periods).
    `hs_code` is a prefix: 2 digits (chapter), 4 (heading), 6, 8 or 10;
    empty means every commodity (large: set a `limit` and narrow it).
    `hs_level` "hs6" aggregates to 6 digits for both directions;
    "national" returns Canada's detail (8 digits exports, 10 imports) and
    then the code may be at most that long. `partner` is a country id,
    two-letter code or name (empty = all countries), `us_state` a US state
    (implies the US), `provinces` provinces of origin for exports or of
    clearance for imports (empty = Canada). `annualize` sums calendar
    years. Values are Canadian dollars at current prices; exports include
    re-exports. When `truncated` is true the rows are an arbitrary subset
    of `total_count`, not a ranking: narrow the query. The undocumented
    web-application API behind these tools may change.
    Keywords: CIMT, exports, imports, merchandise trade, HS code,
    commodity, partner, province, US state, monthly trade, trade value,
    Statistics Canada, international trade.
    Mots-clés : CICM, exportations, importations, commerce de marchandises,
    code SH, marchandise, partenaire, province, État américain, commerce
    mensuel, valeur des échanges, Statistique Canada, commerce
    international.
    """
    return await client.get_trade(
        direction,
        from_period,
        to_period,
        hs_code=hs_code,
        partner=partner,
        us_state=us_state,
        provinces=provinces,
        hs_level=hs_level,
        annualize=annualize,
        limit=limit,
        lang=lang,
    )


@tool
async def cimt_get_top_partners(
    direction: Direction,
    period: str = "",
    hs_chapter: str = "",
    province: str = "",
    view: Literal["country", "us_state"] = "country",
    lang: Lang = "en",
) -> TopPartnersResult:
    """Rank Canada's 15 largest trading partners (countries or US states) for one month.

    Use for: "who buys the most Canadian lumber" or "top import sources
    in July 2026". `period` is a month (empty = latest). `hs_chapter`
    limits to a 2-digit HS chapter, `province` to one province.
    `view` "us_state" ranks the states within the United States.
    `total_value_cad` is the all-partner total, so shares are of the
    whole and, with no chapter, matches the published monthly total.
    The service returns only the top 15.
    Keywords: top trading partners, ranking, largest export markets,
    import sources, country, US state, CIMT, exports, imports, share,
    Canada trade.
    Mots-clés : principaux partenaires commerciaux, classement, plus grands
    marchés d'exportation, sources d'importation, pays, État américain,
    CICM, exportations, importations, part, commerce du Canada.
    """
    return await client.get_top_partners(
        direction, period=period, hs_chapter=hs_chapter, province=province, view=view, lang=lang
    )


@tool
async def cimt_get_top_commodities(
    direction: Direction,
    period: str = "",
    hs_chapter: str = "",
    province: str = "",
    partner: str = "",
    us_state: str = "",
    hs_level: HsLevel = "hs6",
    lang: Lang = "en",
) -> TopCommoditiesResult:
    """Rank the largest traded commodities for one month, by partner, province or HS chapter.

    Use for: "what does Alberta export to the US", "top imports from
    China" or the biggest products inside one HS chapter. `period` is a
    month (empty = latest). Filters are all optional. The service
    returns only its largest commodities.
    Keywords: top commodities, largest products, ranking, exports,
    imports, HS code, province, partner, CIMT, trade composition,
    leading goods.
    Mots-clés : principales marchandises, plus gros produits, classement,
    exportations, importations, code SH, province, partenaire, CICM,
    composition du commerce, principaux biens.
    """
    return await client.get_top_commodities(
        direction,
        period=period,
        hs_chapter=hs_chapter,
        province=province,
        partner=partner,
        us_state=us_state,
        hs_level=hs_level,
        lang=lang,
    )


@tool
async def cimt_get_province_breakdown(
    direction: Direction,
    period: str = "",
    hs_chapter: str = "",
    partner: str = "",
    us_state: str = "",
    lang: Lang = "en",
) -> ProvinceBreakdownResult:
    """Split one month of exports or imports by province, optionally for one partner or chapter.

    Use for: "which provinces export the most to China" or "imports by
    province of clearance". Exports are by province of origin (domestic
    exports and re-exports are reported separately); imports are by
    province of clearance, not of final use, which overstates provinces
    with ports and warehouses. `period` is a month (empty = latest).
    Keywords: trade by province, provincial exports, provincial imports,
    province of origin, province of clearance, CIMT, regional trade,
    territory, breakdown.
    Mots-clés : commerce par province, exportations provinciales,
    importations provinciales, province d'origine, province de dédouanement,
    CICM, commerce régional, territoire, répartition.
    """
    return await client.get_province_breakdown(
        direction,
        period=period,
        hs_chapter=hs_chapter,
        partner=partner,
        us_state=us_state,
        lang=lang,
    )


@tool
async def cimt_get_series(
    direction: Direction,
    hs_code: str,
    period: str = "",
    partner: str = "",
    us_state: str = "",
    province: str = "",
    lang: Lang = "en",
) -> SeriesResult:
    """Get a five-year monthly series of exports or imports for an HS chapter or one commodity.

    Use for: a quick trend line, for example crude oil exports to the US
    over the last 60 months. The window is the five years ending at
    `period` (empty = latest). `hs_code` is a 2-digit chapter (one value
    per month) or a 6-, 8- or 10-digit commodity (value and quantity
    measures: for exports `domestic_value` plus `reexport_value` is total
    exports, and the quantities are in `unit`). For longer ranges or
    several commodities use cimt_get_trade.
    Keywords: time series, monthly trend, exports, imports, HS code,
    chapter, commodity, five years, CIMT, quantity, value.
    Mots-clés : série chronologique, tendance mensuelle, exportations,
    importations, code SH, chapitre, marchandise, cinq ans, CICM, quantité,
    valeur.
    """
    return await client.get_series(
        direction,
        hs_code,
        period=period,
        partner=partner,
        us_state=us_state,
        province=province,
        lang=lang,
    )

"""MCP tools for the Bank of Canada Valet API.

Every tool returns a typed Pydantic model (see schemas.py) - FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.

`lang="fr"` sends the request to the Bank's French domain
(banqueducanada.ca/valet), which returns series and group labels,
descriptions and Valet's own error messages in French; MapleStats's own
notes, limits and errors follow `lang` too. Valet has no language query
parameter, so the domain is what selects the language.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.boc import client, constants, surveys
from maplestats_mcp.modules.boc.schemas import (
    GroupDetail,
    GroupList,
    GroupObservationsResult,
    MprProjectionResult,
    ObservationsResult,
    SeriesDetail,
    SeriesList,
    StaffProjectionResult,
    SurveyResult,
)
from maplestats_mcp.shared.transform import Aggregation, Frequency, Transform, TransformRequest

Lang = Literal["en", "fr"]
StaffVariableCode = Literal[
    "GDP", "GDPN", "PGDP", "GNEN", "PGNE", "C", "PC", "I", "IINVT", "IRES", "G", "X", "M",
    "CIRINV", "PCIRINV", "LYGAP", "PCPI", "PCPIX", "URATE", "USCANPFX", "R1N", "R20N",
]  # fmt: skip


@tool
async def boc_search_series(
    query: str | None = None, limit: int | None = None, lang: Lang = "en"
) -> SeriesList:
    """Search or list Bank of Canada Valet's ~16,000 statistical series.

    Use for: finding a Valet series name when you only know a topic -
    exchange rates, interest rates (policy rate, prime rate), CPI/
    inflation measures, commodity prices, and hundreds of other
    monetary/financial series. Pass `query` for a keyword search (top
    `limit` matches, default 25, max 200). Omit `query` to page through
    the catalogue in name order (`limit` default 50, max 1000);
    `total_count` is the full number and provenance.limits says what was
    cut.
    Keywords: bank of canada, boc, valet, series, search, find, exchange
    rate, interest rate, policy rate, prime rate, five-year mortgage
    rate, bond yield, cpi, inflation, commodity price, discover, list,
    inventory, all series, catalogue, full list.
    Mots-clés : Banque du Canada, valet, série, recherche, trouver, taux
    de change, taux d'intérêt, taux directeur, taux préférentiel, taux
    hypothécaire, rendement des obligations, IPC, inflation, prix des
    matières premières, découvrir, liste, inventaire, toutes les séries,
    catalogue, liste complète, parcourir.
    """
    if query is not None:
        return await client.search_series(
            query, limit=constants.SEARCH_LIMIT_DEFAULT if limit is None else limit, lang=lang
        )
    # page_series copies, so the cached full list is not trimmed in place.
    return client.page_series(
        await client.list_series(lang),
        constants.LIST_LIMIT_DEFAULT if limit is None else limit,
        lang,
    )


@tool
async def boc_search_groups(
    query: str | None = None, limit: int | None = None, lang: Lang = "en"
) -> GroupList:
    """Search or list Bank of Canada Valet's series groups (~2,500).

    Use for: finding a themed group of related series (e.g. daily
    exchange rates, the CPI family including CPI-trim/median/common,
    weekly/monthly/annual commodity price indexes) when you want several
    related series at once rather than one series name. Pass `query`
    for a keyword search (top `limit` matches, default 25, max 200). Omit
    `query` to page through the groups (`limit` default 50, max 1000).
    Keywords: bank of canada, boc, valet, group, series group, search,
    find, cpi, exchange rates, commodity prices, discover, list, groups,
    inventory, catalogue, full list.
    Mots-clés : Banque du Canada, valet, groupe, groupe de séries,
    recherche, trouver, IPC, taux de change, prix des produits de base,
    IPPB, découvrir, liste, groupes, inventaire, catalogue, liste complète,
    parcourir.
    """
    if query is not None:
        return await client.search_groups(
            query, limit=constants.SEARCH_LIMIT_DEFAULT if limit is None else limit, lang=lang
        )
    return client.page_groups(
        await client.list_groups(lang),
        constants.LIST_LIMIT_DEFAULT if limit is None else limit,
        lang,
    )


@tool
async def boc_get_series(name: str, lang: Lang = "en") -> SeriesDetail:
    """Get the label and description for one Bank of Canada Valet series.

    Use for: confirming what a series code actually measures before
    requesting its observations, e.g. FXUSDCAD (USD/CAD daily exchange
    rate), V39079 (target for the overnight rate / policy rate),
    V80691311 (prime rate), V41690973 (Total CPI).
    Keywords: bank of canada, boc, valet, series, detail, metadata,
    description, label, lookup.
    Mots-clés : Banque du Canada, valet, série, détail, métadonnées,
    description, libellé, recherche par code, consulter, code de série.
    """
    return await client.get_series(name, lang=lang)


@tool
async def boc_get_group(name: str, lang: Lang = "en") -> GroupDetail:
    """Get a Bank of Canada Valet group's description and member series.

    Use for: discovering all the series in a themed group before
    fetching their observations together, e.g. FX_RATES_DAILY (daily
    exchange rates for ~27 currencies) or CPI_MONTHLY (Total CPI plus
    core-inflation measures such as CPI-trim, CPI-median, CPI-common).
    Keywords: bank of canada, boc, valet, group, detail, member series,
    cpi, exchange rates, commodity prices, metadata.
    Mots-clés : Banque du Canada, valet, groupe, détail, séries membres,
    IPC, taux de change, prix des produits de base, métadonnées.
    """
    return await client.get_group(name, lang=lang)


@tool
async def boc_get_observations(
    series_names: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    window: int | None = None,
    lang: Lang = "en",
) -> ObservationsResult:
    """Get observations for one or more Bank of Canada Valet series,
    optionally as a computed change, growth rate, index or monthly,
    quarterly or annual aggregate.

    Use for: fetching exchange rate history, interest rate history,
    CPI/inflation history, or commodity price history for one or more
    named series in a single call (observations for several series at
    once: series_names accepts multiple codes, e.g. ["FXUSDCAD", "FXEURCAD"]), and computing from them a
    year-over-year change, a monthly average exchange rate or the change
    in the policy rate.
    `start_date`/`end_date` (each "YYYY-MM-DD") and
    `recent`/`recent_weeks`/`recent_months`/`recent_years` are mutually
    exclusive - Valet rejects mixing them. Series requested together
    are merged into one row per date only when they share the same
    publication frequency; mixing frequencies (e.g. a daily FX rate
    with monthly CPI) returns separate rows, each carrying only its own
    series - check each row's `values` keys rather than assuming every
    requested series appears in every row. With no window, only the 30
    most recent dates come back (pass start_date or recent_* for more);
    provenance.limits says how many dates were left out. A value Valet
    sends as text that is not a number is null in `values`, with the
    text in the row's `non_numeric`.
    `transform` (diff, pct_change, yoy_diff, yoy_pct_change,
    annualized_pct_change, index, moving_average: trailing average over
    `window` periods; `window` with a change averages the change) and
    `frequency` with `aggregation`
    compute from the published levels (a daily series needs `frequency`
    for a year-over-year change); a series in percent gets
    percentage-point changes. `transformed` holds the computed values
    with their formula.
    Keywords: bank of canada, boc, valet, observations, data, exchange
    rate, interest rate, policy rate, prime rate, cpi, inflation,
    commodity price, time series, history, recent, date range,
    year-over-year, percent change, monthly average, annual average,
    moving average, rolling average, several series in one call.
    Mots-clés : Banque du Canada, valet, observations, données, taux de
    change, taux d'intérêt, taux directeur, taux préférentiel, IPC,
    inflation, prix des matières premières, série chronologique,
    historique, plage de dates, variation annuelle, variation en
    pourcentage, moyenne mensuelle, moyenne annuelle, moyenne mobile.
    """
    return await client.get_observations(
        series_names,
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
        lang=lang,
        request=TransformRequest(transform, frequency, aggregation, index_base, window),
    )


@tool
async def boc_get_group_observations(
    group_name: str,
    start_date: str | None = None,
    end_date: str | None = None,
    recent: int | None = None,
    recent_weeks: int | None = None,
    recent_months: int | None = None,
    recent_years: int | None = None,
    lang: Lang = "en",
) -> GroupObservationsResult:
    """Get observations for every series in a Bank of Canada Valet group.

    Use for: fetching all series in a themed group at once, e.g. every
    daily exchange rate in FX_RATES_DAILY or the full CPI_MONTHLY family
    (Total CPI, CPI-trim, CPI-median, CPI-common), without listing each
    series name individually.
    `start_date`/`end_date` and `recent`/`recent_weeks`/`recent_months`/
    `recent_years` are mutually exclusive, same as boc_get_observations.
    With no window, only the 30 most recent dates come back (pass
    start_date or recent_* for more); provenance.limits says
    how many dates were left out.
    Keywords: bank of canada, boc, valet, group, observations, data,
    exchange rates, cpi, inflation, commodity prices, time series,
    history, recent, date range.
    Mots-clés : Banque du Canada, valet, groupe, observations, données,
    taux de change, IPC, inflation, prix des produits de base, série
    chronologique, historique, plage de dates.
    """
    return await client.get_group_observations(
        group_name,
        start_date=start_date,
        end_date=end_date,
        recent=recent,
        recent_weeks=recent_weeks,
        recent_months=recent_months,
        recent_years=recent_years,
        lang=lang,
    )


@tool
async def boc_get_business_outlook(quarter: str | None = None, lang: Lang = "en") -> SurveyResult:
    """Get the Bank of Canada's Business Outlook Survey (BOS) results for the
    latest quarter (or a named one): what firms expect for sales, investment,
    hiring, prices, labour costs and inflation.

    Use for: business sentiment and expectations in Canada - the BOS
    indicator and its activity and price indicators, balances of opinion on
    future sales, investment in machinery and equipment, employment, input
    and output prices, labour costs, labour shortages, capacity pressures and
    credit conditions, and the share of firms expecting inflation below 1%,
    1-2%, 2-3% or above 3% over the next two years. One row per question with
    its unit and survey quarter; `release` names the quarter's publication
    (month, page link) and its chart groups (regional, sector and firm-size
    breakdowns, firms' 1-, 2- and 5-year inflation expectations) for
    boc_get_group_observations. `quarter` like "2026Q3"; omit it for the
    newest survey, found from the data, not a fixed date.
    Keywords: business outlook survey, bos, business expectations, business
    sentiment, firms expect inflation, business confidence, balance of
    opinion, investment intentions, hiring plans, price expectations,
    labour shortages, bank of canada survey.
    Mots-clés : Enquête sur les perspectives des entreprises, EPE, attentes
    des entreprises, sentiment des entreprises, confiance des entreprises,
    attentes d'inflation des entreprises, solde des opinions, intentions
    d'investissement, intentions d'embauche, pénuries de main-d'œuvre,
    Banque du Canada.
    """
    return await surveys.get_survey("bos", quarter, lang)


@tool
async def boc_get_consumer_expectations(
    quarter: str | None = None, lang: Lang = "en"
) -> SurveyResult:
    """Get the Bank of Canada's Canadian Survey of Consumer Expectations
    (CSCE) for the latest quarter (or a named one): households' inflation
    expectations by horizon and their views on jobs, income, spending and
    interest rates.

    Use for: consumer inflation expectations one, two and five years ahead
    and perceived current inflation, expected pay growth, expected income
    and spending growth, probabilities of losing, leaving or finding a job,
    expected interest rates one, two and five years ahead, and the share of
    consumers expecting the economy to grow or decline. One row per series
    with its unit and survey quarter; `release` names the quarter's
    publication (month, page link) and chart groups. Breakdowns by age,
    income, education, province and other groups are in Valet group
    CES_DEMOGRAPHICS (boc_get_group_observations). `quarter` like "2026Q3";
    omit it for the newest survey, found from the data.
    Keywords: consumer expectations, csce, inflation expectations, household
    inflation expectations, consumers expect inflation, expected inflation
    one year ahead, five-year inflation expectations, job loss probability, consumer sentiment, interest rate expectations.
    Mots-clés : Enquête canadienne sur les attentes des consommateurs, ECAC,
    attentes d'inflation, anticipations d'inflation des ménages, attentes des
    consommateurs, inflation attendue dans un an, attentes salariales,
    probabilité de perdre son emploi, sentiment des consommateurs, attentes
    de taux d'intérêt, Banque du Canada.
    """
    return await surveys.get_survey("csce", quarter, lang)


@tool
async def boc_get_mpr_projection(
    report: str | None = None, lang: Lang = "en"
) -> MprProjectionResult:
    """Get the Bank of Canada's projections from the latest Monetary Policy
    Report (or a named one): real GDP growth, the inflation outlook,
    contributions to GDP growth and global growth.

    Use for: the Bank of Canada's forecast for the Canadian economy - the
    summary of the quarterly projection (real GDP growth quarter over
    quarter at annual rates and year over year, projected inflation, by
    quarter and to the fourth quarter of the next two years), the
    contributions of consumption, housing, government, business investment,
    exports, imports and inventories to annual GDP growth with the
    range for potential output, and projected growth for the United States,
    euro area, China and the world. One row per value with its table, period
    and unit; `release` gives the Report's month, page and chart groups.
    `report` like "2026M10", "2026-10" or "October 2026"; omit it for the
    newest Report in Valet. `recent_reports` lists others.
    Keywords: monetary policy report, mpr, bank of canada forecast, gdp
    forecast, inflation forecast, economic projection, growth outlook,
    potential output, global growth projection, base-case
    projection.
    Mots-clés : Rapport sur la politique monétaire, RPM, prévisions de la
    Banque du Canada, prévision du PIB, prévision de l'inflation, projection
    économique, perspectives de croissance, production potentielle,
    croissance mondiale, projection de référence.
    """
    return await surveys.get_mpr_projection(report, lang)


@tool
async def boc_get_staff_projections(
    variables: list[StaffVariableCode] | None = None,
    vintage: str | None = None,
    history_quarters: int = 4,
    lang: Lang = "en",
) -> StaffProjectionResult:
    """Get a vintage of the Bank of Canada staff economic projections: the
    staff forecast prepared for Governing Council, with the data known then.

    Use for: historical real-time projections (released yearly with a
    five-year lag, vintages from 1970Q4) for forecast-evaluation and
    real-time research - real GDP (GDP), nominal GDP (GDPN), deflators
    (PGDP, PC), consumption (C), investment (I, IRES, IINVT), government (G),
    exports (X), imports (M), the output gap (LYGAP), CPI (PCPI), core CPI
    (PCPIX), the unemployment rate (URATE), the US/CAD exchange rate
    (USCANPFX), the policy rate path (R1N) and the 5-year bond rate (R20N).
    Default variables GDP, PCPI, PCPIX, URATE, LYGAP and R1N; `vintage` like
    "2019Q4" (omit for the newest). Rows from `history_quarters` before the
    vintage; `projected` marks the forecast quarters. Rates and the gap are
    fractions (0.0175 is 1.75%); each variable's unit is given. For the
    current outlook use boc_get_mpr_projection.
    Keywords: staff economic projections, staff projection archive,
    real-time data, vintage, historical projections, forecast
    evaluation, output gap, policy rate path, sep, projection vintages,
    five-year lag.
    Mots-clés : projections économiques du personnel, prévisions du personnel
    de la Banque du Canada, données en temps réel, millésime de prévision,
    prévisions historiques, évaluation des prévisions, écart de production,
    trajectoire du taux directeur, millésimes.
    """
    return await surveys.get_staff_projections(
        list(variables) if variables else None, vintage, history_quarters, lang
    )

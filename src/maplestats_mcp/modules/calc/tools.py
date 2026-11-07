"""calc_ tools: arithmetic across StatCan and Bank of Canada series, with the formula shown."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.calc import client
from maplestats_mcp.modules.calc.schemas import (
    ChangeCountResult,
    GrowthResult,
    RankResult,
    RatioResult,
    SeriesRef,
)


@tool
async def calc_ratio(
    numerator: SeriesRef,
    denominator: SeriesRef,
    start: str | None = None,
    end: str | None = None,
    latest_n: int = 1,
    frequency: Literal["monthly", "quarterly", "annual"] | None = None,
    aggregation: Literal["average", "sum", "end_of_period"] = "average",
    multiplier: float = 1.0,
    lang: Literal["en", "fr"] = "en",
) -> RatioResult:
    """Divide one published series by another, period by period, and get the
    formula, the unit and both series' citations with the result.

    Use for: a ratio, a share of a total or a per-person figure built from two
    series, instead of dividing by hand. Each series is a StatCan `vector_id`,
    a StatCan `product_id` + `coordinate`, or a Bank of Canada `boc_series`.
    Periods are matched by calendar period; StatCan values are multiplied by
    their scale factor (thousands, millions) before dividing. Give
    `start`/`end` (2024, 2024-07, 2024-Q2) or `latest_n` (the latest periods
    both have). Series of different frequencies are refused unless
    `frequency` and `aggregation` put both on one (frequency='annual' to
    divide a series given by month by one given by year). An index divided by another
    unit, or current by constant dollars, is refused. `multiplier` scales the
    ratio: 100 for a percent, 12 to turn an amount per month into one per year.
    Keywords: ratio, share of total, proportion, per capita, per person,
    divide, quotient, relative to, two series, formula, percent of.
    Mots-clés : rapport, ratio, part du total, proportion, par habitant,
    par personne, diviser, quotient, deux séries, formule, pourcentage de.
    """
    return await client.ratio(
        numerator,
        denominator,
        start=start,
        end=end,
        latest_n=latest_n,
        frequency=frequency,
        aggregation=aggregation,
        multiplier=multiplier,
        lang=lang,
    )


@tool
async def calc_rank(
    series: list[SeriesRef] | None = None,
    product_id: str | None = None,
    coordinate: str | None = None,
    exclude_member_ids: list[int] | None = None,
    period: str | None = None,
    order: Literal["descending", "ascending"] = "descending",
    frequency: Literal["monthly", "quarterly", "annual"] | None = None,
    aggregation: Literal["average", "sum", "end_of_period"] = "average",
    lang: Literal["en", "fr"] = "en",
) -> RankResult:
    """Rank places or series by their value for one period, ties shared, with
    every series' citation.

    Use for: which place is highest or lowest on one measure, top and bottom
    places, a league table, instead of sorting by hand. Either list the
    `series` (2 to 60: vector_id, product_id + coordinate, or boc_series), or
    give a StatCan `product_id` and a `coordinate` with '*' at the dimension
    to rank across: '*.7.1.1.1.1' in 14-10-0287 ranks every Geography member;
    `exclude_member_ids` drops members (1, Canada, there). `period` (2026-09,
    2026-Q2, 2025) defaults to the latest period most series have. Every
    series must share one unit and one frequency, or the call is refused;
    `frequency` + `aggregation` rank yearly averages instead.
    Equal values share a rank (1, 2, 2, 4).
    Keywords: rank, ranking, highest, lowest, top, bottom, league table,
    order places, which province is highest, leaderboard, sort by value.
    Mots-clés : classement, classer, le plus élevé, le plus bas, premier,
    dernier, palmarès, quelle province, ordonner les lieux, rang.
    """
    return await client.rank(
        series,
        product_id=product_id,
        coordinate=coordinate,
        exclude_member_ids=exclude_member_ids,
        period=period,
        order=order,
        frequency=frequency,
        aggregation=aggregation,
        lang=lang,
    )


@tool
async def calc_cagr(
    series: SeriesRef,
    start: str,
    end: str,
    frequency: Literal["monthly", "quarterly", "annual"] | None = None,
    aggregation: Literal["average", "sum", "end_of_period"] = "average",
    lang: Literal["en", "fr"] = "en",
) -> GrowthResult:
    """Compound annual growth rate of one series between two periods, with the
    number of years, the formula and the citation.

    Use for: the yearly growth rate implied over several years, instead of
    computing it by hand (and miscounting the years). `series` is a StatCan
    `vector_id` or `product_id` + `coordinate`, or a Bank of Canada
    `boc_series`. `start` and `end` are periods of the series' own frequency
    (2015-01 and 2025-01 for a series by month); pass `frequency='annual'`
    with `aggregation` ('average' for prices and indexes, 'sum' for flows) to
    compare whole years (2015 and 2025). Years = periods apart ÷ periods a
    year. A percentage or rate is refused: its change is in percentage
    points, not compound growth.
    Keywords: CAGR, compound annual growth rate, annualized growth, growth per
    year, yearly growth over years, since 2015, over a decade, compounded.
    Mots-clés : TCAC, taux de croissance annuel composé, croissance annualisée,
    croissance par an, croissance composée, depuis 2015, sur dix ans, composé.
    """
    return await client.growth(
        series, start=start, end=end, frequency=frequency, aggregation=aggregation, lang=lang
    )


@tool
async def calc_count_changes(
    series: SeriesRef,
    start: str,
    end: str | None = None,
    threshold: float = 0.0,
    lang: Literal["en", "fr"] = "en",
) -> ChangeCountResult:
    """Count the times a series changed over a window, each change listed (date,
    before, after), with the series' citation.

    Use for: how many times a rate was cut or raised in a year, how often a
    published series moved, instead of counting by hand. The policy rate is
    Valet 'V39079' (target for the overnight rate). `series` is a Bank of
    Canada `boc_series` or a StatCan `vector_id` or `product_id` +
    `coordinate`. `start` and `end` are periods or dates (2024, 2024-06,
    2024-06-05; `end` defaults to today). Each value is compared with the
    previous published one, the first with the last value before the window;
    missing values are skipped, not read as changes. `threshold` counts only
    larger moves (0.1 for at least 0.1 point). Changes of a rate are in
    percentage points.
    Keywords: count changes, rate moves, rate cuts, rate hikes, how many
    times, number of changes, decisions, moved, changed, increases.
    Mots-clés : nombre de variations, baisses de taux, hausses de taux,
    combien de fois, décisions, nombre de changements, mouvements, hausses.
    """
    return await client.count_changes(series, start=start, end=end, threshold=threshold, lang=lang)

"""Server-side transforms (change, growth, index, aggregation) for the WDS series tools.

The arithmetic is shared/transform.py's; this file fetches what it needs:
each series' frequency, unit of measure and scalar factor (getSeriesInfo
plus getCodeSets), and enough history before the requested window for the
lag (12 more months for a year-over-year change of a monthly series).

The published values stay in `observations`, unchanged; the computed ones
go in the series' `transformed` block with their formula and unit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.modules.statcan.wds.schemas import SeriesInfo, VectorSeries
from maplestats_mcp.shared.errors import DataLocked, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.transform import (
    PERIODS_PER_YEAR,
    TransformedSeries,
    TransformRequest,
    extra_months,
    is_rate_unit,
    parse_period,
    shift_months,
    source_periods_needed,
    transform_series,
)

__all__ = ["FREQUENCY_PPY", "TransformRequest", "apply", "compute", "kept_dates"]

# WDS frequencyCode -> periods per year (getCodeSets `frequency`, checked
# 2026-10-27). Daily, weekly, every-N-years and occasional series have no
# calendar step a year-over-year lag can count in.
FREQUENCY_PPY = {6: 12, 7: 6, 9: 4, 11: 2, 12: 1}


def _out_ppy(request: TransformRequest, source_ppy: int | None) -> int | None:
    return PERIODS_PER_YEAR[request.frequency] if request.frequency else source_ppy


async def series_infos(vector_ids: list[int]) -> dict[int, SeriesInfo]:
    """getSeriesInfoFromVector for each vector; one that WDS does not know is
    left out here and reported in the data call's `failed`, as without a transform."""
    infos: dict[int, SeriesInfo] = {}
    for vector_id in dict.fromkeys(vector_ids):
        try:
            infos[vector_id] = await client.get_series_info_from_vector(vector_id)
        except NotFound:
            continue
    return infos


def base_months(index_base: str | None) -> int:
    """Months from the start of index_base to now (the history an index needs)."""
    if not index_base:
        return 0
    try:
        start, _ = parse_period(index_base)
    except ValueError:
        return 0  # transform_series rejects it with a clear message
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    return max(0, (today.year - start.year) * 12 + today.month - start.month + 1)


def latest_n_to_fetch(latest_n: int, request: TransformRequest, ppys: list[int | None]) -> int:
    """latestN to ask WDS for so every series (by its periods per year) can
    give `latest_n` computed periods. reproduce_code asks for the same."""
    needed = latest_n
    for source_ppy in ppys:
        out_ppy = _out_ppy(request, source_ppy)
        needed = max(
            needed, source_periods_needed(latest_n, request.transform, source_ppy, out_ppy)
        )
        if request.index_base and source_ppy:
            needed = max(needed, base_months(request.index_base) * source_ppy // 12 + 1)
    return needed


def start_to_fetch(start: date, request: TransformRequest, ppys: list[int | None]) -> date:
    """The first reference date to ask for: `start`, moved back by the lag."""
    months = 0
    for source_ppy in ppys:
        out_ppy = _out_ppy(request, source_ppy)
        months = max(
            months,
            extra_months(request.transform, out_ppy, aggregating=request.frequency is not None),
        )
    earliest = shift_months(start, -months) if months else start
    if request.index_base:
        try:
            earliest = min(earliest, parse_period(request.index_base)[0])
        except ValueError:
            pass
    return earliest


def ppys(infos: list[SeriesInfo]) -> list[int | None]:
    return [FREQUENCY_PPY.get(info.frequency_code or 0) for info in infos]


async def unit_descriptions(
    uom_code: int | str | None, scalar_code: int | None, lang: str
) -> tuple[str | None, str | None]:
    """The unit of measure and scalar factor descriptions from getCodeSets.

    StatCan's SDMX UOM attribute uses the same codes as WDS memberUomCode
    (checked 2026-10-27: CPI 17 "2002=100", unemployment rate 239 "Percent").
    """
    try:
        obj, _ = await client._code_sets_raw()
    except (UpstreamUnavailable, UpstreamError, DataLocked, NotFound):
        return None, None

    def find(key: str, code_field: str, en_field: str, fr_field: str, code: Any) -> Any:
        for entry in list_or_empty(obj, key):
            if code is not None and str(entry.get(code_field)) == str(code):
                return (
                    (entry.get(fr_field) or entry.get(en_field))
                    if lang == "fr"
                    else (entry.get(en_field))
                )
        return None

    uom = find("uom", "memberUomCode", "memberUomEn", "memberUomFr", uom_code)
    scalar = find(
        "scalar", "scalarFactorCode", "scalarFactorDescEn", "scalarFactorDescFr", scalar_code
    )
    return uom, scalar


async def compute(
    points: list[tuple[date, float | None]],
    *,
    source_ppy: int | None,
    uom_code: int | str | None,
    scalar_code: int | None,
    request: TransformRequest,
    lang: str,
    latest_n: int | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> TransformedSeries:
    """transform_series with the series' unit (percent guard) and scale (unit of a difference)."""
    uom, scalar = await unit_descriptions(uom_code, scalar_code, lang)
    scalar_code = scalar_code or 0
    units = uom
    if uom and scalar_code and scalar:
        units = say(f"{uom}, in {scalar}", f"{uom}, en {scalar}", lang)
    computed = transform_series(
        points,
        source_ppy=source_ppy,
        transform=request.transform,
        frequency=request.frequency,
        aggregation=request.aggregation,
        index_base=request.index_base,
        rate_unit=is_rate_unit(uom),
        units=units,
        window_start=window_start,
        window_end=window_end,
        latest_n=latest_n,
        lang=lang,
    )
    if computed.transform in ("diff", "yoy_diff") and scalar_code and scalar:
        factor = f"{10**scalar_code:,}"
        computed.notes.append(
            say(
                f"Differences are in the published units ({scalar}): multiply by {factor} for "
                "units, as for the published values. Percent changes do not depend on the scale.",
                f"Les différences sont dans les unités publiées ({scalar}) : multipliez par "
                f"{factor.replace(',', ' ')} pour les unités, comme pour les valeurs publiées. "
                "Les variations en pourcentage ne dépendent pas de l'échelle.",
                lang,
            )
        )
    return computed


def kept_dates(
    computed: TransformedSeries,
    out_ppy: int | None,
    days: list[date],
    *,
    latest_n: int | None,
    window_start: date | None,
    window_end: date | None,
) -> list[date]:
    """The published dates to keep beside the computed points: the periods
    those points cover (the extra history was only for the lag)."""
    kept = days
    if computed.points:
        first = computed.points[0].ref_date
        last = shift_months(computed.points[-1].ref_date, 12 // (out_ppy or 12))
        kept = [d for d in kept if first <= d < last]
    else:
        if window_start is not None:
            kept = [d for d in kept if d >= window_start]
        if latest_n is not None:
            kept = kept[-latest_n:]
    if window_end is not None:
        kept = [d for d in kept if d <= window_end]
    return kept


async def apply(
    series: VectorSeries,
    info: SeriesInfo | None,
    request: TransformRequest,
    *,
    latest_n: int | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> VectorSeries:
    """The series with `transformed` set and `observations` cut back to the
    periods the computed values cover."""
    if info is None:
        info = await client.get_series_info_from_vector(series.vector_id)
    source_ppy = FREQUENCY_PPY.get(info.frequency_code or 0)
    computed = await compute(
        [(row.ref_period, row.value) for row in series.observations],
        source_ppy=source_ppy,
        uom_code=info.member_uom_code,
        scalar_code=info.scalar_factor_code,
        request=request,
        lang=client._LANG.get(),
        latest_n=latest_n,
        window_start=window_start,
        window_end=window_end,
    )
    keep = set(
        kept_dates(
            computed,
            _out_ppy(request, source_ppy),
            [row.ref_period for row in series.observations],
            latest_n=latest_n,
            window_start=window_start,
            window_end=window_end,
        )
    )
    observations = [row for row in series.observations if row.ref_period in keep]
    return series.model_copy(update={"observations": observations, "transformed": computed})


def coverage_note(fetched: str) -> str:
    """Provenance coverage for a transformed call: what was fetched and what is returned."""
    return client._m(
        f"Computed by MapleStats from the published values (see each series' "
        f"transformed.formula); {fetched} was fetched so the lag reaches back far enough, and "
        "only the requested window is returned.",
        f"Calculé par MapleStats à partir des valeurs publiées (voir transformed.formula de "
        f"chaque série) ; {fetched} a été demandé pour que le décalage remonte assez loin, et "
        "seule la période demandée est renvoyée.",
    )

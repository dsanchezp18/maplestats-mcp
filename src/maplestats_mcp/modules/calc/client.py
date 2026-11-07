"""Fetch the series a calculation needs, then hand them to compute.py.

Every read goes through the existing clients: StatCan WDS
(statcan/wds/client.py for the data, statcan/wds/context.py for the citation,
unit and scale) and Bank of Canada Valet (boc/client.py). Their caches, rate
limits and typed errors apply unchanged; this file adds no HTTP of its own.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from maplestats_mcp.modules.boc import client as boc
from maplestats_mcp.modules.calc import compute
from maplestats_mcp.modules.calc.compute import Loaded
from maplestats_mcp.modules.calc.schemas import (
    ChangeCountResult,
    GrowthResult,
    InputSeries,
    RankResult,
    RatioResult,
    SeriesRef,
    SeriesValue,
)
from maplestats_mcp.modules.statcan.wds import client as wds
from maplestats_mcp.modules.statcan.wds import context
from maplestats_mcp.modules.statcan.wds.schemas import VectorSeries
from maplestats_mcp.modules.statcan.wds.transforms import FREQUENCY_PPY
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import NotFound
from maplestats_mcp.shared.i18n import normalize_lang, pick
from maplestats_mcp.shared.json_utils import list_or_empty
from maplestats_mcp.shared.models import Provenance
from maplestats_mcp.shared.transform import (
    PERIODS_PER_YEAR,
    Aggregation,
    Frequency,
    frequency_name,
    infer_periods_per_year,
    is_rate_unit,
    period_label,
    period_start,
    shift_months,
)

MAX_RANKED = 60
MAX_LATEST_N = 120
_VALET_URL = "https://www.bankofcanada.ca/valet/observations/{name}/json"
_VALET_URL_FR = "https://www.banqueducanada.ca/valet/observations/{name}/json"
# Valet's metadata.frequency words (seen live 2026-11-07: "Business daily",
# "Monthly"; French on the French domain) -> periods per year.
_VALET_PPY = {
    "monthly": 12,
    "mensuelle": 12,
    "mensuel": 12,
    "quarterly": 4,
    "trimestrielle": 4,
    "trimestriel": 4,
    "annual": 1,
    "annuelle": 1,
    "annuel": 1,
}


def _today() -> date:
    return datetime.now(ZoneInfo("America/Toronto")).date()


def _check_ref(ref: SeriesRef, lang: str) -> None:
    forms = [
        ref.vector_id is not None,
        bool(ref.product_id or ref.coordinate),
        bool(ref.boc_series),
    ]
    if sum(forms) != 1 or (forms[1] and not (ref.product_id and ref.coordinate)):
        raise compute.error(
            lang,
            "Each series needs exactly one of: vector_id (StatCan), product_id with "
            "coordinate (StatCan), or boc_series (Bank of Canada Valet).",
            "Chaque série exige exactement l'un de : vector_id (StatCan), product_id avec "
            "coordinate (StatCan) ou boc_series (Valet de la Banque du Canada).",
        )


# StatCan ---------------------------------------------------------------------------


async def _vector_id(ref: SeriesRef) -> int:
    if ref.vector_id is not None:
        return ref.vector_id
    info = await wds.get_series_info_from_cube_pid_coord(str(ref.product_id), str(ref.coordinate))
    return info.vector_id


def _full_units(value: float | None, multiplier: int) -> float | None:
    """value × 10^scalar factor, without float noise (21,104.8 thousand is 21,104,800)."""
    if value is None:
        return None
    return float(Decimal(str(value)) * multiplier)


def _statcan_loaded(series: VectorSeries, info: dict[str, Any] | None) -> Loaded:
    ctx = series.context
    multiplier = series.observations[0].scale_multiplier if series.observations else 1
    ppy = FREQUENCY_PPY.get(int(info.get("frequencyCode") or 0)) if info else None
    releases = [o.release_time for o in series.observations if o.release_time is not None]
    release = max(releases).date().isoformat() if releases else None
    if release is None and ctx is not None and ctx.table_release_time:
        release = ctx.table_release_time[:10]
    unit = ctx.unit if ctx else None
    input_series = InputSeries(
        source="statcan",
        id=f"v{series.vector_id}",
        label=ctx.series_title if ctx else None,
        geography=ctx.geography if ctx else None,
        citation=(
            ctx.citation
            if ctx and ctx.citation
            else f"Statistics Canada. Vector v{series.vector_id}."
        ),
        table_id=ctx.table_id if ctx else context.table_number(series.product_id),
        url=ctx.table_url if ctx else context.table_url(series.product_id),
        unit=unit,
        scale=ctx.scale if ctx else None,
        scale_multiplier=float(multiplier),
        frequency=(ctx.frequency if ctx and ctx.frequency else frequency_name(ppy)),
        periods_per_year=ppy,
        release=release,
    )
    points = [(o.ref_period, _full_units(o.value, o.scale_multiplier)) for o in series.observations]
    return Loaded(info=input_series, points=points, rate=is_rate_unit(unit))


async def load_statcan(
    vector_ids: list[int],
    *,
    first: date | None,
    last: date | None,
    latest_n: int | None,
    lang: str,
) -> tuple[dict[int, Loaded], list[int]]:
    """(series by vector id, vector ids WDS returned no data for)."""
    ids = list(dict.fromkeys(vector_ids))
    if latest_n is not None:
        data = await wds.get_data_from_vectors_and_latest_n_periods(ids, latest_n)
    else:
        start = (first or date(1900, 1, 1)).isoformat()
        end = (last or _today()).isoformat()
        data = await wds.get_data_from_vector_by_reference_period_range(ids, start, end)
    infos, (described, _) = await asyncio.gather(
        context.series_info_raw(ids), context.describe(data.series)
    )
    loaded = {s.vector_id: _statcan_loaded(s, infos.get(s.vector_id)) for s in described}
    return loaded, [f.vector_id for f in data.failed]


# Bank of Canada -----------------------------------------------------------------------


def _valet_ppy(frequency: str | None, days: list[date]) -> int | None:
    word = (frequency or "").strip().casefold()
    if word in _VALET_PPY:
        return _VALET_PPY[word]
    if "daily" in word or "quotidien" in word or "weekly" in word or "hebdo" in word:
        return None
    return infer_periods_per_year(days)


async def load_boc(
    name: str,
    *,
    first: date | None,
    last: date | None,
    recent: int | None,
    lang: str,
    whole_window: bool = False,
) -> Loaded:
    if recent is not None:
        result = await boc.get_observations([name], recent=recent, lang=lang)
    else:
        result = await boc.get_observations(
            [name],
            start_date=first.isoformat() if first else None,
            end_date=(last or _today()).isoformat(),
            lang=lang,
        )
    limits = result.provenance.limits or ""
    if whole_window and ("observation dates" in limits or "dates d'observation" in limits):
        raise compute.error(
            lang,
            f"The window holds more {name} observations than one Valet read returns, so the "
            "count would miss its start. Fix: shorten the window (start, end), for example to "
            "ten years of a daily series.",
            f"La fenêtre contient plus d'observations de {name} qu'une lecture Valet n'en "
            "renvoie : le compte manquerait le début. Correctif : raccourcissez la fenêtre "
            "(start, end), par exemple à dix ans pour une série quotidienne.",
        )
    info = result.series.get(name) or next(iter(result.series.values()), None)
    if info is None or not result.observations:
        raise compute.not_found(
            lang,
            f"Bank of Canada series {name} has no observations in the window. Fix: check the "
            "name (boc_search_series) and the window.",
            f"La série {name} de la Banque du Canada n'a aucune observation dans la fenêtre. "
            "Correctif : vérifiez le nom (boc_search_series) et la fenêtre.",
        )
    points = [(o.ref_date, o.values.get(name)) for o in result.observations if name in o.values]
    ppy = _valet_ppy(info.frequency, [d for d, _ in points])
    retrieved = datetime.now(UTC).date().isoformat()
    citation = pick(
        lang,
        f"Bank of Canada. Valet series {name}, {info.label}. Retrieved {retrieved}.",
        f"Banque du Canada. Série Valet {name}, {info.label}. Consulté le {retrieved}.",
    )
    input_series = InputSeries(
        source="boc",
        id=name,
        label=info.label,
        citation=citation,
        url=(_VALET_URL_FR if lang == "fr" else _VALET_URL).format(name=name),
        unit=info.unit,
        frequency=info.frequency or frequency_name(ppy, lang),
        periods_per_year=ppy,
    )
    rate = is_rate_unit(info.unit) if info.unit else False
    return Loaded(info=input_series, points=points, rate=rate)


# Shared -------------------------------------------------------------------------------


async def load(
    refs: list[SeriesRef],
    *,
    first: date | None,
    last: date | None,
    latest_n: int | None,
    lang: str,
    whole_window: bool = False,
) -> list[Loaded]:
    """Every ref, in order. A ref with no data raises NotFound naming it."""
    for ref in refs:
        _check_ref(ref, lang)
    statcan_refs = [r for r in refs if not r.boc_series]
    vector_ids = await asyncio.gather(*(_vector_id(r) for r in statcan_refs))
    by_vector: dict[int, Loaded] = {}
    failed: list[int] = []
    if vector_ids:
        by_vector, failed = await load_statcan(
            list(vector_ids), first=first, last=last, latest_n=latest_n, lang=lang
        )
    if failed:
        raise compute.not_found(
            lang,
            f"WDS returned no data for vector(s) {', '.join(f'v{v}' for v in failed)} in the "
            "window. Fix: check the vector (wds_get_series_info) and the window.",
            f"Le WDS n'a renvoyé aucune donnée pour le ou les vecteurs "
            f"{', '.join(f'v{v}' for v in failed)} dans la fenêtre. Correctif : vérifiez le "
            "vecteur (wds_get_series_info) et la fenêtre.",
        )
    boc_loaded = await asyncio.gather(
        *(
            load_boc(
                str(r.boc_series),
                first=first,
                last=last,
                recent=latest_n,
                lang=lang,
                whole_window=whole_window,
            )
            for r in refs
            if r.boc_series
        )
    )
    out: list[Loaded] = []
    statcan_iter = iter(vector_ids)
    boc_iter = iter(boc_loaded)
    for ref in refs:
        out.append(next(boc_iter) if ref.boc_series else by_vector[next(statcan_iter)])
    return out


def _with_values(series: Loaded, values: list[SeriesValue]) -> InputSeries:
    return series.info.model_copy(update={"values_used": values})


def _provenance(loaded: list[Loaded], schema: str, lang: str) -> Provenance:
    sources = {s.info.source for s in loaded}
    source = (
        "statcan-wds"
        if sources == {"statcan"}
        else "boc"
        if sources == {"boc"}
        else "statcan-wds,boc"
    )
    url = (
        "https://www150.statcan.gc.ca/t1/wds/rest/"
        if "statcan" in sources
        else (loaded[0].info.url if loaded else "https://www.bankofcanada.ca/valet/")
    )
    coverage = pick(
        lang,
        "Computed by MapleStats from the values just read from the source(s); each input "
        "series carries its own citation and the values used.",
        "Calculé par MapleStats à partir des valeurs lues à l'instant à la source ; chaque "
        "série d'entrée porte sa citation et les valeurs utilisées.",
    )
    if len(sources) > 1:
        coverage += pick(
            lang,
            " Statistics Canada values are under the Statistics Canada Open Licence; Bank of "
            "Canada values under the Bank's terms of use.",
            " Les valeurs de Statistique Canada relèvent de la Licence ouverte de Statistique "
            "Canada ; celles de la Banque du Canada, de ses conditions d'utilisation.",
        )
    return make_provenance(
        source=source,
        url=url,
        cached=False,
        schema_name=schema,
        coverage=coverage,
        lang=lang,
    )


def _check_frequency(frequency: str | None, lang: str) -> Frequency | None:
    if frequency is None or frequency in PERIODS_PER_YEAR:
        return frequency  # type: ignore[return-value]
    raise compute.error(
        lang,
        f"frequency={frequency!r}: use 'monthly', 'quarterly' or 'annual'.",
        f"frequency={frequency!r} : utilisez 'monthly', 'quarterly' ou 'annual'.",
    )


# Tools' entry points ---------------------------------------------------------------------


async def ratio(
    numerator: SeriesRef,
    denominator: SeriesRef,
    *,
    start: str | None,
    end: str | None,
    latest_n: int,
    frequency: str | None,
    aggregation: Aggregation,
    multiplier: float,
    lang: str,
) -> RatioResult:
    lang = normalize_lang(lang)
    wds.use_lang(lang)
    freq = _check_frequency(frequency, lang)
    if not 1 <= latest_n <= MAX_LATEST_N:
        raise compute.error(
            lang,
            f"latest_n must be 1 to {MAX_LATEST_N}.",
            f"latest_n doit aller de 1 à {MAX_LATEST_N}.",
        )
    if multiplier == 0:
        raise compute.error(lang, "multiplier must not be 0.", "multiplier ne doit pas valoir 0.")
    first, last = compute.window(start, end, lang)
    ranged = first is not None or last is not None
    if ranged:
        # Aggregating needs whole periods: read from the start of the first one.
        if freq is not None and first is not None:
            first = period_start(first, PERIODS_PER_YEAR[freq])
        loaded = await load(
            [numerator, denominator], first=first, last=last, latest_n=None, lang=lang
        )
    elif freq is None:
        # A dozen periods more than asked, so a series released a period later
        # still leaves `latest_n` periods in common.
        loaded = await load(
            [numerator, denominator], first=None, last=None, latest_n=latest_n + 12, lang=lang
        )
    else:
        years = latest_n * 12 // PERIODS_PER_YEAR[freq] // 12 + 2
        loaded = await load(
            [numerator, denominator],
            first=date(_today().year - years, 1, 1),
            last=None,
            latest_n=None,
            lang=lang,
        )
    num, den = loaded
    points, ppy, formula, notes = compute.ratio(
        num,
        den,
        multiplier=multiplier,
        frequency=freq,
        aggregation=aggregation,
        first=first,
        last=last,
        latest_n=latest_n,
        lang=lang,
    )
    used = {p.period for p in points}

    def values(series: Loaded) -> list[SeriesValue]:
        _, by_period = compute.periods(series, freq, aggregation, lang)
        return [
            SeriesValue(period=period_label(k, ppy), value=v)
            for k, v in sorted(by_period.items())
            if period_label(k, ppy) in used
        ]

    return RatioResult(
        numerator=_with_values(num, values(num)),
        denominator=_with_values(den, values(den)),
        frequency=frequency_name(ppy, lang),
        aggregation=aggregation if freq is not None else None,
        multiplier=multiplier,
        formula=formula,
        unit=compute.ratio_unit(num, den, multiplier, lang),
        points=points,
        notes=notes,
        provenance=_provenance(loaded, "calc.RatioResult", lang),
    )


async def _expand(
    product_id: str, coordinate: str, exclude: set[int], lang: str
) -> tuple[list[SeriesRef], dict[str, str]]:
    """One ref per member of the dimension marked '*' in `coordinate`, and each
    coordinate's member name."""
    parts = coordinate.split(".")
    stars = [i for i, p in enumerate(parts) if p.strip() == "*"]
    if len(stars) != 1:
        raise compute.error(
            lang,
            "coordinate needs exactly one '*', at the dimension to rank across (e.g. "
            "'*.7.1.1.1.1' ranks every Geography member of 14-10-0287).",
            "coordinate exige exactement un '*', à la dimension sur laquelle classer (p. ex. "
            "'*.7.1.1.1.1' classe chaque membre Géographie de 14-10-0287).",
        )
    position = stars[0] + 1
    pid = wds.normalize_product_id(product_id)
    cube, _ = await wds.cube_metadata_raw(pid)
    dimension = next(
        (
            d
            for d in list_or_empty(cube, "dimension")
            if int(d.get("dimensionPositionId", 0)) == position
        ),
        None,
    )
    if dimension is None:
        raise compute.error(
            lang,
            f"Table {context.table_number(pid)} has no dimension {position}.",
            f"Le tableau {context.table_number(pid)} n'a pas de dimension {position}.",
        )
    suffix = "Fr" if lang == "fr" else "En"
    refs: list[SeriesRef] = []
    names: dict[str, str] = {}
    for member in list_or_empty(dimension, "member"):
        member_id = int(member["memberId"])
        if member_id in exclude:
            continue
        parts[stars[0]] = str(member_id)
        coord = ".".join(parts)
        refs.append(SeriesRef(product_id=str(pid), coordinate=coord))
        names[coord] = member.get(f"memberName{suffix}") or member.get("memberNameEn") or coord
    if not refs:
        raise compute.error(lang, "Every member was excluded.", "Tous les membres ont été exclus.")
    if len(refs) > MAX_RANKED:
        raise compute.error(
            lang,
            f"That dimension has {len(refs)} members; at most {MAX_RANKED} are ranked in one "
            "call. Fix: exclude members (exclude_member_ids) or pass the series one by one.",
            f"Cette dimension compte {len(refs)} membres ; au plus {MAX_RANKED} sont classés "
            "par appel. Correctif : excluez des membres (exclude_member_ids) ou passez les "
            "séries une à une.",
        )
    return refs, names


async def rank(
    series: list[SeriesRef] | None,
    *,
    product_id: str | None,
    coordinate: str | None,
    exclude_member_ids: list[int] | None,
    period: str | None,
    order: str,
    frequency: str | None,
    aggregation: Aggregation,
    lang: str,
) -> RankResult:
    lang = normalize_lang(lang)
    wds.use_lang(lang)
    freq = _check_frequency(frequency, lang)
    member_names: dict[int, str] = {}
    if series and (product_id or coordinate):
        raise compute.error(
            lang,
            "Pass either series or product_id with coordinate, not both.",
            "Passez soit series, soit product_id avec coordinate, pas les deux.",
        )
    if product_id and coordinate:
        expanded, names = await _expand(product_id, coordinate, set(exclude_member_ids or []), lang)
        refs, member_names = await _existing(expanded, names, lang)
    elif series:
        refs = series
    else:
        raise compute.error(
            lang,
            "Give the series to rank: series (2 or more), or product_id with a coordinate "
            "holding one '*' at the dimension to rank across.",
            "Donnez les séries à classer : series (2 ou plus), ou product_id avec une "
            "coordinate portant un '*' à la dimension sur laquelle classer.",
        )
    if not 2 <= len(refs) <= MAX_RANKED:
        raise compute.error(
            lang,
            f"Ranking needs 2 to {MAX_RANKED} series, got {len(refs)}.",
            f"Le classement exige de 2 à {MAX_RANKED} séries, reçu {len(refs)}.",
        )
    if period:
        first, last = compute.window(period, period, lang)
        if freq is not None and first is not None:
            first = period_start(first, PERIODS_PER_YEAR[freq])
        loaded = await load(refs, first=first, last=last, latest_n=None, lang=lang)
    elif freq is None:
        loaded = await load(refs, first=None, last=None, latest_n=12, lang=lang)
    else:
        loaded = await load(
            refs, first=date(_today().year - 3, 1, 1), last=None, latest_n=None, lang=lang
        )
    for ref, item in zip(refs, loaded, strict=True):
        if ref.vector_id in member_names:
            item.member_name = member_names[ref.vector_id]
    unit = compute.check_units(loaded, lang)
    descending = order != "ascending"
    ranked, entries, ppy, notes = compute.rank(
        loaded,
        period=period,
        descending=descending,
        frequency=freq,
        aggregation=aggregation,
        lang=lang,
    )
    if any(s.info.scale_multiplier != 1 for s in loaded):
        notes.append(
            pick(
                lang,
                "Values are in full units (published value × scale factor).",
                "Valeurs en unités entières (valeur publiée × facteur d'échelle).",
            )
        )
    formula = pick(
        lang,
        f"Values for {ranked} sorted {'highest' if descending else 'lowest'} first; equal "
        "values share a rank and the next rank skips (1, 2, 2, 4)"
        + (f"; each value is the {aggregation.replace('_', ' ')} of the period" if freq else "")
        + ".",
        f"Valeurs de {ranked} triées de la plus {'élevée' if descending else 'faible'} à la "
        "plus " + ("faible" if descending else "élevée") + " ; les valeurs égales partagent un "
        "rang et le rang suivant est sauté (1, 2, 2, 4)"
        + (f" ; chaque valeur est {compute._AGG_FR[aggregation]} de la période" if freq else "")
        + ".",
    )
    return RankResult(
        period=ranked,
        order="descending" if descending else "ascending",
        frequency=frequency_name(ppy, lang),
        aggregation=aggregation if freq is not None else None,
        unit=unit,
        formula=formula,
        entries=entries,
        notes=notes,
        provenance=_provenance(loaded, "calc.RankResult", lang),
    )


async def _existing(
    refs: list[SeriesRef], names: dict[str, str], lang: str
) -> tuple[list[SeriesRef], dict[int, str]]:
    """The refs whose coordinate is a series in the table (a table need not hold
    every combination of members), as vector ids, with each one's member name.
    Fails only when none is."""

    async def one(ref: SeriesRef) -> tuple[int, str] | None:
        try:
            info = await wds.get_series_info_from_cube_pid_coord(
                str(ref.product_id), str(ref.coordinate)
            )
        except NotFound:
            return None
        return info.vector_id, names.get(str(ref.coordinate), str(ref.coordinate))

    found = [r for r in await asyncio.gather(*(one(r) for r in refs)) if r is not None]
    if not found:
        raise compute.not_found(
            lang,
            "No member of that dimension forms a series with the rest of the coordinate. Fix: "
            "check the coordinate with wds_get_cube_metadata.",
            "Aucun membre de cette dimension ne forme une série avec le reste de la "
            "coordonnée. Correctif : vérifiez la coordonnée avec wds_get_cube_metadata.",
        )
    return [SeriesRef(vector_id=v) for v, _ in found], dict(found)


async def growth(
    series: SeriesRef,
    *,
    start: str,
    end: str,
    frequency: str | None,
    aggregation: Aggregation,
    lang: str,
) -> GrowthResult:
    lang = normalize_lang(lang)
    wds.use_lang(lang)
    freq = _check_frequency(frequency, lang)
    first, last = compute.window(start, end, lang)
    if freq is not None and first is not None:
        first = period_start(first, PERIODS_PER_YEAR[freq])
    (loaded,) = await load([series], first=first, last=last, latest_n=None, lang=lang)
    first_key, last_key, start_value, end_value, years, ppy, notes = compute.cagr(
        loaded, start=start, end=end, frequency=freq, aggregation=aggregation, lang=lang
    )
    start_label, end_label = period_label(first_key, ppy), period_label(last_key, ppy)
    return GrowthResult(
        series=_with_values(
            loaded,
            [
                SeriesValue(period=start_label, value=start_value),
                SeriesValue(period=end_label, value=end_value),
            ],
        ),
        start_period=start_label,
        end_period=end_label,
        start_value=start_value,
        end_value=end_value,
        years=years,
        cagr_percent=compute.growth_rate(start_value, end_value, years),
        total_change_percent=(end_value / start_value - 1) * 100,
        frequency=frequency_name(ppy, lang),
        aggregation=aggregation if freq is not None else None,
        formula=compute.cagr_formula(loaded, start_label, end_label, years, ppy, lang),
        notes=notes,
        provenance=_provenance([loaded], "calc.GrowthResult", lang),
    )


async def count_changes(
    series: SeriesRef,
    *,
    start: str,
    end: str | None,
    threshold: float,
    lang: str,
) -> ChangeCountResult:
    lang = normalize_lang(lang)
    wds.use_lang(lang)
    if threshold < 0:
        raise compute.error(lang, "threshold must be 0 or more.", "threshold doit être 0 ou plus.")
    first, last = compute.window(start, end, lang)
    assert first is not None
    last = last or _today()
    # A year earlier: the last value before the window is the baseline its
    # first value is compared with (a quarterly series' is up to 3 months back).
    (loaded,) = await load(
        [series],
        first=shift_months(first, -12),
        last=last,
        latest_n=None,
        lang=lang,
        whole_window=True,
    )
    baseline, events, _, notes = compute.count_changes(
        loaded, first=first, last=last, threshold=threshold, lang=lang
    )
    if loaded.rate:
        change_unit = pick(lang, "percentage points", "points de pourcentage")
    else:
        change_unit = loaded.info.unit or pick(lang, "the series' unit", "l'unité de la série")
    used = ([baseline] if baseline else []) + [
        SeriesValue(period=e.period, value=e.value) for e in events
    ]
    increases = sum(1 for e in events if e.change > 0)
    ppy = loaded.info.periods_per_year
    end_label = period_label(period_start(last, ppy), ppy) if ppy else last.isoformat()
    start_label = period_label(period_start(first, ppy), ppy) if ppy else first.isoformat()
    formula = pick(
        lang,
        f"change = value − previous published value of {loaded.info.id}, for each value from "
        f"{start_label} to {end_label}; counted when |change| > {compute.number(threshold, lang)}.",
        f"variation = valeur − valeur publiée précédente de {loaded.info.id}, pour chaque "
        f"valeur de {start_label} à {end_label} ; comptée quand |variation| > "
        f"{compute.number(threshold, lang)}.",
    )
    return ChangeCountResult(
        series=_with_values(loaded, used),
        start=start_label,
        end=end_label,
        changes=len(events),
        increases=increases,
        decreases=len(events) - increases,
        threshold=threshold,
        change_unit=change_unit,
        baseline=baseline,
        events=events,
        formula=formula,
        notes=notes,
        provenance=_provenance([loaded], "calc.ChangeCountResult", lang),
    )


__all__ = ["count_changes", "growth", "load", "rank", "ratio"]

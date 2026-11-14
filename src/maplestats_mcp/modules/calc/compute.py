"""The arithmetic of the calc_ tools: published levels in, results with formulas out.

Pure functions, so every rule is tested without a network. client.py fetches
the series and hands them here as `Loaded` (values already in full units).

Rules every result relies on:

- Periods are aligned by calendar period, not by row: a gap in one series
  never pairs its next value with the other series' current one.
- A series is never silently converted to another frequency. Different
  frequencies are refused unless the caller names `frequency` (and an
  `aggregation`), which converts both with shared/transform.aggregate: a
  period needs all of its sub-periods to have a value.
- Units are compared as published. A ratio of an index (2002=100) to anything
  but the same index, or of current dollars to constant or chained dollars,
  is refused; a ranking needs every series in one unit.
- Values are multiplied by their StatCan scalar factor first, so a series in
  thousands and one in units divide correctly.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from maplestats_mcp.modules.calc.schemas import (
    ChangeEvent,
    InputSeries,
    RankEntry,
    RatioPoint,
    SeriesValue,
)
from maplestats_mcp.shared.errors import InvalidInput, NotFound
from maplestats_mcp.shared.fr_typography import lang_error
from maplestats_mcp.shared.i18n import pick
from maplestats_mcp.shared.transform import (
    PERIODS_PER_YEAR,
    Aggregation,
    Frequency,
    aggregate,
    frequency_name,
    parse_period,
    period_end,
    period_label,
    period_start,
)

_INDEX_UNIT = re.compile(r"=\s*100\b|\bindex\b|\bindice\b", re.IGNORECASE)
_REAL_DOLLARS = re.compile(r"constant|chained|encha[iî]n", re.IGNORECASE)
_DOLLARS = re.compile(r"dollar", re.IGNORECASE)
# StatCan units that name the scale ("Persons in thousands"): the values here
# are already in full units, so the scale words would misstate the result's unit.
_SCALE_WORDS = re.compile(
    r"\s*(?:\bin\s+(?:thousands|millions|billions)|\ben\s+(?:milliers|millions|milliards))\b",
    re.IGNORECASE,
)
# Two published values whose difference is below this are equal: StatCan and
# Valet publish at most 6 decimals, and a float subtraction leaves noise at 1e-15.
_EQUAL = 1e-9


@dataclass
class Loaded:
    """A series as read: its citation block and its (date, full-unit value) points."""

    info: InputSeries
    points: list[tuple[date, float | None]]
    rate: bool = False
    member_name: str | None = None
    notes: list[str] = field(default_factory=list)


def error(lang: str, en: str, fr: str) -> InvalidInput:
    return lang_error(InvalidInput, lang, en, fr)


def not_found(lang: str, en: str, fr: str) -> NotFound:
    return lang_error(NotFound, lang, en, fr)


def number(value: float, lang: str) -> str:
    """1,000 / 1 000; 0.25; 12."""
    if float(value).is_integer():
        text = f"{int(value):,}"
    else:
        text = f"{value:,.10g}"
    return text.replace(",", " ").replace(".", ",") if lang == "fr" else text


def same_unit(a: str | None, b: str | None) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


# Periods -------------------------------------------------------------------------


def periods(
    series: Loaded, frequency: Frequency | None, aggregation: Aggregation, lang: str
) -> tuple[int | None, dict[date, float | None]]:
    """(periods per year, value by period start) for the series, aggregated
    to `frequency` when one is named."""
    source_ppy = series.info.periods_per_year
    if frequency is not None:
        target = PERIODS_PER_YEAR[frequency]
        if source_ppy == target:
            return target, {period_start(d, target): v for d, v in series.points}
        levels, _ = aggregate(series.points, source_ppy, target, aggregation, lang)
        return target, dict(levels)
    if source_ppy is None:
        return None, dict(series.points)
    return source_ppy, {period_start(d, source_ppy): v for d, v in series.points}


def check_frequencies(loaded: Sequence[Loaded], frequency: Frequency | None, lang: str) -> None:
    """Every series must share one frequency unless `frequency` converts them."""
    if frequency is not None:
        too_coarse = [
            s
            for s in loaded
            if s.info.periods_per_year is not None
            and s.info.periods_per_year < PERIODS_PER_YEAR[frequency]
        ]
        if too_coarse:
            s = too_coarse[0]
            raise error(
                lang,
                f"{s.info.id} is {frequency_name(s.info.periods_per_year)} and cannot be "
                f"converted to {frequency}. Fix: pass a frequency no finer than every series "
                "(annual is always possible).",
                f"{s.info.id} est de fréquence {frequency_name(s.info.periods_per_year, 'fr')} "
                f"et ne peut pas être convertie en {frequency}. Correctif : choisissez une "
                "fréquence pas plus fine que celle de chaque série (annual convient toujours).",
            )
        return
    kinds = {s.info.periods_per_year for s in loaded}
    if len(kinds) > 1:
        listed = ", ".join(f"{s.info.id} {frequency_name(s.info.periods_per_year)}" for s in loaded)
        listed_fr = ", ".join(
            f"{s.info.id} {frequency_name(s.info.periods_per_year, 'fr')}" for s in loaded
        )
        raise error(
            lang,
            f"The series do not share a frequency ({listed}); MapleStats does not guess how to "
            "line them up. Fix: pass frequency='annual' (or 'quarterly') with aggregation "
            "('average' for rates, prices and indexes; 'sum' for flows such as sales; "
            "'end_of_period' for stocks), or choose series of one frequency.",
            f"Les séries n'ont pas la même fréquence ({listed_fr}) ; MapleStats ne devine pas "
            "comment les aligner. Correctif : passez frequency='annual' (ou 'quarterly') avec "
            "aggregation ('average' pour les taux, prix et indices ; 'sum' pour les flux comme "
            "les ventes ; 'end_of_period' pour les stocks), ou choisissez des séries de même "
            "fréquence.",
        )


def window(start: str | None, end: str | None, lang: str) -> tuple[date | None, date | None]:
    """First and last day covered by `start` and `end` (2024, 2024-07, 2024-Q2, 2024-07-15)."""

    def parse(text: str, name: str, last: bool) -> date:
        try:
            first, ppy = parse_period(text)
        except ValueError:
            raise error(
                lang,
                f"{name}={text!r} is not a period: write 2024, 2024-07, 2024-Q2 or 2024-07-15.",
                f"{name}={text!r} n'est pas une période : écrivez 2024, 2024-07, 2024-Q2 ou "
                "2024-07-15.",
            ) from None
        return period_end(first, ppy) if last and ppy else first

    first = parse(start, "start", False) if start else None
    last = parse(end, "end", True) if end else None
    if first and last and first > last:
        raise error(
            lang,
            f"start ({start}) is after end ({end}).",
            f"start ({start}) est postérieur à end ({end}).",
        )
    return first, last


def label(start: date, ppy: int | None) -> str:
    return period_label(start, ppy)


# Ratio ---------------------------------------------------------------------------


def unit_clash(numerator: Loaded, denominator: Loaded, lang: str) -> None:
    """Refuse units whose ratio has no meaning."""
    a, b = numerator.info.unit, denominator.info.unit
    if not a or not b or same_unit(a, b):
        return
    if _INDEX_UNIT.search(a) or _INDEX_UNIT.search(b):
        raise error(
            lang,
            f"{numerator.info.id} is in {a!r} and {denominator.info.id} in {b!r}: an index "
            "has no level, so its ratio to another unit means nothing. Fix: divide two "
            "indexes with the same base, or use the dollar or count series the index is "
            "built from.",
            f"{numerator.info.id} est en {a!r} et {denominator.info.id} en {b!r} : un indice "
            "n'a pas de niveau, son rapport à une autre unité n'a pas de sens. Correctif : "
            "divisez deux indices de même base, ou utilisez les séries en dollars ou en "
            "nombres d'où vient l'indice.",
        )
    if (
        _DOLLARS.search(a)
        and _DOLLARS.search(b)
        and (_REAL_DOLLARS.search(a) or _REAL_DOLLARS.search(b))
    ):
        raise error(
            lang,
            f"{numerator.info.id} is in {a!r} and {denominator.info.id} in {b!r}: current and "
            "constant (or chained) dollars, or two base years, do not divide. Fix: pick both "
            "series in current dollars, or both in the same constant dollars.",
            f"{numerator.info.id} est en {a!r} et {denominator.info.id} en {b!r} : des dollars "
            "courants et constants (ou enchaînés), ou deux années de base, ne se divisent pas. "
            "Correctif : prenez les deux séries en dollars courants, ou dans les mêmes dollars "
            "constants.",
        )


def full_unit(series: Loaded) -> str | None:
    unit = series.info.unit
    if unit and series.info.scale_multiplier != 1:
        return _SCALE_WORDS.sub("", unit).strip() or unit
    return unit


def ratio_unit(numerator: Loaded, denominator: Loaded, multiplier: float, lang: str) -> str:
    a, b = full_unit(numerator), full_unit(denominator)
    times = "" if multiplier == 1 else f" × {number(multiplier, lang)}"
    if not a or not b:
        return pick(
            lang,
            f"ratio{times} (a unit is not published for one series)",
            f"rapport{times} (l'unité d'une série n'est pas publiée)",
        )
    if same_unit(a, b):
        if multiplier == 100:
            return pick(lang, "percent", "pour cent")
        return pick(lang, f"ratio{times} (both in {a})", f"rapport{times} (les deux en {a})")
    return pick(lang, f"{a} per {b}{times}", f"{a} par {b}{times}")


def _scaled(series: Loaded, lang: str) -> str:
    mult = series.info.scale_multiplier
    if mult == 1:
        return series.info.id
    return f"{series.info.id} × {number(mult, lang)}"


def ratio(
    numerator: Loaded,
    denominator: Loaded,
    *,
    multiplier: float,
    frequency: Frequency | None,
    aggregation: Aggregation,
    first: date | None,
    last: date | None,
    latest_n: int,
    lang: str,
) -> tuple[list[RatioPoint], int | None, str, list[str]]:
    """(points, periods per year, formula, notes)."""
    check_frequencies([numerator, denominator], frequency, lang)
    unit_clash(numerator, denominator, lang)
    ppy, num = periods(numerator, frequency, aggregation, lang)
    _, den = periods(denominator, frequency, aggregation, lang)
    keys = sorted(set(num) & set(den))
    if first is not None or last is not None:
        low = period_start(first, ppy) if first is not None and ppy else first
        keys = [k for k in keys if (low is None or k >= low) and (last is None or k <= last)]
    else:
        both = [k for k in keys if num[k] is not None and den[k] is not None]
        keys = both[-latest_n:]
    if not keys:
        raise not_found(
            lang,
            f"{numerator.info.id} and {denominator.info.id} have no period in common with a "
            "value in the window. Fix: widen the window (start, end) or check that both "
            "series cover it.",
            f"{numerator.info.id} et {denominator.info.id} n'ont aucune période commune avec "
            "une valeur dans la fenêtre. Correctif : élargissez la fenêtre (start, end) ou "
            "vérifiez que les deux séries la couvrent.",
        )
    points: list[RatioPoint] = []
    for key in keys:
        a, b = num[key], den[key]
        value = None
        if a is not None and b is not None and b != 0:
            value = a / b * multiplier
        points.append(RatioPoint(period=label(key, ppy), numerator=a, denominator=b, value=value))
    times = "" if multiplier == 1 else f" × {number(multiplier, lang)}"
    agg = (
        pick(
            lang,
            f", each the {aggregation.replace('_', ' ')} of its values in the period",
            f", chacune étant {_AGG_FR[aggregation]} de ses valeurs sur la période",
        )
        if frequency is not None
        and (numerator.info.periods_per_year != ppy or denominator.info.periods_per_year != ppy)
        else ""
    )
    formula = pick(
        lang,
        f"value = ({_scaled(numerator, lang)}) ÷ ({_scaled(denominator, lang)}){times}, "
        f"period by period ({frequency_name(ppy)}{agg}); null when either is missing or the "
        "denominator is 0.",
        f"valeur = ({_scaled(numerator, lang)}) ÷ ({_scaled(denominator, lang)}){times}, "
        f"période par période (fréquence {frequency_name(ppy, 'fr')}{agg}) ; nulle quand "
        "l'une manque ou que le dénominateur vaut 0.",
    )
    notes: list[str] = []
    if any(s.info.scale_multiplier != 1 for s in (numerator, denominator)):
        notes.append(
            pick(
                lang,
                "Published values were multiplied by their scale factor first (numerator and "
                "denominator columns are in full units).",
                "Les valeurs publiées ont d'abord été multipliées par leur facteur d'échelle "
                "(les colonnes numérateur et dénominateur sont en unités entières).",
            )
        )
    if numerator.rate and denominator.rate:
        notes.append(
            pick(
                lang,
                "Both series are rates: this is how many times one is the other, not their "
                "difference in percentage points.",
                "Les deux séries sont des taux : c'est le nombre de fois que l'un fait l'autre, "
                "pas leur écart en points de pourcentage.",
            )
        )
    if ppy is None:
        notes.append(
            pick(
                lang,
                "Daily or irregular series: values were paired by exact date.",
                "Séries quotidiennes ou irrégulières : valeurs appariées par date exacte.",
            )
        )
    return points, ppy, formula, notes


_AGG_FR = {"average": "la moyenne", "sum": "la somme", "end_of_period": "la dernière valeur"}


# Ranking ---------------------------------------------------------------------------


def check_units(loaded: Sequence[Loaded], lang: str) -> str:
    units = {(s.info.unit or "").strip().casefold() for s in loaded}
    if len(units) > 1:
        listed = "; ".join(f"{s.info.id}: {s.info.unit or '?'}" for s in loaded)
        raise error(
            lang,
            f"The series are not in one unit ({listed}), so their values do not rank. Fix: "
            "choose the same measure for every place.",
            f"Les séries ne sont pas dans la même unité ({listed}) : leurs valeurs ne se "
            "classent pas. Correctif : choisissez la même mesure pour chaque lieu.",
        )
    unit = loaded[0].info.unit if loaded else None
    return unit or pick(lang, "unit not published", "unité non publiée")


def rank(
    loaded: Sequence[Loaded],
    *,
    period: str | None,
    descending: bool,
    frequency: Frequency | None,
    aggregation: Aggregation,
    lang: str,
) -> tuple[str, list[RankEntry], int | None, list[str]]:
    """(period ranked, entries, periods per year, notes)."""
    check_frequencies(loaded, frequency, lang)
    by_series = [periods(s, frequency, aggregation, lang) for s in loaded]
    ppy = by_series[0][0]
    notes: list[str] = []
    if period:
        try:
            first, given_ppy = parse_period(period)
        except ValueError:
            raise error(
                lang,
                f"period={period!r} is not a period: write 2024, 2024-07, 2024-Q2 or 2024-07-15.",
                f"period={period!r} n'est pas une période : écrivez 2024, 2024-07, 2024-Q2 ou "
                "2024-07-15.",
            ) from None
        if ppy == 6 and given_ppy == 12:
            # parse_period has no bimonthly form (it never returns 6), so a month
            # names the two-month period that contains it.
            first, given_ppy = period_start(first, 6), 6
        if given_ppy != ppy:
            raise error(
                lang,
                f"period={period!r} is {frequency_name(given_ppy)} but the series are "
                f"{frequency_name(ppy)}. Fix: give a period of that frequency, or pass "
                "frequency (with aggregation) to rank, for example, annual averages.",
                f"period={period!r} est de fréquence {frequency_name(given_ppy, 'fr')}, les "
                f"séries de fréquence {frequency_name(ppy, 'fr')}. Correctif : donnez une "
                "période de cette fréquence, ou passez frequency (avec aggregation) pour "
                "classer, par exemple, des moyennes annuelles.",
            )
        key = first
    else:
        # The latest period the most series have a value for: one series released
        # a month ahead must not leave all the others unranked.
        counts: dict[date, int] = {}
        for _, values in by_series:
            for day, value in values.items():
                if value is not None:
                    counts[day] = counts.get(day, 0) + 1
        if not counts:
            raise not_found(
                lang,
                "None of the series has a value in the periods read.",
                "Aucune série n'a de valeur dans les périodes lues.",
            )
        best = max(counts.values())
        key = max(day for day, n in counts.items() if n == best)
        if any(day > key for day in counts):
            notes.append(
                pick(
                    lang,
                    f"Ranked {label(key, ppy)}, the latest period every series with data "
                    "has; some series have a later value (see each series' values_used).",
                    f"Classement de {label(key, ppy)}, dernière période commune aux séries "
                    "ayant des données ; certaines ont une valeur plus récente.",
                )
            )
    values = [(s, vals.get(key)) for s, (_, vals) in zip(loaded, by_series, strict=True)]
    present = sorted(
        ((s, v) for s, v in values if v is not None),
        key=lambda pair: pair[1],
        reverse=descending,
    )
    entries: list[RankEntry] = []
    previous: float | None = None
    current_rank = 0
    for position, (s, v) in enumerate(present, start=1):
        if previous is None or abs(v - previous) > _EQUAL * max(1.0, abs(v)):
            current_rank = position
        previous = v
        entries.append(_entry(s, current_rank, v, key, ppy))
    missing = [s for s, v in values if v is None]
    for s in missing:
        entries.append(_entry(s, None, None, key, ppy))
    if missing:
        notes.append(
            pick(
                lang,
                f"No value for {label(key, ppy)}: {', '.join(_name(s) for s in missing)} "
                "(not published, suppressed, or not yet released).",
                f"Aucune valeur pour {label(key, ppy)} : {', '.join(_name(s) for s in missing)} "
                "(non publiée, confidentielle ou pas encore diffusée).",
            )
        )
    return label(key, ppy), entries, ppy, notes


def _name(series: Loaded) -> str:
    return series.member_name or series.info.geography or series.info.label or series.info.id


def _entry(
    series: Loaded, rank_: int | None, value: float | None, key: date, ppy: int | None
) -> RankEntry:
    info = series.info.model_copy(
        update={"values_used": [SeriesValue(period=label(key, ppy), value=value)]}
    )
    return RankEntry(rank=rank_, label=_name(series), value=value, series=info)


# Compound annual growth ---------------------------------------------------------------


def cagr(
    series: Loaded,
    *,
    start: str,
    end: str,
    frequency: Frequency | None,
    aggregation: Aggregation,
    lang: str,
) -> tuple[date, date, float, float, float, int | None, list[str]]:
    """(start key, end key, start value, end value, years, periods per year, notes)."""
    if series.rate:
        raise error(
            lang,
            f"{series.info.id} is a percentage or a rate ({series.info.unit}); compound growth "
            "of a rate is not meaningful. Fix: report the change in percentage points (the "
            "series tools' transform='diff' or 'yoy_diff'), or take the growth of the level "
            "the rate is computed from.",
            f"{series.info.id} est un pourcentage ou un taux ({series.info.unit}) ; la "
            "croissance composée d'un taux n'a pas de sens. Correctif : donnez la variation en "
            "points de pourcentage (transform='diff' ou 'yoy_diff' des outils de séries), ou "
            "la croissance du niveau d'où vient le taux.",
        )
    ppy, values = periods(series, frequency, aggregation, lang)
    keys: list[date] = []
    for text, name in ((start, "start"), (end, "end")):
        try:
            first, given_ppy = parse_period(text)
        except ValueError:
            raise error(
                lang,
                f"{name}={text!r} is not a period: write 2024, 2024-07, 2024-Q2 or 2024-07-15.",
                f"{name}={text!r} n'est pas une période : écrivez 2024, 2024-07, 2024-Q2 ou "
                "2024-07-15.",
            ) from None
        if ppy == 6 and given_ppy == 12:
            # Same as rank: a month names the bimonthly period that contains it.
            first, given_ppy = period_start(first, 6), 6
        if given_ppy != ppy:
            raise error(
                lang,
                f"{name}={text!r} is {frequency_name(given_ppy)} but {series.info.id} is "
                f"{frequency_name(ppy)} here. Fix: give a period of that frequency, or pass "
                "frequency='annual' (with aggregation='average' for prices and indexes, 'sum' "
                "for flows) to compare annual figures.",
                f"{name}={text!r} est de fréquence {frequency_name(given_ppy, 'fr')}, "
                f"{series.info.id} de fréquence {frequency_name(ppy, 'fr')} ici. Correctif : "
                "donnez une période de cette fréquence, ou passez frequency='annual' (avec "
                "aggregation='average' pour les prix et indices, 'sum' pour les flux).",
            )
        keys.append(first)
    first_key, last_key = keys
    if last_key <= first_key:
        raise error(
            lang,
            f"end ({end}) must be after start ({start}).",
            f"end ({end}) doit être postérieur à start ({start}).",
        )
    found: list[float] = []
    for key, text in ((first_key, start), (last_key, end)):
        value = values.get(key)
        if value is None:
            raise not_found(
                lang,
                f"{series.info.id} has no value for {text}"
                + (" (a period missing a sub-period cannot be aggregated)" if frequency else "")
                + ". Fix: choose periods the series covers.",
                f"{series.info.id} n'a pas de valeur pour {text}"
                + (" (une période incomplète ne peut pas être agrégée)" if frequency else "")
                + ". Correctif : choisissez des périodes que la série couvre.",
            )
        if value <= 0:
            raise error(
                lang,
                f"{series.info.id} is {value} in {text}: compound growth needs positive values.",
                f"{series.info.id} vaut {value} en {text} : la croissance composée exige des "
                "valeurs positives.",
            )
        found.append(value)
    if ppy is None:
        years = (last_key - first_key).days / 365.25
    else:
        steps = (last_key.year - first_key.year) * ppy + (
            (last_key.month - 1) // (12 // ppy) - (first_key.month - 1) // (12 // ppy)
        )
        years = steps / ppy
    notes: list[str] = []
    if years < 1:
        notes.append(
            pick(
                lang,
                f"The periods are {number(round(years, 4), lang)} years apart: the annual rate "
                "extrapolates a change shorter than a year.",
                f"Les périodes sont à {number(round(years, 4), lang)} an d'écart : le taux "
                "annuel extrapole une variation de moins d'un an.",
            )
        )
    return first_key, last_key, found[0], found[1], years, ppy, notes


def cagr_formula(
    series: Loaded, start: str, end: str, years: float, ppy: int | None, lang: str
) -> str:
    if ppy is None:
        span = pick(lang, "days apart ÷ 365.25", "jours d'écart ÷ 365,25")
    elif ppy == 1:
        span = pick(lang, "years apart", "années d'écart")
    else:
        span = pick(
            lang,
            f"{frequency_name(ppy)} periods apart ÷ {ppy}",
            f"périodes d'écart ÷ {ppy} (fréquence {frequency_name(ppy, 'fr')})",
        )
    return pick(
        lang,
        f"CAGR = ((value {end} ÷ value {start})^(1 ÷ years) − 1) × 100, years = "
        f"{number(round(years, 6), lang)} ({span}), values of {series.info.id}.",
        f"TCAC = ((valeur {end} ÷ valeur {start})^(1 ÷ années) − 1) × 100, années = "
        f"{number(round(years, 6), lang)} ({span}), valeurs de {series.info.id}.",
    )


def growth_rate(start_value: float, end_value: float, years: float) -> float:
    return (math.pow(end_value / start_value, 1 / years) - 1) * 100


# Count of changes -------------------------------------------------------------------


def count_changes(
    series: Loaded,
    *,
    first: date,
    last: date,
    threshold: float,
    lang: str,
) -> tuple[SeriesValue | None, list[ChangeEvent], int, list[str]]:
    """(baseline, events, missing values skipped, notes).

    Each value in the window is compared with the previous published value
    (the last one before the window for the first): a missing value is
    skipped, never read as a change to and from zero.
    """
    ppy = series.info.periods_per_year
    points = sorted(series.points, key=lambda p: p[0])
    before = [(d, v) for d, v in points if d < first and v is not None]
    baseline = (
        SeriesValue(period=label(*_lab(before[-1][0], ppy)), value=before[-1][1])
        if before
        else None
    )
    previous = before[-1][1] if before else None
    events: list[ChangeEvent] = []
    skipped = 0
    for day, value in points:
        if day < first or day > last:
            continue
        if value is None:
            skipped += 1
            continue
        if previous is not None:
            change = round(value - previous, 10)
            if abs(change) > threshold + _EQUAL * max(1.0, abs(value)):
                events.append(
                    ChangeEvent(
                        period=label(*_lab(day, ppy)),
                        previous=previous,
                        value=value,
                        change=change,
                    )
                )
        previous = value
    notes: list[str] = []
    if baseline is None:
        notes.append(
            pick(
                lang,
                "No value before the window was found, so the window's first value is the "
                "starting point and cannot itself count as a change.",
                "Aucune valeur antérieure à la fenêtre : sa première valeur sert de point de "
                "départ et ne peut pas compter comme variation.",
            )
        )
    if skipped:
        notes.append(
            pick(
                lang,
                f"{skipped} missing value(s) in the window were skipped: each value is compared "
                "with the last published one before it.",
                f"{skipped} valeur(s) manquante(s) dans la fenêtre ignorée(s) : chaque valeur "
                "est comparée à la dernière publiée avant elle.",
            )
        )
    return baseline, events, skipped, notes


def _lab(day: date, ppy: int | None) -> tuple[date, int | None]:
    return (period_start(day, ppy), ppy) if ppy else (day, None)

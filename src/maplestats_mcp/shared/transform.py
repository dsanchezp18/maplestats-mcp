"""Transformations MapleStats computes on a published time series.

Pure functions: published levels in, computed values out, with the formula
and unit written next to them. Used by the StatCan WDS and SDMX tools and
the Bank of Canada observation tool; the reproduce_code scripts apply the
same formulas (reproduce/builders.py).

Rules every caller relies on:

- A missing level gives a missing result (None), never 0.
- Lags are calendar periods, not rows: year-over-year compares a period
  with the same period a year earlier, found by date, so a gap in the
  data cannot shift the comparison onto another period.
- Percent change of a series that is already a percentage or a rate
  (an unemployment rate, a bond yield) is misleading; for such series the
  change is given in percentage points instead, and the result says so.
- Differences are in the series' own units as published (StatCan values
  are unscaled, so a difference is in the unit its scalar factor names);
  percent changes and indexes do not depend on the scale.
- A moving average is trailing (the period and the window - 1 before it,
  found by date) and null when any of them is missing: a gap never gives a
  shorter window. It is in the series' own unit, rates included.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.fr_typography import lang_error
from maplestats_mcp.shared.i18n import pick

Transform = Literal[
    "level",
    "diff",
    "pct_change",
    "yoy_diff",
    "yoy_pct_change",
    "annualized_pct_change",
    "index",
    "moving_average",
]
Frequency = Literal["monthly", "quarterly", "annual"]
Aggregation = Literal["average", "sum", "end_of_period"]

PERIODS_PER_YEAR: dict[str, int] = {"monthly": 12, "quarterly": 4, "annual": 1}
_FREQUENCY_NAMES = {
    12: ("monthly", "mensuelle"),
    6: ("bimonthly", "aux deux mois"),
    4: ("quarterly", "trimestrielle"),
    2: ("semi-annual", "semestrielle"),
    1: ("annual", "annuelle"),
}
_PERIOD_WORDS = {
    12: ("months", "mois"),
    6: ("two-month periods", "périodes de deux mois"),
    4: ("quarters", "trimestres"),
    2: ("half-years", "semestres"),
    1: ("years", "années"),
}
# A percent change of a percentage or rate becomes a change in percentage points.
_POINTS_INSTEAD = {
    "pct_change": "diff",
    "yoy_pct_change": "yoy_diff",
    "annualized_pct_change": "diff",
}
_NEEDS_CALENDAR = {"yoy_diff", "yoy_pct_change", "annualized_pct_change", "moving_average"}
# Ten years of months: a longer moving average is a trend, not a smoothing,
# and only multiplies the history fetched.
MAX_WINDOW = 120
# Daily data: a month whose first or last observation is further than this
# from the month's edge was cut by the requested window (or is still running).
_EDGE_DAYS = 4


@dataclass(frozen=True)
class TransformRequest:
    """A tool's transform arguments, passed together to the code that fetches and computes."""

    transform: Transform = "level"
    frequency: Frequency | None = None
    aggregation: Aggregation = "average"
    index_base: str | None = None
    window: int | None = None

    @property
    def active(self) -> bool:
        return (
            self.transform != "level"
            or self.frequency is not None
            or bool(self.index_base)
            or self.window is not None
        )

    def check(self, lang: str = "en") -> None:
        """Reject a bad `window` before any history is fetched for it."""
        check_window(self.transform, self.window, lang)


class TransformedPoint(BaseModel):
    period: str = Field(
        description="The period: 2026-09 (month), 2026-Q3, 2026-S2, 2026, or a date for daily data."
    )
    ref_date: date = Field(description="First day of the period (the date itself for daily data).")
    level: float | None = Field(
        description=(
            "The level the value is computed from: as published, or the aggregate named in "
            "`aggregation`. Null when missing."
        )
    )
    value: float | None = Field(
        description="Computed by MapleStats with `formula`; null when an input is missing."
    )


class TransformedSeries(BaseModel):
    """Values computed by MapleStats from the published levels (which stay in the
    tool's own observations, unchanged)."""

    requested_transform: str = Field(description="The transform asked for.")
    transform: str = Field(
        description=(
            "The transform applied: differs from requested_transform only when a percent change "
            "was asked of a percentage or rate (then a percentage-point difference; see notes)."
        )
    )
    frequency: str = Field(description="Frequency of the points (after any aggregation).")
    periods_per_year: int | None = Field(
        default=None,
        description="12 monthly, 4 quarterly, 1 annual...; null for daily, weekly or irregular.",
    )
    source_periods_per_year: int | None = Field(
        default=None, description="Periods per year of the series as published."
    )
    aggregation: str | None = Field(
        default=None,
        description="How published values were combined into each period, if they were.",
    )
    window: int | None = Field(
        default=None, description="Periods in each moving average (transform moving_average)."
    )
    formula: str = Field(description="Exactly how each value was computed.")
    unit: str = Field(description="Unit of `value`.")
    notes: list[str] = Field(default_factory=list)
    points: list[TransformedPoint]


def _error(lang: str, en: str, fr: str) -> InvalidInput:
    return lang_error(InvalidInput, lang, en, fr)


def check_window(transform: str, window: int | None, lang: str = "en") -> None:
    """`window` goes with transform='moving_average' and only with it, 2 to MAX_WINDOW."""
    if transform == "moving_average":
        if window is None or not 2 <= window <= MAX_WINDOW:
            raise _error(
                lang,
                f"transform='moving_average' needs window, the number of periods averaged, "
                f"from 2 to {MAX_WINDOW} (e.g. window=3 with frequency='annual' for a 3-year "
                "moving average).",
                f"transform='moving_average' exige window, le nombre de périodes de la moyenne, "
                f"de 2 à {MAX_WINDOW} (p. ex. window=3 avec frequency='annual' pour une moyenne "
                "mobile sur 3 ans).",
            )
    elif window is not None:
        raise _error(
            lang,
            "window only applies to transform='moving_average'.",
            "window ne s'applique qu'à transform='moving_average'.",
        )


# Periods -----------------------------------------------------------------------

_PERIOD = re.compile(r"^(\d{4})(?:-(?:(\d{2})(?:-(\d{2}))?|([QSW])(\d{1,2})))?$")


def parse_period(text: str) -> tuple[date, int | None]:
    """(first day, periods per year) of a period written 2026, 2026-07, 2026-Q3,
    2026-S2, 2026-W12 or 2026-07-15. Periods per year is None for a day or a week.
    Raises ValueError for anything else."""
    match = _PERIOD.match(text.strip())
    if not match:
        raise ValueError(text)
    year = int(match.group(1))
    month, day, kind, number = match.group(2), match.group(3), match.group(4), match.group(5)
    if day:
        return date(year, int(month), int(day)), None
    if month:
        return date(year, int(month), 1), 12
    if kind == "Q" and 1 <= int(number) <= 4:
        return date(year, 3 * int(number) - 2, 1), 4
    if kind == "S" and 1 <= int(number) <= 2:
        return date(year, 6 * int(number) - 5, 1), 2
    if kind == "W":
        return date.fromisocalendar(year, int(number), 1), None
    if kind is None:
        return date(year, 1, 1), 1
    raise ValueError(text)


def period_start(day: date, ppy: int) -> date:
    months = 12 // ppy
    return date(day.year, (day.month - 1) // months * months + 1, 1)


def shift_months(day: date, months: int) -> date:
    """The first of the month `months` after (or before, if negative) `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def period_end(start: date, ppy: int) -> date:
    return shift_months(start, 12 // ppy) - timedelta(days=1)


def period_label(start: date, ppy: int | None) -> str:
    if ppy is None:
        return start.isoformat()
    if ppy == 1:
        return f"{start.year}"
    if ppy == 4:
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    if ppy == 2:
        return f"{start.year}-S{(start.month - 1) // 6 + 1}"
    return f"{start.year}-{start.month:02d}"


def _key(start: date, ppy: int) -> int:
    return start.year * ppy + (start.month - 1) // (12 // ppy)


def frequency_name(ppy: int | None, lang: str = "en") -> str:
    if ppy in _FREQUENCY_NAMES:
        en, fr = _FREQUENCY_NAMES[ppy]
        return pick(lang, en, fr)
    return pick(lang, "daily, weekly or irregular", "quotidienne, hebdomadaire ou irrégulière")


def infer_periods_per_year(days: Sequence[date]) -> int | None:
    """Periods per year from the spacing of the dates (median gap); None for
    daily, weekly or too few dates."""
    ordered = sorted(set(days))
    gaps = sorted((b - a).days for a, b in pairwise(ordered))
    if not gaps:
        return None
    gap = gaps[len(gaps) // 2]
    for ppy, low, high in ((12, 27, 32), (6, 58, 63), (4, 88, 93), (2, 180, 185), (1, 364, 367)):
        if low <= gap <= high:
            return ppy
    return None


# History a transform needs ---------------------------------------------------------


def lag_periods(transform: str, ppy: int | None, window: int | None = None) -> int:
    """How many periods before the first returned one the transform reads."""
    if transform in ("diff", "pct_change", "annualized_pct_change"):
        return 1
    if transform in ("yoy_diff", "yoy_pct_change"):
        return ppy or 0
    if transform == "moving_average":
        return max((window or 1) - 1, 0)
    return 0


def extra_months(
    transform: str, out_ppy: int | None, *, aggregating: bool, window: int | None = None
) -> int:
    """Months of history to fetch before the requested window: the lag, plus
    one output period so the first aggregated period is complete."""
    if out_ppy is None:
        return 1 if transform != "level" else 0  # a daily series' previous observation
    months = lag_periods(transform, out_ppy, window) * (12 // out_ppy)
    return months + (12 // out_ppy if aggregating else 0)


def source_periods_needed(
    latest_n: int,
    transform: str,
    source_ppy: int | None,
    out_ppy: int | None,
    window: int | None = None,
) -> int:
    """Source periods to request so that `latest_n` output periods can be computed."""
    lag = lag_periods(transform, out_ppy, window)
    if source_ppy is None or out_ppy is None:
        return latest_n + lag
    ratio = source_ppy // out_ppy
    # ratio - 1 more: the latest output period may not be complete yet.
    return (latest_n + lag) * ratio + ratio - 1


def is_rate_unit(text: str | None) -> bool:
    """Whether a unit names a percentage or a rate in percent.

    Matched against StatCan's uom descriptions (getCodeSets, checked
    2026-10-27: 239 Percent, 242 Percentage, 243-246 Percentage of ...,
    396 Percentage point, 431 Average percentage, 257 Rate, 358 Basis
    points) and Valet's metadata.unit ("Percent", "Pourcentage"). Rates per
    1,000 or 100,000 people are counts per head, not percentages, and keep
    their percent change.
    """
    if not text:
        return False
    folded = text.strip().lower()
    return bool(
        re.search(r"percent|pourcent|\bbasis points?\b|points de base|^%$", folded)
        or folded in ("rate", "taux")
    )


# Aggregation ----------------------------------------------------------------------


def _clean(points: Sequence[tuple[date, float | None]]) -> list[tuple[date, float | None]]:
    """Sorted by date, NaN as missing."""
    return sorted(
        ((d, None if v is None or math.isnan(v) else float(v)) for d, v in points),
        key=lambda point: point[0],
    )


def aggregate(
    points: Sequence[tuple[date, float | None]],
    source_ppy: int | None,
    target_ppy: int,
    method: Aggregation,
    lang: str = "en",
) -> tuple[list[tuple[date, float | None]], set[date]]:
    """(one level per target period, the periods left missing because incomplete).

    From monthly, quarterly or semi-annual data a period needs every one of
    its sub-periods, each with a value; otherwise it is None. From daily or
    weekly data the observations present are combined (a business day with no
    trading has no row), and a first or last period the data only partly
    cover is None.
    """
    points = _clean(points)
    if source_ppy is not None and (source_ppy < target_ppy or source_ppy % target_ppy):
        raise _error(
            lang,
            f"A {frequency_name(source_ppy)} series cannot be aggregated to "
            f"{frequency_name(target_ppy)}.",
            f"Une série {frequency_name(source_ppy, 'fr')} ne peut pas être agrégée en "
            f"fréquence {frequency_name(target_ppy, 'fr')}.",
        )
    groups: dict[date, list[tuple[date, float | None]]] = {}
    for day, value in points:
        groups.setdefault(period_start(day, target_ppy), []).append((day, value))
    if not groups:
        return [], set()
    first_day, last_day = points[0][0], points[-1][0]
    starts = list(groups)
    out: list[tuple[date, float | None]] = []
    incomplete: set[date] = set()
    for start, members in groups.items():
        values: list[float]
        if source_ppy is not None:
            expected = source_ppy // target_ppy
            if len({period_start(d, source_ppy) for d, _ in members}) < expected:
                incomplete.add(start)
                out.append((start, None))
                continue
            if any(v is None for _, v in members):
                out.append((start, None))
                continue
            values = [v for _, v in members if v is not None]
        else:
            cut_start = start == starts[0] and (first_day - start).days > _EDGE_DAYS
            cut_end = (
                start == starts[-1] and (period_end(start, target_ppy) - last_day).days > _EDGE_DAYS
            )
            values = [v for _, v in members if v is not None]
            if cut_start or cut_end:
                incomplete.add(start)
                out.append((start, None))
                continue
            if not values:
                out.append((start, None))
                continue
        if method == "sum":
            level = math.fsum(values)
        elif method == "end_of_period":
            level = values[-1]
        else:
            level = math.fsum(values) / len(values)
        out.append((start, level))
    return out, incomplete


# Transforms -----------------------------------------------------------------------


def _base_value(
    levels: list[tuple[date, float | None]], base: str, ppy: int | None, lang: str
) -> float:
    try:
        base_start, base_ppy = parse_period(base)
    except ValueError as exc:
        raise _error(
            lang,
            f"index_base {base!r} is not a period: use 2020, 2020-Q1, 2020-01 or 2020-01-15.",
            f"index_base {base!r} n'est pas une période : utilisez 2020, 2020-Q1, 2020-01 ou "
            "2020-01-15.",
        ) from exc
    if base_ppy is None:
        base_end = base_start
    else:
        base_end = period_end(base_start, base_ppy)
        if ppy is not None and base_ppy > ppy:
            raise _error(
                lang,
                f"index_base {base!r} is shorter than one period of this "
                f"{frequency_name(ppy)} series; use a whole period or a year.",
                f"index_base {base!r} est plus court qu'une période de cette série "
                f"{frequency_name(ppy, 'fr')} ; utilisez une période entière ou une année.",
            )
    inside = [v for d, v in levels if base_start <= d <= base_end]
    expected = (ppy // base_ppy) if (ppy is not None and base_ppy is not None) else None
    present = [v for v in inside if v is not None]
    if not present or len(present) < len(inside) or (expected and len(present) < expected):
        raise _error(
            lang,
            f"index_base {base!r} has no complete data in this series: pick a period it covers "
            "(the tool fetches back to it).",
            f"index_base {base!r} n'a pas de données complètes dans cette série : choisissez une "
            "période qu'elle couvre (l'outil remonte jusqu'à elle).",
        )
    return math.fsum(present) / len(present)


def _formula(
    transform: str,
    ppy: int | None,
    *,
    index_base: str | None,
    aggregation: str | None,
    source_ppy: int | None,
    window: int | None = None,
    lang: str,
) -> str:
    lag = ppy if transform in ("yoy_diff", "yoy_pct_change") else 1
    span = window or 2
    terms = [f"x_{{t-{k}}}" for k in range(span - 1, 0, -1)] + ["x_t"]
    if span > 4:  # mean(x_{t-11}, ..., x_{t-1}, x_t)
        terms = [terms[0], "...", *terms[-2:]]
    expressions = {
        "level": "x_t",
        "diff": "x_t - x_{t-1}",
        "pct_change": "100 * (x_t / x_{t-1} - 1)",
        "yoy_diff": f"x_t - x_{{t-{lag}}}",
        "yoy_pct_change": f"100 * (x_t / x_{{t-{lag}}} - 1)",
        "annualized_pct_change": f"100 * ((x_t / x_{{t-1}})^{ppy} - 1)",
        "index": "100 * x_t / x_base",
        "moving_average": f"mean({', '.join(terms)})",
    }
    name = f"moving_average_{window}" if transform == "moving_average" else transform
    text_en = f"Computed by MapleStats: {name} = {expressions[transform]}"
    text_fr = f"Calculé par MapleStats : {name} = {expressions[transform]}"
    if ppy is not None:
        en, fr = _PERIOD_WORDS[ppy]
        text_en += f", t in {en}"
        text_fr += f", t en {fr}"
    elif transform != "level":
        text_en += ", t-1 = the previous observation"
        text_fr += ", t-1 = l'observation précédente"
    if transform in ("yoy_diff", "yoy_pct_change"):
        text_en += " (the same period a year earlier, matched by date)"
        text_fr += " (la même période un an plus tôt, appariée par date)"
    if transform == "index":
        text_en += f", x_base = average level over {index_base}"
        text_fr += f", x_base = niveau moyen sur {index_base}"
    if transform == "moving_average":
        text_en += " (trailing, periods matched by date; null if any of them is missing)"
        text_fr += " (moyenne passée, périodes appariées par date ; nulle s'il en manque une)"
    if aggregation:
        target_en, source_en = frequency_name(ppy), frequency_name(source_ppy)
        target_fr, source_fr = frequency_name(ppy, "fr"), frequency_name(source_ppy, "fr")
        method_en = {"average": "average", "sum": "sum", "end_of_period": "last value"}[aggregation]
        method_fr = {"average": "moyenne", "sum": "somme", "end_of_period": "dernière valeur"}[
            aggregation
        ]
        text_en += f"; x = {method_en} of the {source_en} values in each {target_en} period"
        text_fr += (
            f" ; x = {method_fr} des valeurs (fréquence {source_fr}) de chaque période "
            f"(fréquence {target_fr})"
        )
    return pick(lang, text_en, text_fr)


def _compute(transform: str, current: float | None, lagged: float | None, ppy: int | None):
    if current is None or lagged is None:
        return None
    if transform in ("diff", "yoy_diff"):
        return current - lagged
    if lagged == 0:
        return None
    ratio = current / lagged
    if transform == "annualized_pct_change":
        if ratio < 0 or ppy is None:
            return None
        return 100 * (ratio**ppy - 1)
    return 100 * (ratio - 1)


def transform_series(
    points: Sequence[tuple[date, float | None]],
    *,
    source_ppy: int | None,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    window: int | None = None,
    rate_unit: bool = False,
    units: str | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    latest_n: int | None = None,
    lang: str = "en",
) -> TransformedSeries:
    """Levels (date, value) to computed values, trimmed to the requested window.

    `points` must reach back far enough for the lag (see extra_months and
    source_periods_needed); a period whose lagged level is not there gets None.
    """
    points = _clean(points)
    out_ppy = PERIODS_PER_YEAR[frequency] if frequency else source_ppy
    notes: list[str] = []
    incomplete: set[date] = set()
    if frequency:
        if source_ppy is not None and out_ppy is not None and out_ppy > source_ppy:
            raise _error(
                lang,
                f"frequency={frequency!r} is finer than this {frequency_name(source_ppy)} "
                "series; MapleStats only aggregates to a lower frequency.",
                f"frequency={frequency!r} est plus fine que cette série "
                f"{frequency_name(source_ppy, 'fr')} ; MapleStats agrège seulement vers une "
                "fréquence plus basse.",
            )
        assert out_ppy is not None
        levels, incomplete = aggregate(points, source_ppy, out_ppy, aggregation, lang)
    else:
        levels = [(period_start(d, out_ppy) if out_ppy else d, v) for d, v in points]
    if index_base and transform != "index":
        raise _error(
            lang,
            "index_base only applies to transform='index'.",
            "index_base ne s'applique qu'à transform='index'.",
        )
    check_window(transform, window, lang)

    applied: str = transform
    if rate_unit and transform in _POINTS_INSTEAD:
        applied = _POINTS_INSTEAD[transform]
        unit_text = f" ({units})" if units else ""
        notes.append(
            pick(
                lang,
                f"This series is already a percentage or rate{unit_text}, so a percent change of "
                f"it would be misleading: {transform} was computed as {applied}, the change in "
                "percentage points."
                + (" It is not annualized." if transform == "annualized_pct_change" else ""),
                f"Cette série est déjà un pourcentage ou un taux{unit_text} ; une variation en "
                f"pourcentage serait trompeuse : {transform} a été calculé comme {applied}, la "
                "variation en points de pourcentage."
                + (" Elle n'est pas annualisée." if transform == "annualized_pct_change" else ""),
            )
        )
    if applied in _NEEDS_CALENDAR and out_ppy is None:
        raise _error(
            lang,
            f"transform={transform!r} needs a monthly, quarterly or annual series; this one is "
            "daily, weekly or irregular. Add frequency='monthly' (or quarterly, annual) to "
            "aggregate it first.",
            f"transform={transform!r} exige une série mensuelle, trimestrielle ou annuelle ; "
            "celle-ci est quotidienne, hebdomadaire ou irrégulière. Ajoutez "
            "frequency='monthly' (ou quarterly, annual) pour l'agréger d'abord.",
        )
    if transform == "index" and not index_base:
        raise _error(
            lang,
            "transform='index' needs index_base, the period set to 100 (e.g. 2020 or 2020-01).",
            "transform='index' exige index_base, la période ramenée à 100 (p. ex. 2020 ou "
            "2020-01).",
        )

    values: list[float | None]
    if applied == "level":
        values = [v for _, v in levels]
    elif applied == "index":
        assert index_base is not None
        base = _base_value(levels, index_base, out_ppy, lang)
        values = [None if v is None or base == 0 else 100 * v / base for _, v in levels]
    elif applied == "moving_average":
        assert window is not None and out_ppy is not None  # check_window, _NEEDS_CALENDAR
        by_key = {_key(d, out_ppy): v for d, v in levels}
        values = []
        for d, _ in levels:
            span = [by_key.get(_key(d, out_ppy) - k) for k in range(window)]
            present = [v for v in span if v is not None]
            values.append(math.fsum(present) / window if len(present) == window else None)
    elif out_ppy is None:
        values = [None] + [
            _compute(applied, levels[i][1], levels[i - 1][1], None) for i in range(1, len(levels))
        ]
    else:
        by_key = {_key(d, out_ppy): v for d, v in levels}
        lag = lag_periods(applied, out_ppy)
        values = [
            _compute(applied, v, by_key.get(_key(d, out_ppy) - lag), out_ppy) for d, v in levels
        ]
    if applied in ("pct_change", "yoy_pct_change", "annualized_pct_change") and any(
        v == 0 for _, v in levels
    ):
        notes.append(
            pick(
                lang,
                "A percent change from a level of 0 is undefined and left null.",
                "Une variation en pourcentage à partir d'un niveau nul est indéfinie et laissée "
                "nulle.",
            )
        )

    rows = list(zip(levels, values, strict=True))
    if window_start is not None:
        first = period_start(window_start, out_ppy) if out_ppy else window_start
        rows = [r for r in rows if r[0][0] >= first]
    if window_end is not None:
        rows = [r for r in rows if r[0][0] <= window_end]
    if latest_n is not None:
        rows = rows[-latest_n:] if latest_n > 0 else []
    if applied == "moving_average" and window is not None:
        notes.append(
            pick(
                lang,
                f"Trailing moving average: each value is the mean of its period and the "
                f"{window - 1} before it (MapleStats does not compute a centred one). A period "
                "whose window reaches a missing or unpublished period is null."
                + (
                    " The series is a percentage or rate: its moving average is in the same "
                    "unit, so no percentage-point conversion applies."
                    if rate_unit
                    else ""
                ),
                f"Moyenne mobile passée : chaque valeur est la moyenne de sa période et des "
                f"{window - 1} précédentes (MapleStats ne calcule pas de moyenne centrée). Une "
                "période dont la fenêtre touche une période manquante ou non publiée est nulle."
                + (
                    " La série est un pourcentage ou un taux : sa moyenne mobile est dans la "
                    "même unité, sans conversion en points de pourcentage."
                    if rate_unit
                    else ""
                ),
            )
        )
    if cut := sorted(period_label(d, out_ppy) for (d, _), _ in rows if d in incomplete):
        notes.append(
            pick(
                lang,
                f"Not aggregated, the data do not cover the whole period: {', '.join(cut)} "
                "(left null rather than a partial-period figure).",
                f"Non agrégé, les données ne couvrent pas toute la période : {', '.join(cut)} "
                "(laissé nul plutôt qu'un chiffre sur une période partielle).",
            )
        )

    if applied in ("diff", "yoy_diff"):
        unit = (
            pick(lang, "percentage points", "points de pourcentage")
            if rate_unit
            else (units or pick(lang, "the series' own units", "les unités de la série"))
        )
    elif applied in ("pct_change", "yoy_pct_change", "annualized_pct_change"):
        unit = pick(lang, "percent", "pourcentage")
    elif applied == "index":
        unit = pick(lang, f"index, {index_base}=100", f"indice, {index_base}=100")
    else:
        unit = units or pick(lang, "as published", "tel que publié")

    return TransformedSeries(
        requested_transform=transform,
        transform=applied,
        frequency=frequency_name(out_ppy, lang),
        periods_per_year=out_ppy,
        source_periods_per_year=source_ppy,
        aggregation=aggregation if frequency else None,
        window=window if applied == "moving_average" else None,
        formula=_formula(
            applied,
            out_ppy,
            index_base=index_base,
            aggregation=aggregation if frequency else None,
            source_ppy=source_ppy,
            window=window,
            lang=lang,
        ),
        unit=unit,
        notes=notes,
        points=[
            TransformedPoint(
                period=period_label(day, out_ppy),
                ref_date=day,
                level=level,
                value=None if value is None else round(value, 10),
            )
            for (day, level), value in rows
        ],
    )

"""Inline-SVG charts for the website's case studies (scripts/build_site.py).

Every function returns one ``<svg class="chart" data-chart ...>`` string to
paste into a page. The markup carries classes only, never a colour, so the
page's light and dark themes restyle it: site/assets/charts.css draws and
animates the classes, and site/assets/charts.js adds ``play`` to each chart
as it scrolls into view. Without JavaScript (or with reduced motion) the
charts render in their final state.

Width is set by CSS, so the viewBox is a fixed 640 units wide; text sizes in
charts.css are in the same units. Coordinates are rounded to one decimal to
keep the markup small. Text widths are estimated from character counts (there
is no font metrics library here), which is why the margins are generous.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable, Sequence
from datetime import date
from itertools import pairwise

__all__ = [
    "ci_chart",
    "grouped_bars",
    "hbar_chart",
    "line_chart",
    "ring_chart",
    "scatter_chart",
    "step_chart",
]

WIDTH = 640

# Font sizes (viewBox units) must match charts.css; widths are estimates.
_MONO_PX = 11.0  # .c-axis, .c-value, .c-legend
_LABEL_PX = 12.5  # .c-label
_MONO_CHAR = 0.6  # a monospace glyph is ~0.6em wide
_TEXT_CHAR = 0.56  # a generous average for the proportional label font


def _n(x: float) -> str:
    """A coordinate rounded to one decimal, without a trailing '.0'."""
    r = round(x, 1)
    if r == 0:
        return "0"
    s = f"{r:.1f}"
    return s.removesuffix(".0")


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _mono_w(text: str) -> float:
    return len(text) * _MONO_PX * _MONO_CHAR


def _label_w(text: str) -> float:
    return len(text) * _LABEL_PX * _TEXT_CHAR


def _open(height: float, label: str) -> str:
    safe = _esc(label)
    return (
        f'<svg class="chart" data-chart="" viewBox="0 0 {WIDTH} {_n(height)}" role="img" '
        f'aria-label="{safe}" preserveAspectRatio="xMidYMid meet"><title>{safe}</title>'
    )


def _text(x: float, y: float, text: str, cls: str, anchor: str = "start", extra: str = "") -> str:
    anchor_attr = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text class="{cls}" x="{_n(x)}" y="{_n(y)}"{anchor_attr}{extra}>{_esc(text)}</text>'


def _ticks(lo: float, hi: float) -> list[float]:
    """4-6 round tick values whose ends enclose [lo, hi].

    Steps are 1, 2 or 5 times a power of ten (and 2.5 only from 25 up), so a
    caller's value_format that rounds to integers never prints two ticks the
    same or a tick at a value it does not sit on.
    """
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError("chart values must be finite")
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        pad = abs(lo) * 0.1 or 1.0
        lo, hi = lo - pad, hi + pad
    span = hi - lo
    magnitude = math.floor(math.log10(span))
    best: tuple[tuple[float, int], list[float]] | None = None
    for exp in range(magnitude - 2, magnitude + 2):
        for mult in (1.0, 2.0, 2.5, 5.0):
            if mult == 2.5 and exp < 1:
                continue
            step = mult * 10.0**exp
            first = math.floor(lo / step + 1e-9)
            last = math.ceil(hi / step - 1e-9)
            # Too coarse a step gives 2-3 ticks: widen by a step at a time,
            # upwards first and never below zero for non-negative data.
            grow_up = True
            while last - first + 1 < 4:
                if grow_up or (lo >= 0 and first <= 0):
                    last += 1
                else:
                    first -= 1
                grow_up = not grow_up
            count = last - first + 1
            if count > 6:
                continue
            values = [round((first + i) * step, 10) for i in range(count)]
            key = ((last - first) * step / span, abs(count - 5))
            if best is None or key < best[0]:
                best = (key, values)
    if best is None:  # pragma: no cover - some step always fits
        raise ValueError(f"no ticks for {lo}..{hi}")
    return best[1]


def _scale(d0: float, d1: float, r0: float, r1: float) -> Callable[[float], float]:
    if d1 == d0:
        mid = (r0 + r1) / 2
        return lambda _v: mid
    k = (r1 - r0) / (d1 - d0)
    return lambda v: r0 + (v - d0) * k


def _wrap(text: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip(" ,;:") + "\u2026"


def _multiline(x: float, y: float, lines: Sequence[str], cls: str, anchor: str, lh: float) -> str:
    """A <text> with one <tspan> per line, the block centred on y."""
    if len(lines) == 1:
        return _text(x, y, lines[0], cls, anchor)
    top = y - (len(lines) - 1) * lh / 2
    anchor_attr = "" if anchor == "start" else f' text-anchor="{anchor}"'
    spans = "".join(
        f'<tspan x="{_n(x)}" y="{_n(top + i * lh)}">{_esc(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return f'<text class="{cls}"{anchor_attr}>{spans}</text>'


# ---------------------------------------------------------------------------
# Confidence intervals


def ci_chart(
    rows: list[tuple[str, float, float, float]],
    *,
    label: str,
    value_format: Callable[[float], str],
    range_word: str = "to",
) -> str:
    """Horizontal dot-and-whisker chart: one row per (label, estimate, low, high).

    Rows are drawn top to bottom in the given order. The interval is a
    ``c-ci`` path (line plus end caps, so one element scales from its centre),
    the estimate a ``c-dot`` circle and its value a ``c-value`` at the right.
    Each row's tooltip reads "name: estimate (low <range_word> high)".
    """
    if not rows:
        raise ValueError("ci_chart needs at least one row")
    label_cap = 210.0
    max_chars = int(label_cap / (_LABEL_PX * _TEXT_CHAR))
    wrapped = [_wrap(name, max_chars) for name, *_ in rows]
    label_col = min(max(_label_w(line) for lines in wrapped for line in lines), label_cap)
    values = [value_format(est) for _, est, _, _ in rows]
    value_col = max(_mono_w(v) for v in values) + 16

    left = label_col + 16
    right = WIDTH - value_col - 10
    top = 10.0
    heights = [max(32.0, 16.0 * len(lines) + 14) for lines in wrapped]
    plot_bottom = top + sum(heights)
    height = plot_bottom + 30

    lows = [min(lo, est, hi) for _, est, lo, hi in rows]
    highs = [max(lo, est, hi) for _, est, lo, hi in rows]
    ticks = _ticks(min(lows), max(highs))
    x = _scale(ticks[0], ticks[-1], left, right)

    out = [_open(height, label)]
    for t in ticks:
        xt = x(t)
        out.append(
            f'<line class="c-grid" x1="{_n(xt)}" y1="{_n(top)}" '
            f'x2="{_n(xt)}" y2="{_n(plot_bottom)}"/>'
        )
        out.append(_text(xt, plot_bottom + 18, value_format(t), "c-axis", "middle"))
    if ticks[0] < 0 < ticks[-1]:
        x0 = x(0)
        out.append(
            f'<line class="c-grid c-base" x1="{_n(x0)}" y1="{_n(top)}" '
            f'x2="{_n(x0)}" y2="{_n(plot_bottom)}"/>'
        )

    y_top = top
    for i, ((name, est, lo, hi), lines, h, shown) in enumerate(
        zip(rows, wrapped, heights, values, strict=True)
    ):
        yc = y_top + h / 2
        interval = f"{value_format(min(lo, hi))} {range_word} {value_format(max(lo, hi))}"
        tip = f"{name}: {shown} ({interval})"
        out.append(
            f'<rect class="c-hit" x="0" y="{_n(y_top)}" width="{WIDTH}" height="{_n(h)}">'
            f"<title>{_esc(tip)}</title></rect>"
        )
        xl, xh, xe = x(min(lo, hi)), x(max(lo, hi)), x(est)
        cap = 5.0
        out.append(_multiline(left - 14, yc + 4.2, lines, "c-label", "end", 15))
        out.append(
            f'<path class="c-ci" style="--i:{i}" d="M{_n(xl)} {_n(yc - cap)}V{_n(yc + cap)}'
            f'M{_n(xl)} {_n(yc)}H{_n(xh)}M{_n(xh)} {_n(yc - cap)}V{_n(yc + cap)}"/>'
        )
        out.append(f'<circle class="c-dot" style="--i:{i}" cx="{_n(xe)}" cy="{_n(yc)}" r="5"/>')
        out.append(_text(WIDTH - 8, yc + 4, shown, "c-value", "end"))
        y_top += h
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Grouped bars

_ROT_DEG = 40
_ROT_CHARS = 26

_BAR_CLASSES = ("c-bar", "c-bar-2", "c-bar-3")
_KEY_CLASSES = ("c-key", "c-key-2", "c-key-3")


def grouped_bars(
    categories: list[str],
    series: list[tuple[str, list[float | None]]],
    *,
    label: str,
    value_format: Callable[[float], str],
) -> str:
    """Vertical grouped bars: 1-3 series of one value per category.

    A None value leaves a gap. Bars are plain ``<rect>``s (no transform) so
    CSS can scale them from their baseline; ``--i`` numbers them left to
    right for the staggered entrance.
    """
    if not categories:
        raise ValueError("grouped_bars needs at least one category")
    if not 1 <= len(series) <= 3:
        raise ValueError("grouped_bars takes 1 to 3 series")
    for name, vals in series:
        if len(vals) != len(categories):
            raise ValueError(f"series {name!r} has {len(vals)} values for {len(categories)}")

    present = [v for _, vals in series for v in vals if v is not None]
    ticks = _ticks(min([0.0, *present]), max([0.0, *present]))
    tick_labels = [value_format(t) for t in ticks]

    left = max(_mono_w(t) for t in tick_labels) + 14
    right = WIDTH - 6
    top = 34.0
    group_w = (right - left) / len(categories)

    # Category labels: wrap onto up to three lines; rotate if that is not
    # enough. Rotated labels are cut at _ROT_CHARS (the full text stays in a
    # <title> tooltip) so they cannot run off the bottom, and the plot moves
    # right until the first labels' lower-left ends stay on the canvas.
    max_chars = max(1, int((group_w - 6) / (_LABEL_PX * _TEXT_CHAR)))
    wrapped = [_wrap(c, max_chars) for c in categories]
    rotate = any(len(ls) > 3 or any(len(line) > max_chars for line in ls) for ls in wrapped)
    shown_cats = [_truncate(c, _ROT_CHARS) if rotate else c for c in categories]
    if rotate:
        cos, sin = math.cos(math.radians(_ROT_DEG)), math.sin(math.radians(_ROT_DEG))
        widths = [_label_w(c) for c in shown_cats]
        label_h = max(widths) * sin + 24
        for _ in range(3):
            group_w = (right - left) / len(categories)
            need = max(w * cos - (i + 0.5) * group_w - 4 for i, w in enumerate(widths)) + 4
            if need <= left:
                break
            left = need
        group_w = (right - left) / len(categories)
    else:
        label_h = 15.0 * max(len(ls) for ls in wrapped) + 12
    height = 300.0 + (label_h - 27 if label_h > 27 else 0)
    plot_bottom = height - label_h
    y = _scale(ticks[0], ticks[-1], plot_bottom, top)

    out = [_open(height, label)]

    # Legend.
    lx = left
    for s, (name, _) in enumerate(series):
        out.append(f'<rect class="{_KEY_CLASSES[s]}" x="{_n(lx)}" y="6" width="11" height="11"/>')
        out.append(_text(lx + 16, 15.5, name, "c-legend"))
        lx += 16 + _mono_w(name) + 22

    for t, shown in zip(ticks, tick_labels, strict=True):
        yt = y(t)
        cls = "c-grid c-base" if t == 0 else "c-grid"
        out.append(
            f'<line class="{cls}" x1="{_n(left)}" y1="{_n(yt)}" x2="{_n(right)}" y2="{_n(yt)}"/>'
        )
        out.append(_text(left - 8, yt + 3.8, shown, "c-axis", "end"))

    inner = group_w * (0.74 if len(series) > 1 else 0.6)
    gap = 1.5 if len(series) > 1 else 0.0
    bar_w = (inner - gap * (len(series) - 1)) / len(series)
    y0 = y(0)
    order = 0
    for c, category in enumerate(categories):
        gx = left + c * group_w + (group_w - inner) / 2
        for s, (series_name, vals) in enumerate(series):
            v = vals[c]
            bx = gx + s * (bar_w + gap)
            if v is not None:
                yv = y(v)
                style = f"--i:{order}" if v >= 0 else f"--i:{order};transform-origin:top"
                tip = _esc(f"{series_name}, {category}: {value_format(v)}")
                out.append(
                    f'<rect class="{_BAR_CLASSES[s]}" style="{style}" x="{_n(bx)}" '
                    f'y="{_n(min(yv, y0))}" width="{_n(bar_w)}" height="{_n(abs(y0 - yv))}">'
                    f"<title>{tip}</title></rect>"
                )
            order += 1
        cx = left + (c + 0.5) * group_w
        if rotate:
            ty = plot_bottom + 14
            tip = f"<title>{_esc(category)}</title>" if shown_cats[c] != category else ""
            out.append(
                f'<text class="c-label" x="{_n(cx + 4)}" y="{_n(ty)}" text-anchor="end" '
                f'transform="rotate(-{_ROT_DEG} {_n(cx + 4)} {_n(ty)})">'
                f"{tip}{_esc(shown_cats[c])}</text>"
            )
        else:
            lines = wrapped[c]
            spans = "".join(
                f'<tspan x="{_n(cx)}" y="{_n(plot_bottom + 18 + i * 15)}">{_esc(line)}</tspan>'
                for i, line in enumerate(lines)
            )
            out.append(f'<text class="c-label" text-anchor="middle">{spans}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Time series


def _change_points(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """The first point, each point whose value differs from the one before, the last."""
    kept = [points[0]]
    for prev, point in pairwise(points):
        if point[1] != prev[1]:
            kept.append(point)
    if len(points) > 1 and kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def _time_chart(
    points: list[tuple[str, float]],
    *,
    label: str,
    value_format: Callable[[float], str],
    x_tick_format: Callable[[str], str | None],
    steps: bool,
    band: tuple[float, float, str] | None = None,
    date_format: Callable[[str], str] | None = None,
) -> str:
    if not points:
        raise ValueError("a time chart needs at least one point")
    days = [date.fromisoformat(d).toordinal() for d, _ in points]
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    if band:
        lo, hi = min(lo, band[0]), max(hi, band[1])
    pad = (hi - lo) * 0.08 if hi > lo else (abs(hi) * 0.1 or 1.0)
    # Padding must not push an all-positive series (a rate, a price) below
    # zero: an axis running to -2% under a policy rate reads as a claim.
    floor = lo - pad if lo < 0 or lo - pad >= 0 else 0.0
    ticks = _ticks(floor, hi + pad)
    tick_labels = [value_format(t) for t in ticks]
    last_label = value_format(vals[-1])

    height = 300.0
    top = 14.0
    plot_bottom = height - 30
    left = max(_mono_w(t) for t in tick_labels) + 14
    right = WIDTH - _mono_w(last_label) - 20
    x = _scale(days[0], days[-1], left, right)
    y = _scale(ticks[0], ticks[-1], plot_bottom, top)

    out = [_open(height, label)]
    for t, shown in zip(ticks, tick_labels, strict=True):
        yt = y(t)
        cls = "c-grid c-base" if t == 0 else "c-grid"
        out.append(
            f'<line class="{cls}" x1="{_n(left)}" y1="{_n(yt)}" x2="{_n(right)}" y2="{_n(yt)}"/>'
        )
        out.append(_text(left - 8, yt + 3.8, shown, "c-axis", "end"))

    if band:
        b_lo, b_hi, b_label = band
        out.append(
            f'<rect class="c-band" x="{_n(left)}" y="{_n(y(b_hi))}" width="{_n(right - left)}" '
            f'height="{_n(y(b_lo) - y(b_hi))}"/>'
        )
        out.append(_text(right - 6, y(b_lo) - 6, b_label, "c-band-label", "end"))

    # X ticks: a run of points with the same label (every day of a January in
    # daily data) gets one tick, at its first point; ticks too close to the
    # previous one are dropped so labels never overlap.
    prev_label: str | None = None
    prev_edge = -math.inf
    for (d, _), day in zip(points, days, strict=True):
        tick = x_tick_format(d)
        if tick is None or tick == prev_label:
            prev_label = tick
            continue
        prev_label = tick
        xt = x(day)
        half = _mono_w(tick) / 2
        if xt - half < prev_edge + 8:
            continue
        prev_edge = xt + half
        out.append(
            f'<line class="c-grid" x1="{_n(xt)}" y1="{_n(plot_bottom)}" '
            f'x2="{_n(xt)}" y2="{_n(plot_bottom + 5)}"/>'
        )
        out.append(_text(xt, plot_bottom + 18, tick, "c-axis", "middle"))

    if steps:
        reduced = _change_points(points)
        rx = [x(date.fromisoformat(d).toordinal()) for d, _ in reduced]
        ry = [y(v) for _, v in reduced]
        parts = [f"M{_n(rx[0])} {_n(ry[0])}"]
        for i in range(1, len(reduced)):
            parts.append(f"H{_n(rx[i])}")
            if _n(ry[i]) != _n(ry[i - 1]):
                parts.append(f"V{_n(ry[i])}")
    else:
        parts = [
            f"{'M' if i == 0 else 'L'}{_n(x(day))} {_n(y(v))}"
            for i, (day, v) in enumerate(zip(days, vals, strict=True))
        ]
    out.append(f'<path class="c-line" pathLength="1" d="{"".join(parts)}"/>')

    hover = _change_points(points) if steps else points
    for d, v in hover:
        hx, hy = x(date.fromisoformat(d).toordinal()), y(v)
        out.append(
            f'<circle class="c-hit" cx="{_n(hx)}" cy="{_n(hy)}" r="9">'
            f"<title>{_esc(date_format(d) if date_format else d)}: {_esc(value_format(v))}</title>"
            "</circle>"
        )

    xe, ye = x(days[-1]), y(vals[-1])
    out.append(f'<circle class="c-ring" cx="{_n(xe)}" cy="{_n(ye)}" r="5"/>')
    out.append(f'<circle class="c-dot c-end" cx="{_n(xe)}" cy="{_n(ye)}" r="5"/>')
    out.append(_text(xe + 10, ye + 4, last_label, "c-value c-end"))
    out.append("</svg>")
    return "".join(out)


def line_chart(
    points: list[tuple[str, float]],
    *,
    label: str,
    value_format: Callable[[float], str],
    x_tick_format: Callable[[str], str | None],
    band: tuple[float, float, str] | None = None,
    date_format: Callable[[str], str] | None = None,
) -> str:
    """A time series as one ``c-line`` path, x proportional to time.

    ``points`` are (ISO date, value) in time order. An x tick goes at each
    point for which ``x_tick_format`` returns a label; the last point gets a
    pulsing ``c-dot`` and its value. ``band`` (low, high, label) shades a
    range behind the line, such as an inflation target. ``date_format``
    writes each point's date in its tooltip (the ISO date by default).
    """
    return _time_chart(
        points,
        label=label,
        value_format=value_format,
        x_tick_format=x_tick_format,
        steps=False,
        band=band,
        date_format=date_format,
    )


def step_chart(
    points: list[tuple[str, float]],
    *,
    label: str,
    value_format: Callable[[float], str],
    x_tick_format: Callable[[str], str | None],
    date_format: Callable[[str], str] | None = None,
) -> str:
    """Like line_chart, drawn as steps (for a rate that changes on given days).

    Daily points are reduced to their change points first, so ~3,000 days
    of a policy rate become a path of a few dozen segments.
    """
    return _time_chart(
        points,
        label=label,
        value_format=value_format,
        x_tick_format=x_tick_format,
        steps=True,
        date_format=date_format,
    )


# ---------------------------------------------------------------------------
# Scatter

_PT_CLASSES = ("c-pt", "c-pt-2")


def scatter_chart(
    points: list[tuple[float, float, int, int, str]],
    *,
    series: list[str],
    label: str,
    x_format: Callable[[float], str],
    y_format: Callable[[float], str],
    x_title: str,
    y_title: str,
) -> str:
    """Dots at (x, y), one colour per series (at most two).

    Each point is (x, y, series index, count, tooltip). Identical points are
    passed once with their count, and the dot's area grows with it, so a
    stack of sixteen cards at one price reads as one large dot.
    """
    if not points:
        raise ValueError("scatter_chart needs at least one point")
    if len(series) > len(_PT_CLASSES):
        raise ValueError(f"scatter_chart draws at most {len(_PT_CLASSES)} series")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_ticks = _ticks(min(0.0, min(xs)), max(xs))
    y_ticks = _ticks(min(ys), max(ys))
    y_labels = [y_format(t) for t in y_ticks]

    height = 340.0
    top = 44.0
    bottom = height - 48
    left = max(_mono_w(t) for t in y_labels) + 16
    right = WIDTH - 16
    x = _scale(x_ticks[0], x_ticks[-1], left, right)
    y = _scale(y_ticks[0], y_ticks[-1], bottom, top)

    out = [_open(height, label)]
    key_x = left
    for i, name in enumerate(series):
        out.append(f'<circle class="{_PT_CLASSES[i]}" cx="{_n(key_x + 5)}" cy="10" r="5"/>')
        out.append(_text(key_x + 15, 14, name, "c-legend"))
        key_x += 15 + _mono_w(name) + 22
    out.append(_text(left, 32, y_title, "c-axis"))
    for t, shown in zip(y_ticks, y_labels, strict=True):
        yt = y(t)
        out.append(
            f'<line class="c-grid" x1="{_n(left)}" y1="{_n(yt)}" x2="{_n(right)}" y2="{_n(yt)}"/>'
        )
        out.append(_text(left - 8, yt + 3.8, shown, "c-axis", "end"))
    for t in x_ticks:
        xt = x(t)
        out.append(
            f'<line class="c-grid" x1="{_n(xt)}" y1="{_n(bottom)}" x2="{_n(xt)}" y2="{_n(bottom + 5)}"/>'
        )
        out.append(_text(xt, bottom + 18, x_format(t), "c-axis", "middle"))
    out.append(_text((left + right) / 2, bottom + 38, x_title, "c-axis", "middle"))

    # Larger dots first, so small ones stay on top and hoverable.
    order = sorted(range(len(points)), key=lambda k: -points[k][3])
    for i, k in enumerate(order):
        px, py, s_idx, count, tip = points[k]
        r = min(4.5 * math.sqrt(count), 16.0)
        out.append(
            f'<circle class="{_PT_CLASSES[s_idx]}" style="--i:{i}" cx="{_n(x(px))}" '
            f'cy="{_n(y(py))}" r="{_n(r)}"><title>{_esc(tip)}</title></circle>'
        )
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Horizontal bars on a log scale


def hbar_chart(
    rows: list[tuple[str, float]],
    *,
    label: str,
    value_format: Callable[[float], str],
    log: bool = True,
    tick_format: Callable[[float], str] | None = None,
) -> str:
    """One horizontal bar per (label, value), the value printed at its end.

    With ``log`` (the default) the scale is log10, for counts that span orders
    of magnitude (fifteen thousand series beside fifty portals), and each
    gridline is a power of ten; otherwise it is linear from zero.
    ``tick_format`` labels the gridlines when they need a shorter form than
    the values (1k, 1M), and defaults to ``value_format``.
    """
    if not rows or any(v <= 0 for _, v in rows):
        raise ValueError("hbar_chart needs positive values")
    label_col = min(max(_label_w(name) for name, _ in rows), 250.0)
    left = label_col + 16
    values = [value_format(v) for _, v in rows]
    right = WIDTH - max(_mono_w(v) for v in values) - 16
    top = 8.0
    row_h = 30.0
    bottom = top + row_h * len(rows)
    height = bottom + 26
    if log:
        decades = max(1, math.ceil(math.log10(max(v for _, v in rows))))
        x = _scale(0, decades, left, right)
        grid = [(float(d), 10.0**d) for d in range(decades + 1)]
    else:
        ticks = _ticks(0.0, max(v for _, v in rows))
        x = _scale(0, ticks[-1], left, right)
        grid = [(t, t) for t in ticks]

    def position(v: float) -> float:
        return x(math.log10(v)) if log else x(v)

    out = [_open(height, label)]
    for at, shown_tick in grid:
        xt = x(at)
        out.append(
            f'<line class="c-grid" x1="{_n(xt)}" y1="{_n(top)}" x2="{_n(xt)}" y2="{_n(bottom)}"/>'
        )
        out.append(
            _text(xt, bottom + 18, (tick_format or value_format)(shown_tick), "c-axis", "middle")
        )
    for i, ((name, v), shown) in enumerate(zip(rows, values, strict=True)):
        yc = top + i * row_h + row_h / 2
        w = position(v) - left
        out.append(_text(left - 10, yc + 4.2, _truncate(name, 40), "c-label", "end"))
        out.append(
            f'<rect class="c-hbar" style="--i:{i}" x="{_n(left)}" y="{_n(yc - 8)}" '
            f'width="{_n(max(w, 1.0))}" height="16"><title>{_esc(f"{name}: {shown}")}</title></rect>'
        )
        out.append(_text(left + w + 8, yc + 4, shown, "c-value"))
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# The ring: names inscribed on two circles, arcs sized by count, a centre figure

RING = 640.0  # the ring's viewBox is square
_RING_CHAR = 0.54  # an average glyph of the inscription (text sans, tracked), in em


def _circle_path(cx: float, cy: float, r: float) -> str:
    """A full circle, clockwise from the top: the path text is set along."""
    return (
        f"M{_n(cx)},{_n(cy - r)} a{_n(r)},{_n(r)} 0 1,1 0,{_n(2 * r)} "
        f"a{_n(r)},{_n(r)} 0 1,1 0,{_n(-2 * r)}"
    )


def _point(cx: float, cy: float, r: float, angle: float) -> tuple[float, float]:
    """Angle in degrees clockwise from the top."""
    a = math.radians(angle - 90)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _arc_path(cx: float, cy: float, r: float, a0: float, a1: float, reverse: bool = False) -> str:
    (x0, y0), (x1, y1) = _point(cx, cy, r, a0), _point(cx, cy, r, a1)
    large = 1 if a1 - a0 > 180 else 0
    if reverse:
        return f"M{_n(x1)},{_n(y1)} A{_n(r)},{_n(r)} 0 {large},0 {_n(x0)},{_n(y0)}"
    return f"M{_n(x0)},{_n(y0)} A{_n(r)},{_n(r)} 0 {large},1 {_n(x1)},{_n(y1)}"


def _inscription(ident: str, names: list[str], r: float, cls: str) -> tuple[str, str]:
    """(defs path, text) for names set once around a circle, ends meeting at the top.

    The font size is chosen so the names fill the circumference, and
    textLength closes any remaining gap by adjusting the letter spacing, so
    the last separator lands exactly where the first name starts.
    """
    text = " · ".join(names) + " · "
    circumference = 2 * math.pi * r
    size = min(max(circumference / (len(text) * _RING_CHAR), 7.0), 15.0)
    # Centre the lettering in its band: the baseline sits a third of the
    # font size inside the band's middle.
    baseline = r - size * 0.33
    path = f'<path id="{ident}" d="{_circle_path(RING / 2, RING / 2, baseline)}"/>'
    length = 2 * math.pi * baseline
    return path, (
        f'<text class="{cls}" style="font-size:{_n(size)}px">'
        f'<textPath href="#{ident}" textLength="{_n(length)}" lengthAdjust="spacing">'
        f"{_esc(text)}</textPath></text>"
    )


def ring_chart(
    outer: list[str],
    inner: list[str],
    arcs: list[tuple[str, str, int]],
    *,
    centre: str,
    centre_lines: tuple[str, str],
    label: str,
    ident: str = "ring",
) -> str:
    """The case-study finale: one ring for everything the server reaches.

    ``outer`` and ``inner`` are inscribed around two bands (the federal
    publishers, then the provinces and cities). ``arcs`` are (short label,
    full label, count), drawn clockwise from the top in the order given, each
    sweep proportional to its count and labelled along the arc where the
    label fits. The centre shows ``centre`` over two short lines.
    """
    if not outer or not arcs or any(n <= 0 for _, _, n in arcs):
        raise ValueError("ring_chart needs names and positive arc counts")
    c = RING / 2
    safe = _esc(label)
    out = [
        (
            f'<svg class="chart ring" data-chart="" viewBox="0 0 {_n(RING)} {_n(RING)}" role="img" '
            f'aria-label="{safe}" preserveAspectRatio="xMidYMid meet"><title>{safe}</title>'
        )
    ]
    defs: list[str] = []
    body: list[str] = []

    # Two inscription bands, each between two thin rules.
    bands = [
        (outer, 293.0, (276.0, 312.0), "ring-script"),
        (inner, 252.0, (236.0, 268.0), "ring-script-2"),
    ]
    for n, (names, r, (lo, hi), cls) in enumerate(bands):
        if not names:
            continue
        path, text = _inscription(f"{ident}-script-{n}", names, r, cls)
        defs.append(path)
        spin = "ring-spin" if n == 0 else "ring-spin-2"
        body.append(
            f'<circle class="ring-rule" cx="{_n(c)}" cy="{_n(c)}" r="{_n(hi)}"/>'
            f'<circle class="ring-rule" cx="{_n(c)}" cy="{_n(c)}" r="{_n(lo)}"/>'
            f'<g class="{spin}">{text}</g>'
        )

    # Arcs: sweep proportional to count, a small gap between neighbours.
    r_arc, width, gap = 184.0, 52.0, 1.4
    total = sum(n for _, _, n in arcs)
    sweep = 360.0 - gap * len(arcs)
    angle = gap / 2
    labels: list[str] = []
    for i, (short, full, count) in enumerate(arcs):
        a0, a1 = angle, angle + sweep * count / total
        angle = a1 + gap
        body.append(
            f'<path class="ring-arc" style="--i:{i}" pathLength="1" '
            f'd="{_arc_path(c, c, r_arc, a0, a1)}" stroke-width="{_n(width)}">'
            f"<title>{_esc(f'{full} ({count})')}</title></path>"
        )
        arc_len = math.radians(a1 - a0) * r_arc
        mid = (a0 + a1) / 2
        # Labels on the lower half run the other way, so they read upright.
        lower = 90 < mid < 270
        size = 12.0
        named = f"{short} {count}"
        if len(named) * size * _TEXT_CHAR + 12 <= arc_len:
            # A name and count run along the arc; on the lower half the
            # path is reversed and the baseline moves out, so it reads upright.
            pid = f"{ident}-arc-{i}"
            shift = size * 0.35
            r_text = r_arc + shift if lower else r_arc - shift
            defs.append(f'<path id="{pid}" d="{_arc_path(c, c, r_text, a0, a1, reverse=lower)}"/>')
            labels.append(
                f'<text class="ring-arc-label" style="--i:{i}">'
                f'<textPath href="#{pid}" startOffset="50%" text-anchor="middle">{_esc(named)}</textPath></text>'
            )
        elif size * 1.2 + 6 <= arc_len:
            # A short arc gets its count alone, upright at the arc's middle.
            x, y = _point(c, c, r_arc, mid)
            labels.append(
                _text(
                    x, y + size * 0.35, str(count), "ring-arc-label", "middle", f' style="--i:{i}"'
                )
            )

    out.append("<defs>" + "".join(defs) + "</defs>")
    out.extend(body)
    out.extend(labels)
    out.append(_text(c, c + 14, centre, "ring-n", "middle", ' data-count=""'))
    out.append(_text(c, c + 46, centre_lines[0], "ring-sub", "middle"))
    out.append(_text(c, c + 68, centre_lines[1], "ring-sub", "middle"))
    out.append("</svg>")
    return "".join(out)

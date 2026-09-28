"""The website's inline-SVG charts (scripts/site_charts.py).

They are pasted into pages as markup, so each must be well-formed XML, be
labelled for screen readers, and carry classes only: a fill= or stroke=
colour would ignore the page's dark theme.
"""

from __future__ import annotations

import importlib.util
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"


def _load_charts():
    spec = importlib.util.spec_from_file_location(
        "site_charts", ROOT / "scripts" / "site_charts.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


charts = _load_charts()


def pct(v: float) -> str:
    return f"{v:.1f}%"


def january(d: str) -> str | None:
    return d[:4] if d[5:7] == "01" else None


def _parse(svg: str) -> ET.Element:
    # The markup has no xmlns (it is inline HTML); add one to parse as SVG.
    return ET.fromstring(svg.replace("<svg ", f'<svg xmlns="{NS[1:-1]}" ', 1))


def _classes(el: ET.Element) -> set[str]:
    return set(el.get("class", "").split())


def _monthly(n: int) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for i in range(n):
        year, month = 2015 + i // 12, i % 12 + 1
        out.append((f"{year}-{month:02d}-01", 2 + (i % 7) * 0.3))
    return out


def _daily_runs(days: int, runs: list[float]) -> list[tuple[str, float]]:
    start = date(2017, 1, 1)
    per = days // len(runs)
    return [
        ((start + timedelta(i)).isoformat(), runs[min(i // per, len(runs) - 1)])
        for i in range(days)
    ]


CI_ROWS = [
    ("Quebec", 10.3, 9.5, 11.2),
    ("Ontario", 12.9, 12.1, 13.8),
    ('Alberta <&> "B"', 11.1, 10.0, 12.3),
]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _all_charts() -> dict[str, str]:
    return {
        "ci": charts.ci_chart(CI_ROWS, label="Low income", value_format=pct),
        "bars": charts.grouped_bars(
            MONTHS,
            [("2023", [float(i) for i in range(12)]), ("2024", [float(i + 1) for i in range(12)])],
            label="Starts",
            value_format=lambda v: f"{v:.0f}",
        ),
        "line": charts.line_chart(
            _monthly(60), label="CPI", value_format=pct, x_tick_format=january
        ),
        "step": charts.step_chart(
            _daily_runs(3000, [0.5, 1.75, 0.25, 5.0, 2.75]),
            label="Policy rate",
            value_format=lambda v: f"{v:.2f}%",
            x_tick_format=january,
        ),
        "band": charts.line_chart(
            _monthly(60),
            label="Inflation",
            value_format=pct,
            x_tick_format=january,
            band=(1.0, 3.0, "Target range"),
        ),
        "scatter": charts.scatter_chart(
            [
                (0.0, 20.99, 0, 16, "$0, 20.99%: 16 cards"),
                (99.0, 21.99, 0, 1, "a"),
                (0.0, 12.9, 1, 2, "b"),
            ],
            series=["With rewards", "No rewards"],
            label="Cards",
            x_format=lambda v: f"${v:.0f}",
            y_format=pct,
            x_title="Annual fee",
            y_title="Purchase rate",
        ),
        "hbar": charts.hbar_chart(
            [("Patents", 1_610_458.0), ("Series", 15_937.0), ("Tables", 67.0)],
            label="Reach",
            value_format=lambda v: f"{v:,.0f}",
            tick_format=lambda v: f"{v:g}",
        ),
        "hbar_linear": charts.hbar_chart(
            [("Statistics", 62.0), ("Energy", 5.0)],
            label="Tools",
            value_format=lambda v: f"{v:.0f}",
            log=False,
        ),
        "square": charts.square_chart(
            ["Bank of Canada", "StatCan", "CMHC <&>"],
            ["Alberta", "Edmonton", "Calgary"],
            [
                ("Statistics", "Statistics and census", 62),
                ("Money", "Money and prices", 21),
                ("Energy", "Energy", 1),
            ],
            centre="84",
            centre_lines=("tools,", "one connection"),
            label="Square",
        ),
    }


CHARTS = ["ci", "bars", "line", "step", "band", "scatter", "hbar", "hbar_linear", "square"]


@pytest.mark.parametrize("name", CHARTS)
def test_chart_is_labelled_well_formed_svg(name: str) -> None:
    svg = _all_charts()[name]
    root = _parse(svg)
    assert root.tag == f"{NS}svg"
    assert root.get("role") == "img"
    assert "chart" in _classes(root)
    assert root.get("data-chart") == ""
    assert root.get("aria-label")
    assert root.get("preserveAspectRatio") == "xMidYMid meet"
    first = root[0]
    assert first.tag == f"{NS}title"
    assert first.text == root.get("aria-label")
    width = float((root.get("viewBox") or "").split()[2])
    assert 600 <= width <= 700


@pytest.mark.parametrize("name", CHARTS)
def test_no_colour_attributes(name: str) -> None:
    root = _parse(_all_charts()[name])
    for el in root.iter():
        assert "fill" not in el.attrib, el.tag
        assert "stroke" not in el.attrib, el.tag
        assert not re.search(r"(fill|stroke|color)\s*:", el.get("style", "")), el.tag


def test_text_is_escaped() -> None:
    svg = charts.ci_chart(CI_ROWS, label='A <b> & "c"', value_format=pct)
    root = _parse(svg)
    assert root.get("aria-label") == 'A <b> & "c"'
    labels = ["".join(t.itertext()) for t in root.iter(f"{NS}text")]
    assert 'Alberta <&> "B"' in labels


def test_ci_chart_one_row_each_in_order() -> None:
    root = _parse(charts.ci_chart(CI_ROWS, label="x", value_format=pct))
    cis = [el for el in root.iter() if "c-ci" in _classes(el)]
    dots = [el for el in root.iter() if "c-dot" in _classes(el)]
    values = [el.text for el in root.iter() if "c-value" in _classes(el)]
    assert len(cis) == len(dots) == 3
    assert [el.get("style") for el in cis] == ["--i:0", "--i:1", "--i:2"]
    assert values == ["10.3%", "12.9%", "11.1%"]
    ys = [float(d.get("cy", "0")) for d in dots]
    assert ys == sorted(ys)
    grid = [el for el in root.iter() if _classes(el) == {"c-grid"}]
    assert 4 <= len(grid) <= 6


def test_grouped_bars_count_and_gaps() -> None:
    root = _parse(_all_charts()["bars"])
    bars = [el for el in root.iter(f"{NS}rect") if _classes(el) & {"c-bar", "c-bar-2"}]
    assert len(bars) == 24
    for bar in bars:
        assert "transform" not in bar.attrib
        assert (bar.get("style") or "").startswith("--i:")
    keys = [el for el in root.iter(f"{NS}rect") if _classes(el) & {"c-key", "c-key-2"}]
    assert len(keys) == 2

    gappy = charts.grouped_bars(
        ["a", "b", "c"],
        [("x", [1.0, None, 3.0]), ("y", [None, 2.0, 1.0]), ("z", [1.0, 1.0, 1.0])],
        label="gaps",
        value_format=lambda v: f"{v:.0f}",
    )
    rects = [el for el in _parse(gappy).iter(f"{NS}rect") if "c-key" not in el.get("class", "")]
    by_class = {
        c: sum(1 for r in rects if c in _classes(r)) for c in ("c-bar", "c-bar-2", "c-bar-3")
    }
    assert by_class == {"c-bar": 2, "c-bar-2": 2, "c-bar-3": 3}


def test_long_categories_rotate_inside_the_canvas() -> None:
    cats = [f"A rather long industry name number {i}" for i in range(12)]
    svg = charts.grouped_bars(
        cats, [("s", [float(i) for i in range(12)])], label="x", value_format=str
    )
    assert "rotate(" in svg
    assert "…" in svg  # truncated, with the full name in a <title>
    assert cats[0] in svg


def test_line_chart_path_ticks_and_last_point() -> None:
    root = _parse(_all_charts()["line"])
    (path,) = [el for el in root.iter(f"{NS}path") if "c-line" in _classes(el)]
    assert path.get("pathLength") == "1"
    assert (path.get("d") or "").count("L") == 59
    axis = [el.text for el in root.iter(f"{NS}text") if "c-axis" in _classes(el)]
    assert [t for t in axis if t and t.startswith("20")] == ["2015", "2016", "2017", "2018", "2019"]
    ends = [el for el in root.iter() if "c-end" in _classes(el)]
    assert any("c-dot" in _classes(e) for e in ends)
    assert any(e.text == pct(_monthly(60)[-1][1]) for e in ends)
    grid = [el for el in root.iter(f"{NS}line") if "c-grid" in _classes(el)]
    horizontal = [g for g in grid if g.get("y1") == g.get("y2")]
    assert 4 <= len(horizontal) <= 6


def test_step_chart_reduces_daily_points() -> None:
    svg = _all_charts()["step"]
    root = _parse(svg)
    (path,) = [el for el in root.iter(f"{NS}path") if "c-line" in _classes(el)]
    d = path.get("d") or ""
    # First point, four changes, last point: five horizontal runs, four risers.
    assert d.count("H") == 5
    assert d.count("V") == 4
    assert len(d) < 120
    assert len(svg) < 4000
    # A daily series labels each January once, not on all 31 days.
    axis = [el.text for el in root.iter(f"{NS}text") if "c-axis" in _classes(el)]
    years = [t for t in axis if t and t.isdigit()]
    assert years == sorted(set(years))
    assert len(years) == 9


def test_positive_series_axis_does_not_go_below_zero() -> None:
    svg = charts.step_chart(
        _daily_runs(400, [0.25, 5.0]), label="x", value_format=str, x_tick_format=january
    )
    axis = [el.text or "" for el in _parse(svg).iter(f"{NS}text") if "c-axis" in _classes(el)]
    assert not any(t.startswith("-") for t in axis)


def test_ticks_are_round_and_enclose_the_data() -> None:
    for lo, hi in [(9.5, 21.6), (0, 640), (-2.1, 4.4), (0.001, 0.049), (5, 5), (-3, -1)]:
        ticks = charts._ticks(lo, hi)
        assert 4 <= len(ticks) <= 6, (lo, hi, ticks)
        assert ticks[0] <= lo and ticks[-1] >= hi
        steps = {round(b - a, 9) for a, b in pairwise(ticks)}
        assert len(steps) == 1


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        charts.ci_chart([], label="x", value_format=pct)
    with pytest.raises(ValueError):
        charts.grouped_bars([], [("a", [])], label="x", value_format=pct)
    with pytest.raises(ValueError):
        charts.line_chart([], label="x", value_format=pct, x_tick_format=january)


def test_band_is_drawn_behind_the_line_with_its_label() -> None:
    root = _parse(_all_charts()["band"])
    order = [_classes(el) for el in root.iter()]
    band = next(i for i, c in enumerate(order) if "c-band" in c)
    line = next(i for i, c in enumerate(order) if "c-line" in c)
    assert band < line
    assert any(el.text == "Target range" for el in root.iter(f"{NS}text"))


def test_scatter_dot_area_grows_with_count_and_big_dots_go_first() -> None:
    root = _parse(_all_charts()["scatter"])
    dots = [el for el in root.iter(f"{NS}circle") if "--i" in (el.get("style") or "")]
    radii = [float(el.get("r") or 0) for el in dots]
    assert len(dots) == 3
    assert radii == sorted(radii, reverse=True)
    assert radii[0] == 16.0  # 4.5 * sqrt(16) = 18, capped at 16
    series_two = [el for el in dots if "c-pt-2" in _classes(el)]
    assert len(series_two) == 1


def test_hbar_log_grid_is_powers_of_ten_and_bars_are_ordered() -> None:
    root = _parse(_all_charts()["hbar"])
    axis = [el.text for el in root.iter(f"{NS}text") if "c-axis" in _classes(el)]
    assert axis == ["1", "10", "100", "1000", "10000", "100000", "1e+06", "1e+07"]
    widths = [
        float(el.get("width") or 0) for el in root.iter(f"{NS}rect") if "c-hbar" in _classes(el)
    ]
    assert widths == sorted(widths, reverse=True)
    with pytest.raises(ValueError):
        charts.hbar_chart([("zero", 0.0)], label="x", value_format=str)


def test_square_inscriptions_close_and_segments_share_the_track() -> None:
    root = _parse(_all_charts()["square"])
    paths = {el.get("id"): el for el in root.iter(f"{NS}path") if el.get("id")}
    text_paths = list(root.iter(f"{NS}textPath"))
    # Each band's names run in two halves, over the top and along the
    # bottom, both from the left side to the right: the only text on a path.
    hrefs = [tp.get("href") for tp in text_paths]
    assert hrefs == [f"#square-script-{n}-{h}" for n in (0, 1) for h in ("top", "bottom")]
    assert all(tp.get("href", "")[1:] in paths for tp in text_paths)
    for n in (0, 1):
        top, bottom = (paths[f"square-script-{n}-{h}"].get("d") or "" for h in ("top", "bottom"))
        start_top, start_bottom = top.split()[0], bottom.split()[0]
        # Both start on the left side, halfway down; the top one climbs
        # (clockwise arcs), the bottom one descends (anticlockwise arcs).
        assert start_top.endswith(",320") and start_bottom.endswith(",320")
        assert "0,1" in top and "0,0" in bottom
    written = "".join(tp.text or "" for tp in text_paths[:2])
    assert "CMHC <&>" in written and "Bank of Canada" in written
    # The seams are padded with non-breaking spaces, which SVG keeps.
    assert all((tp.text or "").startswith("\u00a0") for tp in text_paths)
    segments = [el for el in root.iter(f"{NS}path") if "sq-arc" in _classes(el)]
    assert len(segments) == 3
    assert all(el.get("pathLength") == "1" for el in segments)
    # The first segment (62 of 84) starts on the top and turns the corners
    # it passes: its path has more than two points.
    first = segments[0].get("d") or ""
    assert first.count("L") >= 2
    # Labels are plain text: the name and count where they fit, upright on
    # the top and bottom and turned on the sides; the 1-of-84 segment is too
    # short for any label.
    labels = [el for el in root.iter(f"{NS}text") if "sq-arc-label" in _classes(el)]
    assert [el.text for el in labels] == ["Statistics 62", "Money 21"]
    for el in labels:
        turn = el.get("transform") or ""
        assert turn == "" or re.fullmatch(r"rotate\((90|-90) [\d.]+ [\d.]+\)", turn), turn
    centre = [el for el in root.iter(f"{NS}text") if "sq-n" in _classes(el)]
    assert centre[0].text == "84" and "data-count" in centre[0].attrib
    with pytest.raises(ValueError):
        charts.square_chart([], [], [("a", "a", 1)], centre="1", centre_lines=("", ""), label="x")


def test_track_points_walk_the_square_clockwise() -> None:
    c, half = 320.0, 100.0
    assert charts._track_point(c, half, 0) == (320.0, 220.0)
    assert charts._track_point(c, half, half) == (420.0, 220.0)
    assert charts._track_point(c, half, 3 * half) == (420.0, 420.0)
    assert charts._track_point(c, half, 5 * half) == (220.0, 420.0)
    assert charts._track_point(c, half, 7 * half) == (220.0, 220.0)
    assert charts._track_point(c, half, 8 * half) == (320.0, 220.0)
    # A stretch across the top-right corner goes through it.
    assert charts._track_path(c, half, 50, 150) == "M370,220 L420,220 L420,270"
    assert charts._straight_runs(half, 50, 150) == [(50, 100.0, 0), (100.0, 150, 1)]


def test_tooltips_take_the_page_language() -> None:
    """A French page words its intervals and dates in French."""
    ci = _parse(charts.ci_chart(CI_ROWS, label="x", value_format=pct, range_word="à"))
    tips = [el.text for el in ci.iter(f"{NS}title")]
    assert "Quebec: 10.3% (9.5% à 11.2%)" in tips
    default = _parse(charts.ci_chart(CI_ROWS, label="x", value_format=pct))
    assert "Quebec: 10.3% (9.5% to 11.2%)" in [el.text for el in default.iter(f"{NS}title")]
    line = _parse(
        charts.line_chart(
            _monthly(24),
            label="x",
            value_format=pct,
            x_tick_format=january,
            date_format=lambda d: f"mois {d[:7]}",
        )
    )
    assert "mois 2015-01: 2.0%" in [el.text for el in line.iter(f"{NS}title")]


def test_responsive_adds_a_narrow_drawing_for_phones() -> None:
    """responsive() returns the chart at WIDTH and again at NARROW, each marked
    for charts.css to show one, and leaves the module's WIDTH as it was."""
    both = charts.responsive(charts.ci_chart)(CI_ROWS, label="x", value_format=pct)
    wide, narrow = (
        both[both.index(f'<svg class="chart {c}"') :] for c in ("chart-wide", "chart-narrow")
    )
    wide = _parse(wide[: wide.index("</svg>") + 6])
    narrow = _parse(narrow[: narrow.index("</svg>") + 6])
    assert (wide.get("viewBox") or "").split()[2] == str(charts.WIDTH)
    assert (narrow.get("viewBox") or "").split()[2] == str(charts.NARROW)
    assert charts.WIDTH == 640
    # Crowded tick labels are thinned in the narrow drawing, never overlapped.
    xs = sorted(float(t.get("x") or 0) for t in narrow.iter(f"{NS}text") if "c-axis" in _classes(t))
    assert all(b - a >= 40 for a, b in pairwise(xs))


def test_data_table_follows_and_is_linked_from_its_chart() -> None:
    svg = charts.ci_chart(CI_ROWS, label="x", value_format=pct)
    out = charts.with_table(
        svg,
        ident="data-ci",
        summary="Show the data",
        caption="Shares <by> province",
        head=("Province", "Estimate", "Low", "High"),
        rows=charts.ci_rows(CI_ROWS, pct),
    )
    chart, table = out.split("</svg>", 1)
    assert chart.startswith('<svg aria-details="data-ci" class="chart"')
    # Well-formed, with a caption, a header row and one row per chart row.
    root = ET.fromstring(table)
    assert root.tag == "details" and root.get("id") == "data-ci"
    assert root.findtext("summary") == "Show the data"
    tbl = root.find("div/table")
    assert tbl is not None and tbl.findtext("caption") == "Shares <by> province"
    rows = tbl.findall("tbody/tr")
    assert [r.findtext("th") for r in rows] == [name for name, *_ in CI_ROWS]
    assert [td.text for td in rows[0].findall("td")] == ["10.3%", "9.5%", "11.2%"]
    with pytest.raises(ValueError):
        charts.with_table(svg, ident="x", summary="s", caption="c", head=("a",), rows=[["a", "b"]])


def test_table_rows_come_from_the_chart_series() -> None:
    bars = charts.bar_rows(["2020", "2021"], [("A", [1.0, None]), ("B", [2.0, 3.0])], pct)
    assert bars == [["2020", "1.0%", "2.0%"], ["2021", "–", "3.0%"]]
    # A step chart's table lists the days the value changes, not every day.
    daily = _daily_runs(900, [1.0, 1.5, 0.5])
    steps = charts.time_rows(daily, pct, steps=True)
    assert [value for _, value in steps] == ["1.0%", "1.5%", "0.5%", "0.5%"]
    assert steps[0][0] == daily[0][0] and steps[-1][0] == daily[-1][0]
    # A long series summarised by year: average, lowest, highest.
    yearly = charts.yearly_rows(_monthly(24), pct)
    assert [row[0] for row in yearly] == ["2015", "2016"]
    assert yearly[0][2:] == ["2.0%", "3.8%"]
    points = [(10.0, 20.0, 1, 2, "b"), (0.0, 19.0, 0, 1, "a")]
    assert charts.scatter_rows(points, ["S0", "S1"], str, str) == [
        ["S0", "0.0", "19.0", "1"],
        ["S1", "10.0", "20.0", "2"],
    ]
    assert charts.square_rows([("A", "A: x", 3)], str) == [["A: x", "3"]]

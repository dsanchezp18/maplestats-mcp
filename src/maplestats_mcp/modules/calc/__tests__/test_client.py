"""calc_ tools end to end, with the WDS and Valet reads replaced by fakes.

The fakes return what the real clients returned on 2026-11-07: 14-10-0287's
Alberta (v2064512) and Canada (v2062811) employment in thousands, its
provincial unemployment rates, and Valet V39079 (business daily, Percent).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from maplestats_mcp.modules.boc import client as boc
from maplestats_mcp.modules.boc.schemas import Observation, ObservationsResult, SeriesInfoBrief
from maplestats_mcp.modules.calc import client
from maplestats_mcp.modules.calc.schemas import SeriesRef
from maplestats_mcp.modules.statcan.wds import client as wds
from maplestats_mcp.modules.statcan.wds import context
from maplestats_mcp.modules.statcan.wds.schemas import (
    FailedVector,
    ObservationRow,
    SeriesContext,
    VectorDataSet,
    VectorSeries,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound

GEOS = {
    2: "Newfoundland and Labrador",
    6: "Quebec",
    10: "Alberta",
}
# vector -> (coordinate, title, geography, unit, scalar code, {period: value})
SERIES: dict[int, tuple[str, str, str, str, int, dict[str, float]]] = {
    2064512: (
        "10.3.1.1.1.1",
        "Alberta;Employment",
        "Alberta",
        "Persons in thousands",
        3,
        {"2025-08-01": 2600.0, "2025-09-01": 2608.5},
    ),
    2062811: (
        "1.3.1.1.1.1",
        "Canada;Employment",
        "Canada",
        "Persons in thousands",
        3,
        {"2025-09-01": 21009.9},
    ),
    2063004: (
        "2.7.1.1.1.1",
        "NL;Unemployment rate",
        "Newfoundland and Labrador",
        "Percent",
        0,
        {"2025-09-01": 10.5},
    ),
    2064706: (
        "10.7.1.1.1.1",
        "Alberta;Unemployment rate",
        "Alberta",
        "Percent",
        0,
        {"2025-09-01": 7.7},
    ),
    2063950: (
        "6.7.1.1.1.1",
        "Quebec;Unemployment rate",
        "Quebec",
        "Percent",
        0,
        {"2025-09-01": 5.7},
    ),
    41690973: (
        "2.2",
        "Canada;All-items",
        "Canada",
        "2002=100",
        0,
        {"2015-01-01": 124.3, "2025-01-01": 161.3},
    ),
}
BY_COORD = {coord: vector for vector, (coord, *_rest) in SERIES.items()}


def _prov() -> Any:
    return make_provenance(source="statcan-wds", url="https://x/", cached=False, schema_name="t")


def _vector(vector_id: int, first: date | None = None, last: date | None = None) -> VectorSeries:
    coord, _, _, _, scalar, values = SERIES[vector_id]
    rows = [
        ObservationRow(
            ref_period=date.fromisoformat(day),
            value=value,
            decimals=1,
            scalar_factor_code=scalar,
            scale_multiplier=10**scalar,
            symbol_code=0,
            status_code=0,
            security_level_code=0,
            release_time=datetime(2026, 4, 10, 12, 30, tzinfo=UTC),
        )
        for day, value in values.items()
        if (first is None or date.fromisoformat(day) >= first)
        and (last is None or date.fromisoformat(day) <= last)
    ]
    return VectorSeries(
        product_id=14100287, coordinate=coord, vector_id=vector_id, observations=rows
    )


@pytest.fixture
def fake_sources(monkeypatch):
    calls: dict[str, list[Any]] = {"range": [], "latest": [], "boc": []}

    async def by_range(ids, start, end):
        calls["range"].append((ids, start, end))
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        known = [v for v in ids if v in SERIES]
        return VectorDataSet(
            series=[_vector(v, first, last) for v in known],
            failed=[FailedVector(vector_id=v, reason="no data") for v in ids if v not in SERIES],
            provenance=_prov(),
        )

    async def latest(ids, n):
        calls["latest"].append((ids, n))
        return VectorDataSet(series=[_vector(v) for v in ids], provenance=_prov())

    async def info_by_coord(pid, coordinate):
        if coordinate not in BY_COORD:
            raise NotFound(f"no series {coordinate}")
        return SimpleNamespace(vector_id=BY_COORD[coordinate])

    async def series_info(ids):
        return {v: {"frequencyCode": 6, "productId": "14100287"} for v in ids}

    async def describe(series):
        out = []
        for s in series:
            _, title, geo, unit, scalar, _ = SERIES[s.vector_id]
            ctx = SeriesContext(
                citation=f"Statistics Canada. Table 14-10-0287-01. Vector v{s.vector_id}.",
                table_id="14-10-0287-01",
                table_url="https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410028701",
                series_title=title,
                unit=unit,
                scale="thousands" if scalar == 3 else "units",
                frequency="Monthly",
                geography=geo,
            )
            out.append(s.model_copy(update={"context": ctx}))
        return out, None

    async def cube(pid):
        members = (
            [{"memberId": 1, "memberNameEn": "Canada"}]
            + [{"memberId": m, "memberNameEn": n} for m, n in GEOS.items()]
            + [{"memberId": 11, "memberNameEn": "British Columbia"}]
        )
        return {"dimension": [{"dimensionPositionId": 1, "member": members}]}, False

    async def valet(names, *, start_date=None, end_date=None, recent=None, lang="en", **_):
        calls["boc"].append((names, start_date, end_date, recent))
        days = [
            (date(2023, 12, 29), 5.0),
            (date(2024, 6, 5), 5.0),
            (date(2024, 6, 6), 4.75),
            (date(2024, 12, 12), 3.25),
        ]
        rows = [
            Observation(ref_date=d, values={"V39079": v})
            for d, v in days
            if (start_date is None or d.isoformat() >= start_date)
            and (end_date is None or d.isoformat() <= end_date)
        ]
        return ObservationsResult(
            series={
                "V39079": SeriesInfoBrief(
                    name="V39079",
                    label="Target for the overnight rate (business daily)",
                    description="",
                    unit="Percent",
                    frequency="Business daily",
                )
            },
            observations=rows,
            provenance=make_provenance(
                source="boc", url="https://x/", cached=False, schema_name="t"
            ),
        )

    monkeypatch.setattr(wds, "get_data_from_vector_by_reference_period_range", by_range)
    monkeypatch.setattr(wds, "get_data_from_vectors_and_latest_n_periods", latest)
    monkeypatch.setattr(wds, "get_series_info_from_cube_pid_coord", info_by_coord)
    monkeypatch.setattr(wds, "cube_metadata_raw", cube)
    monkeypatch.setattr(context, "series_info_raw", series_info)
    monkeypatch.setattr(context, "describe", describe)
    monkeypatch.setattr(boc, "get_observations", valet)
    return calls


async def test_ratio_scales_cites_and_lists_values_used(fake_sources):
    result = await client.ratio(
        SeriesRef(product_id="14-10-0287", coordinate="10.3.1.1.1.1"),
        SeriesRef(vector_id=2062811),
        start="2025-08",
        end="2025-09",
        latest_n=1,
        frequency=None,
        aggregation="average",
        multiplier=100,
        lang="en",
    )
    assert [p.period for p in result.points] == ["2025-09"]
    assert result.points[0].numerator == 2_608_500
    assert result.points[0].value == pytest.approx(2608.5 / 21009.9 * 100)
    assert result.unit == "percent"
    assert result.numerator.citation.endswith("Vector v2064512.")
    assert result.numerator.release == "2026-04-10"
    assert [v.period for v in result.numerator.values_used] == ["2025-09"]
    assert result.provenance.source == "statcan-wds"
    assert fake_sources["range"][0][1:] == ("2025-08-01", "2025-09-30")


async def test_ratio_latest_reads_extra_periods(fake_sources):
    result = await client.ratio(
        SeriesRef(vector_id=2064512),
        SeriesRef(vector_id=2062811),
        start=None,
        end=None,
        latest_n=1,
        frequency=None,
        aggregation="average",
        multiplier=1,
        lang="en",
    )
    assert fake_sources["latest"] == [([2064512, 2062811], 13)]
    assert result.points[0].period == "2025-09"


async def test_ratio_refuses_bad_arguments(fake_sources):
    with pytest.raises(InvalidInput, match="exactly one"):
        await client.ratio(
            SeriesRef(vector_id=1, boc_series="V39079"),
            SeriesRef(vector_id=2062811),
            start=None,
            end=None,
            latest_n=1,
            frequency=None,
            aggregation="average",
            multiplier=1,
            lang="en",
        )
    with pytest.raises(InvalidInput, match="latest_n"):
        await client.ratio(
            SeriesRef(vector_id=2064512),
            SeriesRef(vector_id=2062811),
            start=None,
            end=None,
            latest_n=0,
            frequency=None,
            aggregation="average",
            multiplier=1,
            lang="en",
        )
    with pytest.raises(NotFound, match="v999"):
        await client.ratio(
            SeriesRef(vector_id=999),
            SeriesRef(vector_id=2062811),
            start="2025-09",
            end="2025-09",
            latest_n=1,
            frequency=None,
            aggregation="average",
            multiplier=1,
            lang="en",
        )


async def test_rank_expands_a_starred_coordinate(fake_sources):
    result = await client.rank(
        None,
        product_id="14-10-0287",
        coordinate="*.7.1.1.1.1",
        exclude_member_ids=[1],
        period="2025-09",
        order="descending",
        frequency=None,
        aggregation="average",
        lang="en",
    )
    # British Columbia (11) has no series in the fake table: left out, not an error.
    assert [(e.rank, e.label, e.value) for e in result.entries] == [
        (1, "Newfoundland and Labrador", 10.5),
        (2, "Alberta", 7.7),
        (3, "Quebec", 5.7),
    ]
    assert result.unit == "Percent"
    assert result.entries[0].series.id == "v2063004"


async def test_rank_needs_a_star_and_one_input_form(fake_sources):
    with pytest.raises(InvalidInput, match="exactly one '\\*'"):
        await client.rank(
            None,
            product_id="14100287",
            coordinate="1.7.1.1.1.1",
            exclude_member_ids=None,
            period=None,
            order="descending",
            frequency=None,
            aggregation="average",
            lang="en",
        )
    with pytest.raises(InvalidInput, match="not both"):
        await client.rank(
            [SeriesRef(vector_id=2063004)],
            product_id="14100287",
            coordinate="*.7",
            exclude_member_ids=None,
            period=None,
            order="descending",
            frequency=None,
            aggregation="average",
            lang="en",
        )
    with pytest.raises(InvalidInput, match="2 to"):
        await client.rank(
            [SeriesRef(vector_id=2063004)],
            product_id=None,
            coordinate=None,
            exclude_member_ids=None,
            period=None,
            order="descending",
            frequency=None,
            aggregation="average",
            lang="en",
        )


async def test_cagr_end_to_end(fake_sources):
    result = await client.growth(
        SeriesRef(vector_id=41690973),
        start="2015-01",
        end="2025-01",
        frequency=None,
        aggregation="average",
        lang="fr",
    )
    assert result.years == 10
    assert result.cagr_percent == pytest.approx(((161.3 / 124.3) ** 0.1 - 1) * 100)
    assert result.formula.startswith("TCAC")
    assert [v.period for v in result.series.values_used] == ["2015-01", "2025-01"]


async def test_count_changes_reads_a_year_before_for_the_baseline(fake_sources):
    result = await client.count_changes(
        SeriesRef(boc_series="V39079"), start="2024", end="2024", threshold=0, lang="en"
    )
    assert fake_sources["boc"][0][1:3] == ("2023-01-01", "2024-12-31")
    assert result.changes == 2 and result.decreases == 2
    assert result.change_unit == "percentage points"
    assert result.baseline is not None and result.baseline.period == "2023-12-29"
    assert result.series.citation.startswith("Bank of Canada. Valet series V39079")
    assert result.series.periods_per_year is None
    assert result.provenance.source == "boc"
    with pytest.raises(InvalidInput, match="threshold"):
        await client.count_changes(
            SeriesRef(boc_series="V39079"), start="2024", end=None, threshold=-1, lang="en"
        )


async def test_mixed_sources_monthly_over_daily_is_refused(fake_sources):
    with pytest.raises(InvalidInput, match="do not share a frequency"):
        await client.ratio(
            SeriesRef(vector_id=2064512),
            SeriesRef(boc_series="V39079"),
            start="2024",
            end="2025",
            latest_n=1,
            frequency=None,
            aggregation="average",
            multiplier=1,
            lang="en",
        )


def test_valet_frequency_words():
    assert client._valet_ppy("Monthly", []) == 12
    assert client._valet_ppy("Business daily", []) is None
    assert client._valet_ppy("Trimestrielle", []) == 4
    assert client._valet_ppy(None, [date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]) == 1


def test_mixed_sources_name_both_in_provenance():
    from maplestats_mcp.modules.calc.compute import Loaded
    from maplestats_mcp.modules.calc.schemas import InputSeries

    def loaded(source: Literal["statcan", "boc"]) -> Loaded:
        info = InputSeries(source=source, id="x", citation="c", url="https://u/", frequency="f")
        return Loaded(info=info, points=[])

    provenance = client._provenance([loaded("statcan"), loaded("boc")], "calc.T", "en")
    assert provenance.source == "statcan-wds,boc"
    assert "Bank of Canada" in (provenance.coverage or "")

"""Series context on WDS data, explained missing series, error fixes, caveats by result.

Payloads are trimmed copies of live WDS answers read on 2026-11-02 for the
series CanData's GTA benchmark asks about: v3823103 (Toronto two-bedroom rent,
34-10-0133) and v96415851 (Toronto median after-tax income, 11-10-0190).
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import NotFoundError, ToolError

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.wds import client, constants, context
from maplestats_mcp.modules.statcan.wds.schemas import ObservationRow, VectorSeries
from maplestats_mcp.shared.error_hints import with_hint
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable
from maplestats_mcp.shared.response_budget import caveats_for, result_product_ids

RENT_CUBE = {
    "productId": "34100133",
    "cubeTitleEn": "Canada Mortgage and Housing Corporation, average rents for areas with a "
    "population of 10,000 and over",
    "cubeTitleFr": "Société canadienne d'hypothèques et de logement, loyers moyens",
    "cubeStartDate": "1987-01-01",
    "cubeEndDate": "2025-01-01",
    "releaseTime": "2025-12-17T08:30",
    "frequencyCode": 12,
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "dimensionNameFr": "Géographie",
            "member": [
                {"memberId": 104, "memberNameEn": "Oshawa, Ontario", "memberNameFr": "Oshawa"},
                {"memberId": 125, "memberNameEn": "Toronto, Ontario", "memberNameFr": "Toronto"},
            ],
        },
        {
            "dimensionPositionId": 2,
            "dimensionNameEn": "Type of structure",
            "dimensionNameFr": "Type de structure",
            "member": [
                {
                    "memberId": 3,
                    "memberNameEn": "Row and apartment structures of three units and over",
                    "memberNameFr": "Logements en bandes et appartements de trois logements et plus",
                }
            ],
        },
        {
            "dimensionPositionId": 3,
            "dimensionNameEn": "Type of unit",
            "dimensionNameFr": "Type de logement",
            "member": [
                {
                    "memberId": 3,
                    "memberNameEn": "Two bedroom units",
                    "memberNameFr": "Deux chambres",
                }
            ],
        },
    ],
}

INCOME_CUBE = {
    "productId": "11100190",
    "cubeTitleEn": "Market income, government transfers, total income, income tax and "
    "after-tax income by economic family type",
    "cubeTitleFr": "Revenu du marché ... selon le type de famille économique",
    "cubeStartDate": "1976-01-01",
    "cubeEndDate": "2024-01-01",
    "releaseTime": "2026-04-29T08:30",
    "frequencyCode": 12,
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "dimensionNameFr": "Géographie",
            "member": [
                {"memberId": 17, "memberNameEn": "Toronto, Ontario", "memberNameFr": "Toronto"}
            ],
        },
        {
            "dimensionPositionId": 2,
            "dimensionNameEn": "Income concept",
            "dimensionNameFr": "Concept de revenu",
            "member": [
                {
                    "memberId": 12,
                    "memberNameEn": "Median after-tax income",
                    "memberNameFr": "Revenu après impôt médian",
                    "memberUomCode": 455,
                }
            ],
        },
        {
            "dimensionPositionId": 3,
            "dimensionNameEn": "Economic family type",
            "dimensionNameFr": "Type de famille économique",
            "member": [
                {
                    "memberId": 1,
                    "memberNameEn": "Economic families and persons not in an economic family",
                    "memberNameFr": "Familles économiques et personnes hors famille économique",
                }
            ],
        },
    ],
}

CODE_SETS = {
    "status": "SUCCESS",
    "object": {
        "scalar": [
            {"scalarFactorCode": 0, "scalarFactorDescEn": "units", "scalarFactorDescFr": "unités"}
        ],
        "frequency": [
            {"frequencyCode": 12, "frequencyDescEn": "Annual", "frequencyDescFr": "Annuelle"}
        ],
        "uom": [
            {"memberUomCode": 81, "memberUomEn": "Dollars", "memberUomFr": "Dollars"},
            {
                "memberUomCode": 455,
                "memberUomEn": "2024 constant dollars",
                "memberUomFr": "Dollars constants de 2024",
            },
        ],
        "symbol": [],
        "status": [],
        "securityLevel": [],
    },
}


def _info(vector, pid, coord, title, uom):
    return {
        "status": "SUCCESS",
        "object": {
            "responseStatusCode": 0,
            "productId": pid,
            "coordinate": coord,
            "vectorId": vector,
            "frequencyCode": 12,
            "scalarFactorCode": 0,
            "decimals": 0,
            "terminated": 0,
            "SeriesTitleEn": title,
            "SeriesTitleFr": title,
            "memberUomCode": uom,
        },
    }


def _obs(day, value):
    return ObservationRow(
        ref_period=day,
        value=value,
        decimals=0,
        scalar_factor_code=0,
        symbol_code=0,
        status_code=0,
        security_level_code=0,
    )


RENT = VectorSeries(
    product_id=34100133,
    coordinate="125.3.3.0.0.0.0.0.0.0",
    vector_id=3823103,
    observations=[_obs("2025-01-01", 2045.0)],
)
INCOME = VectorSeries(
    product_id=11100190,
    coordinate="17.12.1.0.0.0.0.0.0.0",
    vector_id=96415851,
    observations=[_obs("2024-01-01", 82500.0)],
)


def _metadata(httpx_mock):
    # getSeriesInfoFromVector answers a batch out of request order (live 2026-11-02).
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getSeriesInfoFromVector",
        json=[
            _info(
                96415851,
                11100190,
                "17.12.1.0.0.0.0.0.0.0",
                "Toronto, Ontario;Median after-tax income;Economic families and persons not in "
                "an economic family",
                455,
            ),
            _info(
                3823103,
                34100133,
                "125.3.3.0.0.0.0.0.0.0",
                "Toronto, Ontario;Row and apartment structures of three units and over;Two "
                "bedroom units",
                81,
            ),
        ],
        is_optional=True,
    )
    for cube in (RENT_CUBE, INCOME_CUBE):
        httpx_mock.add_response(
            url=f"{constants.BASE_URL}getCubeMetadata",
            match_json=[{"productId": int(cube["productId"])}],
            json=[{"status": "SUCCESS", "object": cube}],
            is_optional=True,
        )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCodeSets", json=CODE_SETS, is_optional=True, is_reusable=True
    )


async def test_context_names_table_unit_and_members(httpx_mock):
    _metadata(httpx_mock)
    client.use_lang("en")
    series, note = await context.describe([RENT, INCOME])
    assert note is None
    rent, income = (s.context for s in series)
    assert rent is not None and income is not None
    assert rent.table_id == "34-10-0133-01"
    assert rent.table_url == "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3410013301"
    assert rent.unit == "Dollars" and rent.geography == "Toronto, Ontario"
    assert [m.member for m in rent.members][1:] == [
        "Row and apartment structures of three units and over",
        "Two bedroom units",
    ]
    assert rent.table_release_time == "2025-12-17T08:30"
    assert any("current (nominal) dollars" in n for n in rent.notes)
    # The GT-08 trap: income is in constant dollars, rent in current dollars.
    assert income.unit == "2024 constant dollars"
    assert any("inflation-adjusted" in n for n in income.notes)
    assert income.members[2].member.startswith("Economic families and persons")


async def test_context_in_french(httpx_mock):
    _metadata(httpx_mock)
    client.use_lang("fr")
    try:
        series, _ = await context.describe([INCOME])
    finally:
        client.use_lang("en")
    described = series[0].context
    assert described is not None
    assert described.unit == "Dollars constants de 2024"
    assert described.table_url.startswith("https://www150.statcan.gc.ca/t1/tbl1/fr/")
    assert described.members[0].dimension == "Géographie"


async def test_empty_window_states_the_series_span(httpx_mock):
    _metadata(httpx_mock)
    # Rows from 1987, values from 1992, as v3823103 has (live 2026-11-02).
    points = [
        {"refPer": f"{year}-01-01", "value": None if year < 1992 else 1000.0 + year}
        for year in range(1987, 2026)
    ]
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getDataFromVectorsAndLatestNPeriods",
        json=[{"status": "SUCCESS", "object": {"vectorId": 3823103, "vectorDataPoint": points}}],
    )
    client.use_lang("en")
    empty = RENT.model_copy(update={"observations": []})
    series, _ = await context.describe([empty])
    notes = series[0].context.notes  # type: ignore[union-attr]
    assert any("values from 1992-01-01 to 2025-01-01 only" in n for n in notes)


async def test_metadata_outage_keeps_the_data(httpx_mock):
    httpx_mock.add_exception(
        UpstreamUnavailable("down"), url=f"{constants.BASE_URL}getSeriesInfoFromVector"
    )
    httpx_mock.add_exception(
        UpstreamUnavailable("down"), url=f"{constants.BASE_URL}getCubeMetadata"
    )
    httpx_mock.add_response(url=f"{constants.BASE_URL}getCodeSets", json=CODE_SETS)
    client.use_lang("en")
    series, note = await context.describe([RENT])
    assert series[0].observations == RENT.observations
    assert series[0].context is not None and series[0].context.table_id == "34-10-0133-01"
    assert note is not None and "getSeriesInfoFromVector" in note


async def test_missing_combination_says_it_is_not_published(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata",
        json=[{"status": "SUCCESS", "object": RENT_CUBE}],
    )
    client.use_lang("en")
    with pytest.raises(NotFound, match="does not publish a series for this combination") as info:
        await client.explain_missing_coordinate(34100133, "104.3.3.0.0.0.0.0.0.0", "m")
    assert "Geography = Oshawa, Ontario" in str(info.value) and "Fix:" in str(info.value)


async def test_unknown_member_names_the_dimension(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata",
        json=[{"status": "SUCCESS", "object": RENT_CUBE}],
    )
    client.use_lang("en")
    with pytest.raises(InvalidInput, match=r"dimension 1 \(Geography\) .* no member 999"):
        await client.explain_missing_coordinate(34100133, "999.3.3.0.0.0.0.0.0.0", "m")


async def test_unknown_table_points_to_search(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}getCubeMetadata",
        json=[{"status": "FAILED", "object": "The cube product ID 99999999 does not exist."}],
    )
    client.use_lang("en")
    with pytest.raises(NotFound, match="wds_search_cubes"):
        await client.explain_missing_coordinate(99999999, "1.1.0.0.0.0.0.0.0.0", "m")


def test_error_hints_by_class_and_cause():
    wrapped = ToolError("Error calling tool 'x': no match")
    wrapped.__cause__ = NotFound("no match")
    hinted = with_hint(wrapped, "en")
    assert isinstance(hinted, ToolError) and "do not estimate" in str(hinted)
    plain = with_hint(UpstreamUnavailable("timed out"), "fr")
    assert isinstance(plain, UpstreamUnavailable) and isinstance(plain, ToolError)
    assert "Solution" in str(plain)
    assert "search_tools" in str(with_hint(NotFoundError("Unknown tool: 'x'"), "en"))
    assert with_hint(NotFound("Fix: already said"), "en") is None


def test_caveats_follow_the_result_tables():
    payload = {"series": [{"product_id": 18100004}, {"product_id": 34100133}], "provenance": {}}
    found = result_product_ids(payload)
    assert found == [18100004, 34100133]
    notes = caveats_for("wds_get_data_from_vectors", {"_result_product_ids": found}, "en")
    assert any("Mortgage interest cost is published for Canada alone" in n for n in notes)
    assert any("not an asking rent" in n for n in notes)
    assert caveats_for("wds_get_data_from_vectors", {"vector_ids": [41692889]}, "en") == []


def test_file_export_is_opt_in(monkeypatch):
    monkeypatch.setenv("MAPLE_TRANSPORT", "stdio")
    monkeypatch.delenv("MAPLE_EXPORT_DIR", raising=False)
    assert config.local_exports_enabled() is False
    monkeypatch.setenv("MAPLE_EXPORT_DIR", "exports")
    assert config.local_exports_enabled() is True
    monkeypatch.setenv("MAPLE_TRANSPORT", "http")
    assert config.local_exports_enabled() is False


async def test_sdmx_series_get_context_by_vector(httpx_mock):
    _metadata(httpx_mock)
    client.use_lang("en")
    found, note = await context.describe_vectors([96415851], set())
    assert note is None
    assert found[96415851].unit == "2024 constant dollars"
    assert found[96415851].table_id == "11-10-0190-01"


def test_sdmx_dataflow_counts_as_a_table():
    payload = {"dataflow_id": "DF_11100190", "series": [], "provenance": {}}
    assert result_product_ids(payload) == [11100190]
    notes = caveats_for("sdmx_get_data", {"_result_product_ids": [11100190]}, "en")
    assert any("Economic families and persons not in an economic family" in n for n in notes)

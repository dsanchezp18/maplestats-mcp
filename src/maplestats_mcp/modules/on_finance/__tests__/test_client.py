"""Ontario population projections, against workbooks laid out as seen live on 2026-11-24.

Each workbook is built with the live layout: a title row, a "Sources: ..." row
naming the release in parentheses, a blank row, the age-band row, the header row,
a blank row, then the data. English and French files share one resource name; the
interim update exists for Ontario and its components only; census division names
carry trailing spaces; the public health unit file ends with Mean and Median Age.
"""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from openpyxl import Workbook

from maplestats_mcp.modules.on_finance import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = "https://data.ontario.ca/dataset/f52a6457/resource/{rid}/download/{name}"
FILES = {
    "ontario": (
        "Ontario MOF Population Projections",
        "ontario_mof_population_projections_2025-2051.xlsx",
    ),
    "ontario_fr": (
        "Ontario MOF Population Projections",
        "ontario_projections_demographiques_du_mdf_2025_a_2051.xlsx",
    ),
    "interim": (
        "Interim Ontario MOF Population Projections",
        "interim_update_ontario_mof_population_projections_for_2026-2051.xlsx",
    ),
    "cd": (
        "49 Census Divisions MOF Population Projections",
        "49_census_divisions_mof_population_projections_2025-2051.xlsx",
    ),
    "phu": (
        "34 Public Health Units MOF Population Projections",
        "34_public_health_units_mof_population_projections_2025-2051.xlsx",
    ),
    "components": (
        "Interim Components of Provincial Demographic Change MOF Population Projections",
        (
            "interim_update_components_of_provincial_demographic_change_mof_population_"
            "projections_2026-2051.xlsx"
        ),
    ),
}
AGES = ["0 to 14", "15 to 64", "65 Plus", "0 to 4", "5 to 9", "90 Plus", 0, 1, "90+"]
BANDS = ["BROAD AGE GROUPS", None, None, "5-YEAR AGE GROUPS", None, None, "SINGLE-YEAR OF AGE"]


def _url(key: str) -> str:
    return BASE.format(rid=f"r-{key}", name=FILES[key][1])


def _bytes(book: Workbook) -> bytes:
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _top(sheet, title: str, release: str) -> None:
    sheet.append([title])
    sheet.append(
        [f"Sources: Statistics Canada and Ontario Ministry of Finance projections ({release})."]
    )
    sheet.append([])


def _ontario(first: int, release: str) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    _top(sheet, "Population Projections by Scenario for Ontario by Age and Gender", release)
    sheet.append([None, None, None, None, *BANDS])
    sheet.append(["SCENARIO", "YEAR (JULY 1)", "GENDER", "TOTAL", *AGES])
    sheet.append([])
    for scenario, extra in (("REFERENCE", 0), ("LOW-GROWTH", -10), ("HIGH-GROWTH", 10)):
        for year in (first, 2051):
            bump = 0 if year == first else extra
            for gender, total in (("MEN+", 50), ("WOMEN+", 50), ("TOTAL ALL GENDERS", 100)):
                value = total + bump
                sheet.append([scenario, year, gender, value, *[value // 9] * 9])
    return _bytes(book)


def _areas(names: list[tuple[int, str]], all_label: str, extra: bool = False) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    _top(sheet, "Population Projections for areas by Age and Gender", "Summer 2026")
    tail = ["Mean Age", "Median Age"] if extra else []
    sheet.append([None, None, None, None, None, *BANDS])
    sheet.append(["YEAR (JULY 1)", "REGION CODE", "REGION NAME", "GENDER", "TOTAL", *AGES, *tail])
    sheet.append([])
    for year in (2025, 2051):
        for code, name in names:
            for gender, total in (("MEN+", 40), ("WOMEN+", 60), (all_label, 100)):
                sheet.append(
                    [
                        year,
                        code,
                        name,
                        gender,
                        total * code,
                        *[1] * 9,
                        *([41.5, 40.2] if extra else []),
                    ]
                )
    return _bytes(book)


def _components() -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Projected Components of Demographic Change by Scenario for Ontario, 2026-2051"])
    sheet.append(
        ["Sources: Statistics Canada and Ontario Ministry of Finance (Fall 2026 Interim Update)."]
    )
    sheet.append(["Note: Total growth may not add up to the sum of components due to rounding."])
    sheet.append([])
    sheet.append(
        ["SCENARIO", "PERIOD", "START POPULATION (JULY 1)", "BIRTHS", "DEATHS", "NATURAL INCREASE"]
        + ["NET INTERPROVINCIAL MIGRATION", "RATE OF TOTAL POPULATION CHANGE (%)"]
    )
    sheet.append([])
    sheet.append(["REFERENCE", "2026-27", 16262121, 145548, 127382, 18166, -11500, 0.4789])
    sheet.append(["REFERENCE", 2051, 20342410])
    sheet.append(["LOW-GROWTH", "2026-27", 16262121, 140000, 128000, 12000, -15000, 0.1])
    return _bytes(book)


def _package() -> dict:
    return {
        "success": True,
        "result": {
            "id": "f52a6457",
            "name": "population-projections",
            "title": "Population projections",
            "license_id": "OGL-ON-1.0",
            "resources": [
                {"id": f"r-{key}", "name": name, "format": "XLSX", "url": _url(key), "size": 1000}
                for key, (name, _file) in FILES.items()
            ],
        },
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def ontario(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r"https://data\.ontario\.ca/api/3/action/package_show\?.*"),
        json=_package(),
        is_reusable=True,
    )
    books = {
        "ontario": _ontario(2025, "Summer 2026"),
        "interim": _ontario(2026, "Fall 2026 Interim Update"),
        "cd": _areas(
            [(1, "TORONTO"), (4, "PEEL "), (8, "HALDIMAND-NORFOLK  ")], "TOTAL BOTH GENDERS"
        ),
        "phu": _areas([(3895, "Toronto Public Health")], "TOTAL ALL GENDERS", extra=True),
        "components": _components(),
    }
    for key, body in books.items():
        httpx_mock.add_response(url=_url(key), content=body, is_reusable=True, is_optional=True)


async def test_latest_reads_the_interim_update(ontario):
    result = await client.get_population_projection()
    assert result.interim and result.release == "Fall 2026 Interim Update"
    assert result.base_year == 2026
    assert [(r.year, r.projected, r.total) for r in result.rows] == [
        (2026, False, 100),
        (2051, True, 100),
    ]
    assert all(r.area == "Ontario" and r.scenario == "reference" for r in result.rows)
    assert "Open Government Licence - Ontario" in result.licence
    assert result.provenance.commercial_use == "allowed"


async def test_annual_release_and_every_scenario(ontario):
    result = await client.get_population_projection(release="annual", scenario="any", gender="any")
    assert not result.interim and result.base_year == 2025
    assert {r.scenario for r in result.rows} == {"reference", "low", "high"}
    assert {r.gender for r in result.rows} == {"men+", "women+", "all"}
    high = [r for r in result.rows if r.scenario == "high" and r.year == 2051 and r.gender == "all"]
    assert high[0].total == 110


async def test_age_groups_follow_the_band_row(ontario):
    broad = await client.get_population_projection(age_groups="broad", end_year=2026)
    assert list((broad.rows[0].ages or {}).keys()) == ["0 to 14", "15 to 64", "65 Plus"]
    single = await client.get_population_projection(age_groups="single_year", end_year=2026)
    assert list((single.rows[0].ages or {}).keys()) == ["0", "1", "90+"]


async def test_census_divisions_by_name_or_code(ontario):
    every = await client.get_population_projection(geography="census_division", end_year=2025)
    assert [a.name for a in every.areas] == ["TORONTO", "PEEL", "HALDIMAND-NORFOLK"]
    assert [r.total for r in every.rows] == [100, 400, 800]
    peel = await client.get_population_projection(geography="census_division", area="peel")
    assert {r.area for r in peel.rows} == {"PEEL"} and peel.rows[-1].year == 2051
    by_code = await client.get_population_projection(geography="census_division", area="8")
    assert by_code.rows[0].area == "HALDIMAND-NORFOLK"


async def test_public_health_units_carry_mean_and_median_age(ontario):
    result = await client.get_population_projection(
        geography="public_health_unit", area="toronto", age_groups="single_year", start_year=2051
    )
    row = result.rows[0]
    assert row.mean_age == 41.5 and row.median_age == 40.2
    assert "Mean Age" not in (row.ages or {})


async def test_components(ontario):
    result = await client.get_projection_components(scenario="any")
    assert result.interim and result.release == "Fall 2026 Interim Update"
    assert [(r.scenario, r.period) for r in result.rows] == [
        ("reference", "2026-27"),
        ("reference", "2051"),
        ("low", "2026-27"),
    ]
    first = result.rows[0]
    assert first.births == 145548 and first.net_interprovincial == -11500
    assert first.growth_rate_percent == pytest.approx(0.4789)
    assert result.rows[1].births is None
    assert result.provenance.limits and "immigration" in result.provenance.limits
    assert any(n.startswith("Note:") for n in result.notes)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"geography": "census_division", "scenario": "high"},
        {"area": "Toronto"},
        {"geography": "census_division", "age_groups": "single_year"},
        {"start_year": 2051, "end_year": 2030},
    ],
)
async def test_bad_arguments_are_refused(kwargs):
    with pytest.raises(InvalidInput):
        await client.get_population_projection(**kwargs)


async def test_an_ambiguous_area_is_refused(ontario):
    with pytest.raises(InvalidInput, match="matches 2 areas"):
        await client.get_population_projection(geography="census_division", area="o")


def _declared_a1(body: bytes) -> bytes:
    """The same workbook with the sheet's <dimension> cut to A1, as one writer leaves it."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(body)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"', b'<dimension ref="A1"', data)
            target.writestr(item, data)
    return out.getvalue()


def test_a_sheet_declared_as_a1_is_still_read_whole():
    # Confirmed live on other workbooks (shared/xlsx_sheets.fix_dimensions): a lone
    # A1 made openpyxl yield one row, so the header row was never reached and the
    # file was reported as no longer having it.
    declared = _declared_a1(_ontario(2025, "Summer 2026"))
    assert b'<dimension ref="A1"' in zipfile.ZipFile(io.BytesIO(declared)).read(
        "xl/worksheets/sheet1.xml"
    )
    sheet = client.parse_workbook(declared)
    assert sheet.header[:4] == ["SCENARIO", "YEAR (JULY 1)", "GENDER", "TOTAL"]
    assert sheet.release == "Summer 2026"
    # Three scenarios x two years x three genders.
    assert len(sheet.rows) == 18


async def test_a_missing_file_says_so(ontario):
    with pytest.raises(NotFound):
        await client.get_population_projection(geography="region")

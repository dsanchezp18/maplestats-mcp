"""Tests for jobbank/client.py, shaped on the live payloads read 2026-11-03."""

from __future__ import annotations

import json
import re

import pytest

from maplestats_mcp.modules.jobbank import client, constants
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_R2025 = "res-2025"
_R2024 = "res-2024"
_R2023 = "res-2023"

_PACKAGE = {
    "success": True,
    "result": {
        "id": constants.PACKAGE_ID,
        "resources": [
            {
                "id": _R2025,
                "name": "2025 Wages",
                "name_translated": {"en": "2025 Wages", "fr": "Salaires de 2025"},
                "datastore_active": True,
            },
            {"id": _R2024, "name": "2024 Wages", "datastore_active": True},
            # 2023's English name had a trailing space in other years ("2018 Wages ").
            {"id": _R2023, "name": "2023 Wages ", "datastore_active": "true"},
            {"id": "res-2022", "name": "2022 Wages", "datastore_active": True},
            {"id": "pdf", "name": "Data dictionary", "datastore_active": False},
        ],
    },
}

# Field list of the 2025 resource (live); 2023 spells the titles NOC_TITLE_ENG/FRA.
_FIELDS_2025 = [
    {"id": name, "type": "text"}
    for name in (
        "_id",
        "NOC_CNP",
        "NOC_Title_eng",
        "NOC_Title_fra",
        "prov",
        "ER_Code_Code_RE",
        "ER_Name",
        "Nom_RE",
        "Low_Wage_Salaire_Minium",
        "Median_Wage_Salaire_Median",
        "High_Wage_Salaire_Maximal",
        "Average_Wage_Salaire_Moyen",
        "Quartile1_Wage_Salaire_Quartile1",
        "Quartile3_Wage_Salaire_Quartile3",
        "Source2025_NHQ",
        "Data_Source_E",
        "Data_Source_F",
        "Reference_Period",
        "Revision_Date_Date_revision",
        "Annual_Wage_Flag_Salaire_annuel",
        "Wage_Comment_E",
        "Wage_Comment_F",
        "EmployeesWithNonWageBenefit_Pct",
    )
]


def _row(
    noc="NOC_21231",
    title=(
        "Software engineers and designers",
        "Ingénieurs/ingénieures et concepteurs/conceptrices en logiciel",
    ),
    prov="ON",
    er=("ER3530", "Toronto", "Toronto"),
    wages=("36.06", "56.49", "88.94"),
    source=("Labour Force Survey", "Enquête sur la population active", "LFS 2023-24 ER NOC5"),
    period="2023-2024",
    annual="0",
    comment=(None, None),
):
    return {
        "NOC_CNP": noc,
        "NOC_Title_eng": title[0],
        "NOC_Title_fra": title[1],
        "prov": prov,
        "ER_Code_Code_RE": er[0],
        "ER_Name": er[1],
        "Nom_RE": er[2],
        "Low_Wage_Salaire_Minium": wages[0],
        "Median_Wage_Salaire_Median": wages[1],
        "High_Wage_Salaire_Maximal": wages[2],
        "Average_Wage_Salaire_Moyen": "59.97" if wages[1] else None,
        "Quartile1_Wage_Salaire_Quartile1": None,
        "Quartile3_Wage_Salaire_Quartile3": None,
        "Source2025_NHQ": source[2],
        "Data_Source_E": source[0],
        "Data_Source_F": source[1],
        "Reference_Period": period,
        "Revision_Date_Date_revision": "2025-11-19",
        "Annual_Wage_Flag_Salaire_annuel": annual,
        "Wage_Comment_E": comment[0],
        "Wage_Comment_F": comment[1],
        "EmployeesWithNonWageBenefit_Pct": None,
    }


_NAT_21231 = _row(
    prov="NAT",
    er=("ER00", "Canada", "Canada"),
    wages=("35", "56.49", "91.35"),
    source=("Labour Force Survey", "Enquête sur la population active", "LFS 2023-24 CAN NOC5"),
)
_NAT_21232 = _row(
    noc="NOC_21232",
    title=(
        "Software developers and programmers",
        "Développeurs/développeuses et programmeurs/programmeuses de logiciels",
    ),
    prov="NAT",
    er=("ER00", "Canada", "Canada"),
    wages=("28", "48.08", "75"),
)
_NAT_00010 = _row(
    noc="NOC_00010",
    title=("Legislators", "Membres des corps législatifs"),
    prov="NAT",
    er=("ER00", "Canada", "Canada"),
    wages=("32867", "84000", "184000"),
    source=("2021 Census", "Recensement 2021", "Census 2021 CAN NOC5"),
    period="2021",
    annual="1",
)
_NATIONAL = [_NAT_00010, _NAT_21231, _NAT_21232]

_UNPUBLISHED = (
    (
        "Due to data limitations, the wage for this occupation cannot be published. Please refer "
        "to the wage published for this occupation at the provincial level."
    ),
    (
        "En raison des limites associées aux données, le salaire pour cette profession ne peut "
        "être diffusé."
    ),
)
_GEOS_21231 = [
    _NAT_21231,
    _row(
        er=("ER35", "Ontario", "Ontario"),
        wages=("36.06", "56.73", "88"),
        source=("Labour Force Survey", "Enquête sur la population active", "LFS 2023-24 PR NOC5"),
    ),
    # Ottawa shows Ontario's wage: its source code says PR (live 2025 row).
    _row(
        er=("ER3510", "Ottawa", "Ottawa"),
        wages=("36.06", "56.73", "88"),
        source=("Labour Force Survey", "Enquête sur la population active", "LFS 2023-24 PR NOC5"),
    ),
    _row(),
    _row(er=("ER3590", "Northeast", "Nord-est"), wages=("23.5", "48.08", "86.54")),
    _row(
        prov="BC",
        er=("ER5980", "Northeast", "Nord-est"),
        wages=(None, None, None),
        source=("NA", "NA", "N/A"),
        period="NA",
        comment=_UNPUBLISHED,
    ),
    _row(prov="QC", er=("ER2440", "Montréal", "Montréal"), wages=("31.53", "52.88", "82.42")),
]


def _ds(records, fields=None, total=None):
    return {
        "success": True,
        "result": {
            "records": records,
            "fields": fields if fields is not None else _FIELDS_2025,
            "total": len(records) if total is None else total,
        },
    }


def _filters(request) -> dict:
    return json.loads(request.url.params["filters"])


def _mock(httpx_mock, *, national=_NATIONAL, geos=_GEOS_21231, extra=None, package=_PACKAGE):
    """Answer package_show and datastore_search by the filters each request carries."""

    def answer(request):
        import httpx

        url = str(request.url)
        if "package_show" in url:
            return httpx.Response(200, json=package)
        filters = _filters(request)
        if filters == {"ER_Code_Code_RE": "ER00"}:
            return httpx.Response(200, json=_ds(national))
        noc = filters.get("NOC_CNP")
        if isinstance(noc, str):
            rows = [r for r in geos if r["NOC_CNP"] == noc]
            first = national[0]["NOC_CNP"] if national else None
            if noc == first and not rows:
                rows = [dict(r, NOC_CNP=noc) for r in geos]
            return httpx.Response(200, json=_ds(rows))
        if isinstance(noc, list):
            pool = [*(extra or []), *geos, *national]
            rows = [
                r
                for r in pool
                if r["NOC_CNP"] in noc and r["ER_Code_Code_RE"] == filters["ER_Code_Code_RE"]
            ]
            return httpx.Response(200, json=_ds(rows))
        return httpx.Response(200, json=_ds([]))

    httpx_mock.add_callback(answer, is_reusable=True)


async def test_search_by_words_picks_newest_release_and_cites_it(httpx_mock):
    _mock(httpx_mock)
    result = await client.search_occupations("software engineer")
    assert [m.noc_code for m in result.matches] == ["21231"]
    match = result.matches[0]
    assert match.national_median_wage == 56.49
    assert match.wage_unit == "hourly"
    assert match.reference_period == "2023-2024"
    assert match.data_source == "Labour Force Survey"
    assert result.release.release_year == 2025
    assert result.release.resource_id == _R2025
    # NOC 2016 releases (2022 and older) are not offered.
    assert result.release.available_years == [2025, 2024, 2023]
    assert "Job Bank" in result.release.citation and _R2025 in result.release.citation
    assert result.provenance.licence and "Open Government Licence" in result.provenance.licence
    assert "not a Statistics Canada table" in (result.provenance.limits or "")
    request = next(r for r in httpx_mock.get_requests() if "datastore_search" in str(r.url))
    assert request.url.params["resource_id"] == _R2025


async def test_search_french_words_ignore_accents_and_digits_match_prefix(httpx_mock):
    _mock(httpx_mock)
    french = await client.search_occupations("developpeurs logiciels", lang="fr")
    assert [m.noc_code for m in french.matches] == ["21232"]
    assert "Guichet-Emplois" in french.release.citation
    prefix = await client.search_occupations("NOC 2123")
    assert [m.noc_code for m in prefix.matches] == ["21231", "21232"]


async def test_annual_occupation_is_flagged(httpx_mock):
    _mock(httpx_mock)
    result = await client.search_occupations("00010")
    assert result.matches[0].wage_unit == "annual"
    assert result.matches[0].national_median_wage == 84000


async def test_get_wages_for_one_region(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_wages("21231", region="toronto")
    assert result.returned_count == 1
    row = result.rows[0]
    assert (row.region_code, row.province, row.geography_level) == (
        "ER3530",
        "ON",
        "economic_region",
    )
    assert (row.low_wage, row.median_wage, row.high_wage) == (36.06, 56.49, 88.94)
    assert row.data_source == "Labour Force Survey" and row.reference_period == "2023-2024"
    assert row.estimate_geography == "economic_region"
    assert result.provenance.as_of and result.provenance.as_of.date().isoformat() == "2025-11-19"
    request = [r for r in httpx_mock.get_requests() if "datastore_search" in str(r.url)][-1]
    assert _filters(request) == {"NOC_CNP": "NOC_21231"}


async def test_get_wages_marks_unpublished_cells_and_provincial_stand_ins(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_wages("NOC_21231")
    assert result.returned_count == len(_GEOS_21231)
    canada = result.rows[0]
    assert canada.province is None and canada.geography_level == "national"
    ottawa = next(r for r in result.rows if r.region_code == "ER3510")
    assert ottawa.estimate_geography == "provincial"
    bc_northeast = next(r for r in result.rows if r.region_code == "ER5980")
    assert not bc_northeast.published
    assert bc_northeast.data_source is None and bc_northeast.reference_period is None
    assert bc_northeast.comment and "provincial level" in bc_northeast.comment
    assert result.unpublished_count == 1
    ontario = await client.get_wages("21231", province="on", published_only=True)
    assert {r.region_code for r in ontario.rows} == {"ER35", "ER3510", "ER3530", "ER3590"}


async def test_region_resolution(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(InvalidInput, match="ER3590 Northeast \\(ON\\); ER5980 Northeast \\(BC\\)"):
        await client.get_wages("21231", region="Northeast")
    narrowed = await client.get_wages("21231", region="Northeast", province="BC")
    assert narrowed.rows[0].region_code == "ER5980"
    by_code = await client.get_wages("21231", region="3530")
    assert by_code.rows[0].region_name == "Toronto"
    by_province = await client.get_wages("21231", region="ON")
    assert by_province.rows[0].region_code == "ER35"
    accents = await client.get_wages("21231", region="montreal", lang="fr")
    assert accents.rows[0].region_name == "Montréal"
    assert accents.rows[0].data_source == "Enquête sur la population active"
    with pytest.raises(NotFound, match="jobbank_list_regions"):
        await client.get_wages("21231", region="Atlantis")


async def test_bad_inputs_are_typed(httpx_mock):
    _mock(httpx_mock)
    with pytest.raises(InvalidInput, match="five-digit"):
        await client.get_wages("2123")
    with pytest.raises(InvalidInput, match="province"):
        await client.get_wages("21231", province="Ontario")
    with pytest.raises(NotFound, match="jobbank_search_occupations"):
        await client.get_wages("99999")
    with pytest.raises(InvalidInput, match="2025, 2024, 2023"):
        await client.get_wages("21231", release_year=2022)
    with pytest.raises(InvalidInput, match="query"):
        await client.search_occupations("  ")
    with pytest.raises(InvalidInput, match="2 to 25"):
        await client.compare_occupations(["21231", "NOC_21231"])


async def test_release_year_reads_that_resource(httpx_mock):
    _mock(httpx_mock)
    result = await client.search_occupations("software", release_year=2023)
    assert result.release.release_year == 2023
    assert all(
        r.url.params["resource_id"] == _R2023
        for r in httpx_mock.get_requests()
        if "datastore_search" in str(r.url)
    )


async def test_compare_occupations_in_a_region(httpx_mock):
    dev_toronto = dict(_row(), NOC_CNP="NOC_21232", Median_Wage_Salaire_Median="48.08")
    _mock(httpx_mock, extra=[dev_toronto])
    result = await client.compare_occupations(["21232", "21231", "31102"], region="Toronto")
    assert result.region_code == "ER3530"
    assert [r.noc_code for r in result.rows] == ["21232", "21231"]
    assert result.not_found == ["31102"]
    assert not result.mixed_units
    request = [r for r in httpx_mock.get_requests() if "datastore_search" in str(r.url)][-1]
    assert _filters(request) == {
        "ER_Code_Code_RE": "ER3530",
        "NOC_CNP": ["NOC_21232", "NOC_21231", "NOC_31102"],
    }


async def test_compare_flags_mixed_units_in_canada(httpx_mock):
    _mock(httpx_mock)
    result = await client.compare_occupations(["00010", "21231"])
    assert result.region_code == "ER00"
    assert result.mixed_units


async def test_compare_with_a_province_reads_its_row_not_canada(httpx_mock):
    # region defaults to "Canada"; province="ON" alone returned the national row.
    _mock(httpx_mock)
    result = await client.compare_occupations(["21232", "21231"], province="ON")
    assert result.region_code == "ER35"
    request = [r for r in httpx_mock.get_requests() if "datastore_search" in str(r.url)][-1]
    assert _filters(request)["ER_Code_Code_RE"] == "ER35"


async def test_list_regions_by_province(httpx_mock):
    _mock(httpx_mock)
    result = await client.list_regions("ON")
    assert [r.region_code for r in result.regions] == ["ER35", "ER3510", "ER3530", "ER3590"]
    assert result.regions[0].geography_level == "provincial"
    every = await client.list_regions()
    assert every.regions[0].region_code == "ER00"


async def test_columns_are_resolved_case_insensitively_2023(httpx_mock):
    fields = [
        {
            "id": f["id"]
            .replace("NOC_Title_eng", "NOC_TITLE_ENG")
            .replace("NOC_Title_fra", "NOC_TITLE_FRA")
        }
        for f in _FIELDS_2025
        if f["id"] not in ("Source2025_NHQ", "EmployeesWithNonWageBenefit_Pct")
    ]
    national = [
        {
            (
                "NOC_TITLE_ENG"
                if k == "NOC_Title_eng"
                else "NOC_TITLE_FRA"
                if k == "NOC_Title_fra"
                else k
            ): v
            for k, v in dict(_NAT_21231, prov="NA").items()
            if k not in ("Source2025_NHQ", "EmployeesWithNonWageBenefit_Pct")
        }
    ]

    def answer(request):
        import httpx

        if "package_show" in str(request.url):
            return httpx.Response(200, json=_PACKAGE)
        return httpx.Response(200, json=_ds(national, fields=fields))

    httpx_mock.add_callback(answer, is_reusable=True)
    result = await client.search_occupations("software", release_year=2023)
    assert result.matches[0].title_en == "Software engineers and designers"
    wages = await client.get_wages("21231", release_year=2023)
    assert wages.rows[0].province is None  # "NA" is the 2023 national code
    assert wages.rows[0].source_detail is None and wages.rows[0].estimate_geography is None


async def test_changed_layout_is_an_upstream_error(httpx_mock):
    fields = [f for f in _FIELDS_2025 if f["id"] != "Median_Wage_Salaire_Median"]

    def answer(request):
        import httpx

        if "package_show" in str(request.url):
            return httpx.Response(200, json=_PACKAGE)
        return httpx.Response(200, json=_ds(_NATIONAL, fields=fields))

    httpx_mock.add_callback(answer, is_reusable=True)
    with pytest.raises(UpstreamError, match="median_wage_salaire_median"):
        await client.search_occupations("software")


async def test_package_without_wage_resources_falls_back_to_pinned(httpx_mock):
    empty = {"success": True, "result": {"id": constants.PACKAGE_ID, "resources": []}}
    _mock(httpx_mock, package=empty)
    result = await client.search_occupations("software")
    assert result.release.resource_id == constants.FALLBACK_RESOURCE_ID
    assert result.release.note and "Fallback" in result.release.note
    assert "Fallback" in (result.provenance.limits or "")


async def test_ckan_error_envelope_is_typed(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*package_show.*"),
        json={"success": False, "error": {"message": "Not found", "__type": "Not Found Error"}},
    )
    with pytest.raises(UpstreamError):
        await client.search_occupations("software")

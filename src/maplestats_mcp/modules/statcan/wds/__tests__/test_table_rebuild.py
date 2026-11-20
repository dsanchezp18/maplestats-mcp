"""wds_get_full_table_download's WDS rebuild: its size, its member checks, and its script.

Since November 2026 StatCan answers scripted downloads of full-table zips with a
captcha on some networks but serves WDS everywhere. The script asks WDS for every series and writes StatCan's CSV layout;
live on 2026-11-18 its output was byte for byte StatCan's own file for 36-10-0104,
18-10-0004 (from 2024-01) and 14-10-0287 (from 2025-06). The idea comes from
vrraiv/sixfigures PR #105 (reimplemented: that repository has no licence file).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.reproduce import wds_table
from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.shared.errors import InvalidInput

WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"


def _member(mid, name, **extra):
    return {
        "memberId": mid,
        "memberNameEn": name,
        "memberNameFr": {"Food": "Aliments", "All-items": "Ensemble"}.get(name, name),
        "terminated": 0,
        "memberUomCode": None,
        "vintage": None,
        "geoLevel": None,
        "classificationCode": None,
        **extra,
    }


CUBE = {
    "productId": "99100001",
    "cubeStartDate": "2026-01-01",
    "cubeEndDate": "2026-03-01",
    "frequencyCode": 6,
    "nbSeriesCube": 3,
    "dimension": [
        {
            "dimensionPositionId": 1,
            "dimensionNameEn": "Geography",
            "dimensionNameFr": "Géographie",
            "hasUom": False,
            "member": [
                _member(1, "Canada", vintage=2016, geoLevel=0, classificationCode="11124"),
                _member(
                    5, "Toronto, Ontario", vintage=2011, geoLevel=503, classificationCode="535"
                ),
            ],
        },
        {
            "dimensionPositionId": 2,
            "dimensionNameEn": "Products",
            "dimensionNameFr": "Produits",
            "hasUom": True,
            # Listed out of id order: the CSV follows this order, not the ids.
            "member": [
                _member(7, "All-items", memberUomCode=17),
                _member(2, "Food", memberUomCode=17),
            ],
        },
    ],
}

CODES = {
    "uom": [{"memberUomCode": 17, "memberUomEn": "2002=100", "memberUomFr": "2002=100"}],
    "scalar": [{"scalarFactorCode": 0, "scalarFactorDescEn": "units", "scalarFactorDescFr": "unités"}],
    "status": [
        {"statusCode": "0", "statusRepresentationEn": None, "statusRepresentationFr": None},
        {"statusCode": "1", "statusRepresentationEn": "..", "statusRepresentationFr": ".."},
    ],
    "symbol": [
        {"symbolCode": "0", "symbolRepresentationEn": None, "symbolRepresentationFr": None},
        {"symbolCode": "1", "symbolRepresentationEn": "p", "symbolRepresentationFr": "p"},
    ],
    "securityLevel": [
        {"securityLevelCode": 0, "securityLevelRepresentationEn": None,
         "securityLevelRepresentationFr": None},
        {"securityLevelCode": 1, "securityLevelRepresentationEn": "x",
         "securityLevelRepresentationFr": "x"},
    ],
}  # fmt: skip


def _point(month, value, status=0, symbol=0, secret=0, released: str | None = "2026-04-15T08:30"):
    return {
        "refPer": f"2026-0{month}-01",
        "value": value,
        "decimals": 1,
        "scalarFactorCode": 0,
        "symbolCode": symbol,
        "statusCode": status,
        "securityLevelCode": secret,
        "releaseTime": released,
    }


def _series(coordinate, vector, points):
    return {"status": "SUCCESS", "object": {"coordinate": coordinate, "vectorId": vector,
                                            "vectorDataPoint": points}}  # fmt: skip


@pytest.fixture
def cube(monkeypatch):
    async def metadata(pid):
        return CUBE, True

    monkeypatch.setattr(client, "cube_metadata_raw", metadata)


async def test_the_rebuild_is_sized_and_scripted(cube):
    rebuild, scripts = await client._rebuild(99100001, None, None, None)
    assert rebuild is not None
    assert (rebuild.combinations, rebuild.periods_per_series, rebuild.wds_calls) == (4, 4, 1)
    assert rebuild.within_limit and scripts[0].language == "python"
    assert "PRODUCT_ID = 99100001" in scripts[0].code
    assert "Mozilla" not in scripts[0].code  # it names itself


async def test_members_and_periods_narrow_the_rebuild(cube):
    rebuild, scripts = await client._rebuild(99100001, {"geography": ["canada"]}, "2026-02", None)
    assert rebuild is not None and rebuild.combinations == 2
    assert "MEMBERS = {'geography': ['canada']}" in scripts[0].code
    assert "START_PERIOD = '2026-02'" in scripts[0].code


async def test_an_unknown_dimension_member_or_period_is_refused(cube):
    with pytest.raises(InvalidInput, match="no dimension"):
        await client._rebuild(99100001, {"Sex": ["Males"]}, None, None)
    with pytest.raises(InvalidInput, match="not in 'Geography'"):
        await client._rebuild(99100001, {"Geography": ["Atlantis"]}, None, None)
    with pytest.raises(InvalidInput, match="start_period"):
        await client._rebuild(99100001, None, "January 2026", None)


async def test_a_rebuild_past_the_limit_has_no_script(cube, monkeypatch):
    monkeypatch.setattr(wds_table, "MAX_CALLS", 0)
    rebuild, scripts = await client._rebuild(99100001, None, None, None)
    assert rebuild is not None and not rebuild.within_limit and scripts == []
    assert "over the limit" in client._rebuild_notes(rebuild, "en")[0]


def _mock_wds(httpx_mock):
    httpx_mock.add_response(
        url=f"{WDS}getCubeMetadata", json=[{"status": "SUCCESS", "object": CUBE}]
    )
    httpx_mock.add_response(url=f"{WDS}getCodeSets", json={"status": "SUCCESS", "object": CODES})
    httpx_mock.add_response(
        url=f"{WDS}getDataFromCubePidCoordAndLatestNPeriods",
        # Out of the order asked, as WDS answers; Toronto x Food is not published.
        json=[
            _series("5.7.0.0.0.0.0.0.0.0", 103, [_point(1, None, secret=1), _point(2, 30.8)]),
            {"status": "FAILED", "object": {"coordinate": "5.2.0.0.0.0.0.0.0.0"}},
            _series("1.2.0.0.0.0.0.0.0.0", 102, [_point(1, None, status=1), _point(2, 25.0)]),
            _series(
                "1.7.0.0.0.0.0.0.0.0",
                101,
                # The last point is WDS padding (no release time): left out.
                [_point(1, 19.7), _point(2, 20.25, symbol=1), _point(3, None, 1, released=None)],
            ),
        ],
    )


def _run(script: str, output: Path) -> str:
    namespace: dict = {"__name__": "rebuild"}
    exec(script, namespace)  # noqa: S102
    namespace["wds_rebuild"](output)
    return output.read_bytes().decode("utf-8")


def test_the_script_writes_statcans_csv_layout_with_its_code_sets(httpx_mock, tmp_path):
    _mock_wds(httpx_mock)
    text = _run(wds_table.rebuild_script(99100001), tmp_path / "table.csv")
    request = json.loads(httpx_mock.get_requests()[-1].content)
    assert [r["coordinate"] for r in request][:2] == ["1.7.0.0.0.0.0.0.0.0", "1.2.0.0.0.0.0.0.0.0"]
    assert {r["latestN"] for r in request} == {4}
    assert text.startswith("﻿")
    h = '"REF_DATE","GEO","DGUID","Products","UOM","UOM_ID","SCALAR_FACTOR","SCALAR_ID",'
    h += '"VECTOR","COORDINATE","VALUE","STATUS","SYMBOL","TERMINATED","DECIMALS"'
    canada = '"Canada","2016A000011124"'
    toronto = '"Toronto, Ontario","2011S0503535"'
    tail = '"2002=100","17","units","0"'
    assert text[1:].split("\n") == [
        h,
        f'"2026-01",{canada},"All-items",{tail},"v101","1.7","19.7","","","","1"',
        f'"2026-01",{canada},"Food",{tail},"v102","1.2","","..","","","1"',
        f'"2026-01",{toronto},"All-items",{tail},"v103","5.7","","x","","","1"',
        f'"2026-02",{canada},"All-items",{tail},"v101","1.7","20.2","","p","","1"',
        f'"2026-02",{canada},"Food",{tail},"v102","1.2","25.0","","","","1"',
        f'"2026-02",{toronto},"All-items",{tail},"v103","5.7","30.8","","","","1"',
        "",
    ]


@pytest.mark.parametrize(
    ("start", "expected"),
    [("2025", 23), ("2025-01", 23), ("2025-01-15", 23), (None, 611)],
)
def test_periods_to_ask_reads_every_ref_date_form(start, expected):
    """A bare year raised ValueError from wds_get_full_table_download until 2026-11-20."""
    monthly = {"cubeStartDate": "1976-01-01", "cubeEndDate": "2026-10-01", "frequencyCode": 6}
    assert wds_table.periods_to_ask(monthly, start) == expected


def test_the_french_edition_uses_french_code_sets_names_and_separator(httpx_mock, tmp_path):
    # Checked live 2026-11-20 against StatCan's French files (17-10-0009 whole, and
    # 18-10-0004 and 14-10-0287 slices): ";" between fields, "." in numbers.
    httpx_mock.add_response(
        url=f"{WDS}getCubeMetadata", json=[{"status": "SUCCESS", "object": CUBE}]
    )
    httpx_mock.add_response(url=f"{WDS}getCodeSets", json={"status": "SUCCESS", "object": CODES})
    httpx_mock.add_response(
        url=f"{WDS}getDataFromCubePidCoordAndLatestNPeriods",
        json=[
            {"status": "FAILED", "object": {"coordinate": "5.2.0.0.0.0.0.0.0.0"}},
            _series("1.2.0.0.0.0.0.0.0.0", 102, [_point(1, None, status=1), _point(2, 25.0)]),
        ],
    )
    script = wds_table.rebuild_script(99100001, {"Produits": ["Aliments"]}, lang="fr")
    assert 'OUTPUT = Path("data/raw/99100001-fra-wds.csv")' in script
    lines = _run(script, tmp_path / "table.csv")[1:].split("\n")
    assert lines[0].startswith('"PÉRIODE DE RÉFÉRENCE";"GÉO";"DGUID";"Produits";"UNITÉ DE MESURE"')
    assert lines[0].endswith('"SYMBOLE";"TERMINÉ";"DÉCIMALES"')
    request = json.loads(httpx_mock.get_requests()[-1].content)
    # French member names pick the same members (Food is member 2).
    assert [r["coordinate"] for r in request] == ["1.2.0.0.0.0.0.0.0.0", "5.2.0.0.0.0.0.0.0.0"]
    assert lines[2] == (
        '"2026-02";"Canada";"2016A000011124";"Aliments";"2002=100";"17";"unités";"0";'
        '"v102";"1.2";"25.0";"";"";"";"1"'
    )


@pytest.mark.parametrize(
    ("code", "point", "expected"),
    [
        (6, {"refPer": "2026-01-01"}, "2026-01"),
        (9, {"refPer": "2026-04-01"}, "2026-04"),
        (12, {"refPer": "2025-01-01"}, "2025"),
        # Occasional (2,585 tables) writes a year; 11-10-0016, checked 2026-11-20.
        (18, {"refPer": "1999-01-01"}, "1999"),
        # Occasional daily: 17-10-0009's quarterly estimates write the whole date.
        (21, {"refPer": "1946-01-01"}, "1946-01-01"),
        (1, {"refPer": "2026-11-19"}, "2026-11-19"),
        # Two ends: a fiscal year (35-10-0044) or a five-year span (13-10-0064).
        (12, {"refPer": "1991-04-01", "refPer2": "1992-03-31"}, "1991/1992"),
        (16, {"refPer": "1994-01-01", "refPer2": "1998-12-31"}, "1994/1998"),
    ],
)
def test_ref_date_takes_the_form_statcans_csv_writes(code, point, expected):
    namespace: dict = {"__name__": "rebuild"}
    exec(wds_table.rebuild_script(99100001), namespace)  # noqa: S102
    assert namespace["wds_ref_date"](point, code) == expected


async def test_members_may_be_named_in_french(cube):
    rebuild, scripts = await client._rebuild(
        99100001, {"Géographie": ["Canada"], "produits": ["aliments"]}, None, None, "fr"
    )
    assert rebuild is not None and rebuild.combinations == 1
    assert "LANG = 'fr'" in scripts[0].code


def test_occasional_daily_and_biweekly_tables_ask_for_enough_periods():
    # 17-10-0009 (occasional daily, 21): a period can fall on any day. Biweekly (4):
    # 26 a year. Before 2026-11-20 both were counted as monthly.
    daily = {"cubeStartDate": "2026-01-01", "cubeEndDate": "2026-07-01", "frequencyCode": 21}
    assert wds_table.periods_to_ask(daily, None) == 183
    biweekly = {"cubeStartDate": "2025-01-01", "cubeEndDate": "2025-12-01", "frequencyCode": 4}
    assert wds_table.periods_to_ask(biweekly, None) == 27

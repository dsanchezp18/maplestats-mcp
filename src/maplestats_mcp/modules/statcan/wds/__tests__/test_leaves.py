"""wds_get_leaf_members against getCubeMetadata trimmed from live answers.

fixtures/leaf_metadata.json holds real members (ids, parents, names, codes,
geoLevel, units) of 18-10-0004 (CPI), 14-10-0287 (LFS) and 36-10-0434 (GDP
by industry), fetched 2026-11-03 and cut down with every kept member's
parent kept too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.wds import client, constants, leaves, tools
from maplestats_mcp.shared.errors import InvalidInput

METADATA_URL = f"{constants.BASE_URL}getCubeMetadata"
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "leaf_metadata.json").read_text(encoding="utf-8")
)


def _mock(httpx_mock, pid: int | dict) -> None:
    obj = pid if isinstance(pid, dict) else FIXTURE[str(pid)]
    httpx_mock.add_response(
        url=METADATA_URL, method="POST", json=[{"status": "SUCCESS", "object": obj}]
    )


@pytest.fixture(autouse=True)
def _english():
    client.use_lang("en")


async def test_cpi_products_drop_parents_and_flag_other_hierarchies(httpx_mock):
    _mock(httpx_mock, 18100004)
    result = await leaves.get_leaf_members("18-10-0004-01", 2)

    # All-items > Food > ... parents are left out; the leaves under All-items stay.
    assert result.member_ids == [24, 26, 28, 31, 328]
    assert result.member_ids_csv == "24,26,28,31,328"
    assert result.parent_count == 11
    assert result.leaf_count == 9
    # Real CPI special aggregates are separate top-level members or trees.
    flagged = {x.member_id: x.flags for x in result.flagged_leaves}
    assert flagged == {
        275: ["outside_main_hierarchy"],  # Durable goods, under Goods and services
        283: ["outside_main_hierarchy"],  # Services excluding shelter services
        284: ["total_name", "outside_main_hierarchy"],  # All-items excluding food
        288: ["outside_main_hierarchy"],  # Energy
    }
    assert result.selected_count == 5 and result.flagged_count == 4
    butter = result.leaves[0]
    assert (butter.member_name, butter.parent_member_id, butter.parent_name) == (
        "Butter",
        22,
        "Dairy products",
    )
    assert [x.terminated for x in result.leaves] == [False, False, False, False, True]
    assert result.top_level_members[0].member_name == "All-items"
    assert result.top_level_members[0].leaf_count == 5
    assert result.sdmx_key_fragment == "24+26+28+31+328"
    assert result.sdmx_key == ".24+26+28+31+328"
    assert result.example_coordinates == ["2.24", "2.26", "2.28"]
    assert any("'All-items' (2)" in n for n in result.notes)
    assert any("terminated" in n for n in result.notes)
    assert result.provenance.source == "statcan-wds"
    assert result.provenance.limits is None


async def test_include_flagged_keeps_every_leaf(httpx_mock):
    _mock(httpx_mock, 18100004)
    result = await leaves.get_leaf_members(18100004, 2, include_flagged=True)
    # In metadata order, which is not id order.
    assert result.member_ids == [24, 26, 28, 31, 328, 284, 288, 275, 283]
    assert result.flagged_leaves == []
    assert next(x for x in result.leaves if x.member_id == 284).flags == [
        "total_name",
        "outside_main_hierarchy",
    ]


async def test_under_member_id_keeps_one_branch(httpx_mock):
    _mock(httpx_mock, 18100004)
    dairy = await leaves.get_leaf_members(18100004, 2, under_member_id=21)
    assert dairy.member_ids == [24, 26, 28]  # Butter, Ice cream, Eggs
    assert dairy.parent_count == 2  # Dairy products and eggs, Dairy products
    # Another tree, chosen on purpose, is not flagged as outside the main one.
    goods = await leaves.get_leaf_members(18100004, 2, under_member_id=273)
    assert goods.member_ids == [275, 283]
    assert goods.flagged_leaves == []


async def test_cpi_geography_leaves_are_cities_not_provinces(httpx_mock):
    _mock(httpx_mock, 18100004)
    result = await leaves.get_leaf_members(18100004, 1)
    # Ontario (14) and British Columbia (26) are parents of their CMAs.
    assert result.member_ids == [15, 16, 27, 29]
    assert result.geo_levels == {"505": 1, "503": 2, "5": 1}
    assert any("geographic levels" in n for n in result.notes)
    assert result.example_coordinates[0] == "15.2"


async def test_lfs_provinces_are_leaves_and_rates_are_set_aside(httpx_mock):
    _mock(httpx_mock, 14100287)
    geo = await leaves.get_leaf_members("14-10-0287", 1)
    assert [x.member_name for x in geo.leaves] == ["Quebec", "Ontario", "Alberta"]
    assert geo.geo_levels == {"2": 3}
    assert geo.sdmx_key == "6+7+10....."
    assert geo.example_coordinates == ["6.1.1.1.1.1", "7.1.1.1.1.1", "10.1.1.1.1.1"]

    chars = await leaves.get_leaf_members(14100287, 2)
    assert [x.member_name for x in chars.leaves] == [
        "Full-time employment",
        "Part-time employment",
        "Unemployment",
    ]
    assert [x.member_id for x in chars.flagged_leaves] == [7, 8, 9]


async def test_flat_dimension_says_overlaps_are_invisible(httpx_mock):
    _mock(httpx_mock, 14100287)
    ages = await leaves.get_leaf_members(14100287, 4)
    assert ages.member_ids == [1, 2, 3, 4]
    assert ages.parent_count == 0 and ages.flagged_leaves == []
    assert any("No member of this dimension has a parent" in n for n in ages.notes)


async def test_gender_total_is_a_parent_not_a_leaf(httpx_mock):
    _mock(httpx_mock, 14100287)
    gender = await leaves.get_leaf_members(14100287, 3)
    assert gender.member_ids == [2, 3]
    assert gender.leaves[0].parent_name == "Total - Gender"


async def test_naics_special_aggregates_are_flagged(httpx_mock):
    _mock(httpx_mock, 36100434)
    result = await leaves.get_leaf_members("36-10-0434", 4)
    assert result.member_ids == [24, 25, 29, 30]
    assert {x.classification_code: x.flags for x in result.flagged_leaves} == {
        "T002": ["special_aggregate"],
        "T014": ["special_aggregate"],
        "T015": ["special_aggregate"],
        "T016": ["special_aggregate"],
    }
    assert result.sdmx_key == "...24+25+29+30"
    assert result.example_coordinates[0] == "1.1.1.24"


async def test_canada_alone_is_a_total_that_is_also_a_leaf(httpx_mock):
    _mock(httpx_mock, 36100434)
    result = await leaves.get_leaf_members(36100434, 1)
    assert result.member_ids == []
    assert [(x.member_name, x.flags) for x in result.flagged_leaves] == [("Canada", ["total_name"])]


async def test_flat_total_member_is_flagged(httpx_mock):
    # 98-10-0002, "Population and dwelling counts": flat, with live names.
    def member(member_id, en, fr):
        return {
            "memberId": member_id,
            "parentMemberId": None,
            "memberNameEn": en,
            "memberNameFr": fr,
            "terminated": 0,
        }

    cube = {
        "productId": 98100002,
        "dimension": [
            {
                "dimensionPositionId": 1,
                "dimensionNameEn": "Geographic name",
                "dimensionNameFr": "Nom géographique",
                "member": [member(1, "Canada", "Canada")],
            },
            {
                "dimensionPositionId": 2,
                "dimensionNameEn": "Population and dwelling counts (13)",
                "dimensionNameFr": "Chiffres de population et des logements (13)",
                "member": [
                    member(1, "Population, 2021", "Population, 2021"),
                    member(4, "Total private dwellings, 2021", "Total des logements privés, 2021"),
                    member(
                        7,
                        "Private dwellings occupied by usual residents, 2021",
                        "Logements privés occupés par des résidents habituels, 2021",
                    ),
                ],
            },
        ],
    }
    _mock(httpx_mock, cube)
    result = await leaves.get_leaf_members(98100002, 2)
    assert result.member_ids == [1, 7]
    assert [x.member_id for x in result.flagged_leaves] == [4]


async def test_member_query_filters_leaves_and_points_to_parents(httpx_mock):
    _mock(httpx_mock, 36100434)
    oil = await leaves.get_leaf_members(36100434, 4, member_query="sables bitumineux")
    assert oil.member_ids == [29, 30]  # French names match too; 29 says "à l'exception des"
    mining = await leaves.get_leaf_members(36100434, 4, member_query="mining quarrying")
    assert mining.member_ids == []
    assert any("27 Mining" in n and "under_member_id" in n for n in mining.notes)


async def test_paging_is_stated(httpx_mock):
    _mock(httpx_mock, 18100004)
    page = await leaves.get_leaf_members(18100004, 2, limit=2, offset=1)
    assert page.member_ids == [26, 28]
    assert page.selected_count == 5
    assert page.provenance.limits is not None and "2 of 5" in page.provenance.limits


@pytest.mark.parametrize(
    "kwargs",
    [{"dimension": 9}, {"dimension": 2, "under_member_id": 999}, {"dimension": 2, "limit": 0}],
)
async def test_bad_arguments_raise(httpx_mock, kwargs):
    httpx_mock.add_response(
        url=METADATA_URL,
        method="POST",
        json=[{"status": "SUCCESS", "object": FIXTURE["18100004"]}],
        is_optional=True,
    )
    with pytest.raises(InvalidInput):
        await leaves.get_leaf_members(18100004, **kwargs)


async def test_tool_answers_in_french(httpx_mock):
    _mock(httpx_mock, 36100434)
    fn = getattr(tools.wds_get_leaf_members, "fn", tools.wds_get_leaf_members)
    result = await fn("36-10-0434", 4, under_member_id=27, lang="fr")
    assert result.dimension_name.startswith("Système de classification")
    assert result.leaves[0].member_name == (
        "Extraction de pétrole et de gaz (à l'exception des sables bitumineux)"
    )
    assert result.leaves[0].unit == "Dollars"
    assert result.notes[-1].startswith("Utilisation")
    with pytest.raises(InvalidInput, match="n'a pas de dimension"):
        await fn(36100434, 7, lang="fr")


@pytest.mark.parametrize(
    ("name", "is_total"),
    [
        ("Total, all industries", True),
        ("All-items", True),
        ("All industries", True),
        ("Ensemble des industries", True),
        ("All other miscellaneous food preparations", False),
        ("Toutes autres préparations alimentaires", False),
        ("Women's footwear (excluding athletic)", False),
        ("Butter", False),
    ],
)
def test_total_names(name, is_total):
    member = {"memberNameEn": name, "memberNameFr": name}
    assert leaves._looks_total(member, is_root=False) is is_total

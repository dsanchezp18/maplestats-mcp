"""Tests on rows trimmed from the live IRCC files (2026-09-25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.ircc.monthly import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_HERE = Path(__file__).parent
_PR = (_HERE / "pr_pt_immcat.tsv").read_bytes()
_PR_URL = constants.FILE_PREFIX + "ODP-PR-PT_IMMCAT.csv"
_CATALOGUE = {
    "success": True,
    "result": {
        "count": 2,
        "results": [
            {
                "id": "f7e5498e",
                "title": "Permanent Residents – Monthly IRCC Updates",
                "title_translated": {
                    "en": "Permanent Residents – Monthly IRCC Updates",
                    "fr": "Résidents permanents – Mises à jour mensuelles d’IRCC",
                },
                "resources": [
                    {
                        "format": "CSV",
                        "url": _PR_URL,
                        "name": "[rounded - not for calculations]  Canada - PR by province",
                        "name_translated": {"fr": "[arrondi] Canada - RP par province"},
                    },
                    {"format": "XLSX", "url": constants.FILE_PREFIX + "EN_ODP-PR.xlsx"},
                ],
            },
            {
                "id": "01c85d28",
                "title": "(ARCHIVED) Syrian Refugees – Monthly IRCC Updates",
                "resources": [
                    {"format": "CSV", "url": constants.FILE_PREFIX + "ODP-Syrian.csv", "name": "x"}
                ],
            },
        ],
    },
}


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def catalogue(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.CKAN_SEARCH_URL}?q=title%3A%22Monthly+IRCC+Updates%22&rows=50",
        json=_CATALOGUE,
        is_reusable=True,
    )


@pytest.fixture
def live(httpx_mock, catalogue):
    httpx_mock.add_response(url=_PR_URL, content=_PR, is_reusable=True)


def test_parse_long_table():
    parsed = client.parse_table(_PR)
    assert [d.key for d in parsed.dimensions] == [
        "province_territory",
        "immigration_category_main_category",
    ]
    assert parsed.periods == ["month", "quarter", "year"]
    assert parsed.rows[0].value == 1205 and parsed.rows[0].month == 7
    assert parsed.rows[2].value is None  # '--'
    assert parsed.dimensions[0].fr["Quebec"] == "Québec"


def test_parse_value_column_before_dimensions_and_unpaired_column():
    parsed = client.parse_table((_HERE / "dli.tsv").read_bytes())
    assert [d.key for d in parsed.dimensions] == [
        "dli_province_territory",
        "designated_learning_instituion",
    ]
    assert parsed.dimensions[1].column_fr is None
    assert [r.value for r in parsed.rows] == [10070, None]


def test_parse_comma_file_ignores_copy_columns():
    parsed = client.parse_table((_HERE / "copies.csv").read_bytes())
    assert [d.key for d in parsed.dimensions] == ["age"]
    assert parsed.rows[0].value == 20


def test_lumped_english_label_keeps_rows_and_falls_back_in_french():
    body = (
        b"EN_CENSUS_METROPOLITAN_AREA\tFR_REGION\tTOTAL\n"
        b"Other - Ontario\tWeak metropolitan influenced zone (Ontario)\t5200\n"
        b"Other - Ontario\tModerate metropolitan influenced zone (Ontario)\t4185\n"
    )
    parsed = client.parse_table(body)
    assert [r.value for r in parsed.rows] == [5200, 4185]
    assert parsed.dimensions[0].fr["Other - Ontario"] == "Other - Ontario"


def test_headerless_file_is_reported():
    with pytest.raises(UpstreamError, match="header"):
        client.parse_table((_HERE / "headerless.tsv").read_bytes())


async def test_catalogue_strips_brackets_and_hides_archived(catalogue):
    result = await client.list_tables()
    assert [t.table_id for t in result.tables] == ["ODP-PR-PT_IMMCAT"]
    assert result.tables[0].title == "Canada - PR by province"
    assert result.total_tables == 2
    everything = await client.list_tables(include_archived=True, lang="fr")
    assert everything.tables[-1].archived
    assert everything.tables[0].dataset.startswith("Résidents permanents")


async def test_describe(live):
    result = await client.describe_table("odp-pr-pt_immcat.csv")
    assert result.first_period == "2025-12" and result.last_period == "2026-07"
    assert result.suppressed_cells == 2
    assert result.dimensions[0].values == ["Alberta", "Quebec"]


async def test_query_rows_are_chronological_and_keep_latest(live):
    result = await client.query_table("ODP-PR-PT_IMMCAT", limit=2)
    assert [r.period for r in result.rows] == ["2026-07", "2026-07"]
    assert result.total_matched == 7


async def test_query_filters_in_french_and_totals_by_year(live):
    result = await client.query_table(
        "ODP-PR-PT_IMMCAT",
        {"province_territory": "Québec"},
        period="year",
        group_by=[],
        lang="fr",
    )
    assert result.applied_filters == {"EN_PROVINCE_TERRITORY": "Quebec"}
    by_year = {r.period: (r.value, r.suppressed_cells) for r in result.rows}
    assert by_year == {"2025": (None, 1), "2026": (900, 1)}


async def test_query_group_and_rank(live):
    result = await client.query_table(
        "ODP-PR-PT_IMMCAT",
        year_from=2026,
        period="quarter",
        group_by=["province_territory"],
        sort="value_desc",
    )
    top = result.rows[0]
    assert (top.period, top.dimensions, top.value, top.cells) == (
        "2026-Q3",
        {"province_territory": "Alberta"},
        1615,
        2,
    )


async def test_bad_inputs(live):
    with pytest.raises(NotFound):
        await client.query_table("ODP-NOPE")
    with pytest.raises(InvalidInput, match="unknown dimension"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"region": "x"})
    with pytest.raises(InvalidInput, match="no value"):
        await client.query_table("ODP-PR-PT_IMMCAT", {"province_territory": "Atlantis"})

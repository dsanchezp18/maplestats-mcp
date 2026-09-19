"""Tests for the cmhc module's client.py, shaped around the real HMIP
quirks confirmed live this session (see client.py's module docstring):
the paired label/value+flag CSV shape, cp1252 (not UTF-8/latin-1)
encoding, suppressed-value markers, the ASP.NET YSOD 500-for-unknown-
table behavior, and TableId/GeographyTypeId resolution from the
embedded data-table-model JSON rather than a hardcoded catalogue.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.cmhc import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    cache_module._caches.clear()
    yield


_CATEGORIES_HTML = """
<html><body>
<a data-category-link="true"
   href="/hmip-pimh/en/TableMapChart/TableCategory?geographyType=Country&amp;geographyId=1&amp;categoryLevel1=Primary%20Rental%20Market&amp;categoryLevel2=Vacancy%20Rate%20%28%25%29">Vacancy Rate (%)</a>
<a data-category-link="true"
   href="/hmip-pimh/en/TableMapChart/TableCategory?geographyType=Country&amp;geographyId=1&amp;categoryLevel1=Primary%20Rental%20Market&amp;categoryLevel2=Average%20Rent%20%28%24%29">Average Rent ($)</a>
<a data-category-link="true"
   href="/hmip-pimh/en/TableMapChart/TableCategory?geographyType=Country&amp;geographyId=1&amp;categoryLevel1=Primary%20Rental%20Market&amp;categoryLevel2=Vacancy%20Rate%20%28%25%29">Vacancy Rate (%) again</a>
</body></html>
"""

_TABLE_OPTIONS_HTML = """
<html><body>
<h4>By:</h4>
<ol>
<li><a href="/hmip-pimh/en/TableMapChart/TableMatchingCriteria?GeographyType=Country&amp;GeographyId=1&amp;CategoryLevel1=Primary%20Rental%20Market&amp;CategoryLevel2=Vacancy%20Rate%20%28%25%29&amp;ColumnField=2&amp;RowField=21">Bedroom Type</a></li>
</ol>
<h4>Display Options:</h4>
<ol>
<li><a href="/hmip-pimh/en/TableMapChart/TableMatchingCriteria?GeographyType=Country&amp;GeographyId=1&amp;CategoryLevel1=Primary%20Rental%20Market&amp;CategoryLevel2=Vacancy%20Rate%20%28%25%29&amp;ColumnField=2&amp;RowField=TIMESERIES">Historical Time Periods</a></li>
</ol>
</body></html>
"""

_PROVINCES_HTML = """
<div class="ProvinceContainer">
<div class="option-container">
<a href="#" class="Province option" data-type="Province" data-type-code="2" data-id="10">Newfoundland and Labrador</a>
</div>
<div class="option-container">
<a href="#" class="Province option" data-type="Province" data-type-code="2" data-id="12">Nova Scotia</a>
</div>
</div>
"""

_TABLE_MATCHING_CRITERIA_HTML = (
    "<html><body>"
    '<input type="hidden" id="serialized-model" data-table-model="{'
    "&quot;TableId&quot;:&quot;2.2.1&quot;,&quot;GeographyId&quot;:&quot;1&quot;,"
    "&quot;GeographyTypeId&quot;:1,&quot;TableName&quot;:&quot;Historical Vacancy "
    "Rates by Bedroom Type&quot;,&quot;GeograghyName&quot;:&quot;Canada&quot;"
    '}">'
    "</body></html>"
)


def _csv_bytes(text: str) -> bytes:
    return text.encode("cp1252")


_EXPORT_CSV = _csv_bytes(
    "— Historical Vacancy Rates by Bedroom Type\n"
    "1990 to 2025 Row / Apartment October\n"
    ",Studio,,1 Bedroom,,Total,,\n"
    "1990 October,5.0,a ,3.5,a ,3.4,a ,\n"
    "1991 October,**,,4.3,b ,4.3,a ,\n"
    "\n"
    "Notes\n"
    '"The following letter codes indicate reliability: a - Excellent, b - Very good"\n'
    "Source,CMHC Rental Market Survey\n"
)


async def test_list_categories_dedupes_and_parses(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart?geographyType=Country&geographyId=1",
        text=_CATEGORIES_HTML,
    )
    result = await client.list_categories()
    assert result.total_count == 2
    labels = {(c.category_level_1, c.category_level_2) for c in result.categories}
    assert ("Primary Rental Market", "Vacancy Rate (%)") in labels
    assert ("Primary Rental Market", "Average Rent ($)") in labels
    assert result.provenance.cached is False


async def test_get_table_options_parses_field_links(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableCategory"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
        ),
        text=_TABLE_OPTIONS_HTML,
    )
    result = await client.get_table_options("Primary Rental Market", "Vacancy Rate (%)")
    pairs = {(o.column_field, o.row_field) for o in result.field_options}
    assert pairs == {("2", "21"), ("2", "TIMESERIES")}
    by_row = {o.row_field: o.label for o in result.field_options}
    assert by_row["TIMESERIES"] == "Historical Time Periods"


async def test_list_provinces_parses_id_and_name(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
    )
    result = await client.list_provinces()
    assert {p.id: p.name for p in result.provinces} == {
        "10": "Newfoundland and Labrador",
        "12": "Nova Scotia",
    }
    assert all(p.type_code == "2" for p in result.provinces)


async def test_get_table_data_resolves_table_id_and_parses_csv(httpx_mock):
    """Confirmed live: TableMatchingCriteria resolves TableId/GeographyTypeId
    from an embedded data-table-model JSON blob, then ExportTable returns a
    cp1252-encoded CSV with paired (value, flag) columns and a suppressed
    ("**") marker for at least one real cell."""
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
            "&ColumnField=2&RowField=TIMESERIES"
        ),
        text=_TABLE_MATCHING_CRITERIA_HTML,
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart/ExportTable",
        method="POST",
        content=_EXPORT_CSV,
        headers={"content-type": "text/csv"},
    )
    result = await client.get_table_data(
        "Primary Rental Market", "Vacancy Rate (%)", "2", "TIMESERIES"
    )
    assert result.table_id == "2.2.1"
    assert result.geography_name == "Canada"
    assert result.columns == ["Studio", "1 Bedroom", "Total"]
    assert len(result.rows) == 2
    row_1990 = result.rows[0]
    assert row_1990.period == "1990 October"
    assert row_1990.values["Studio"].value == 5.0
    assert row_1990.values["Studio"].flag == "a"
    # Confirmed live: a suppressed cell holds "**" with an empty flag column.
    row_1991 = result.rows[1]
    assert row_1991.values["Studio"].value is None
    assert row_1991.values["Studio"].flag == "**"
    assert any("Source" in note for note in result.notes)


async def test_get_table_data_maps_ysod_500_to_not_found(httpx_mock):
    """Confirmed live: an unresolvable category/geography returns HTTP 500
    with an ASP.NET YSOD page, not a clean 404 - retried 3x by
    shared/http.py before surfacing, same as any other 500."""
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
                "?GeographyType=Country&GeographyId=1"
                "&CategoryLevel1=Not+A+Real+Category&CategoryLevel2=Nonsense"
                "&ColumnField=2&RowField=TIMESERIES"
            ),
            status_code=500,
            text="<html><head><title>Sequence contains no elements</title></head></html>",
        )
    with pytest.raises(NotFound, match="Sequence contains no elements"):
        await client.get_table_data("Not A Real Category", "Nonsense", "2", "TIMESERIES")


async def test_get_table_data_raises_not_found_when_model_missing(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
            "&ColumnField=2&RowField=TIMESERIES"
        ),
        text="<html><body>no model here</body></html>",
    )
    with pytest.raises(NotFound):
        await client.get_table_data("Primary Rental Market", "Vacancy Rate (%)", "2", "TIMESERIES")


async def test_get_table_data_rejects_empty_arguments():
    with pytest.raises(InvalidInput):
        await client.get_table_data("", "Vacancy Rate (%)", "2", "TIMESERIES")
    with pytest.raises(InvalidInput):
        await client.get_table_data("Primary Rental Market", "  ", "2", "TIMESERIES")


async def test_list_categories_rejects_bad_lang():
    with pytest.raises(InvalidInput):
        await client.list_categories(lang="de")


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.list_provinces()

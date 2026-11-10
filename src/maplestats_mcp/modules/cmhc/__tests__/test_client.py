"""Tests for the cmhc module's client.py, shaped around the real HMIP
quirks confirmed live this session (see client.py's module docstring):
the paired label/value+flag CSV shape, cp1252 (not UTF-8/latin-1)
encoding, suppressed-value markers, the ASP.NET YSOD 500-for-unknown-
table behavior, and TableId/GeographyTypeId resolution from the
embedded data-table-model JSON rather than a hardcoded catalogue.
"""

from __future__ import annotations

import csv
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.cmhc import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.brief import shape
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)


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
    "Rates by Bedroom Type&quot;,&quot;GeograghyName&quot;:&quot;Canada&quot;,"
    "&quot;AvailableFilters&quot;:[{&quot;Item1&quot;:&quot;dwelling_type_desc_en&quot;,"
    "&quot;Item2&quot;:&quot;Dwelling Type&quot;,&quot;Item3&quot;:[&quot;Row&quot;,"
    "&quot;Apartment&quot;]},{&quot;Item1&quot;:&quot;season&quot;,&quot;Item2&quot;:null,"
    "&quot;Item3&quot;:[&quot;April&quot;,&quot;October&quot;]}]"
    '}">'
    "</body></html>"
)

# Confirmed live: a census-style administrative table (Starts and
# Completions Survey) has NO paired quality/flag columns at all - unlike
# the Rms vacancy-rate fixture above. Also exercises the thousands-comma
# separator ("2,222") and the bare "-" nil-value marker.
_TABLE_MATCHING_CRITERIA_HTML_SCSS = (
    "<html><body>"
    '<input type="hidden" id="serialized-model" data-table-model="{'
    "&quot;TableId&quot;:&quot;1.1.1.3&quot;,&quot;GeographyId&quot;:&quot;1&quot;,"
    "&quot;GeographyTypeId&quot;:1,&quot;TableName&quot;:&quot;Starts by Dwelling Type "
    "by Centres&quot;,&quot;GeograghyName&quot;:&quot;Canada&quot;"
    '}">'
    "</body></html>"
)


def _csv_bytes(text: str) -> bytes:
    return text.encode("cp1252")


_EXPORT_CSV_SCSS = _csv_bytes(
    "— Starts by Dwelling Type by Centres\n"
    "August 2026\n"
    ",Single,Row,All,\n"
    'Calgary,715,264,"2,222",\n'
    "Kamloops,3,-,3,\n"
    "\n"
    "Source,CMHC Starts and Completions Survey\n"
)

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
    # Confirmed live: the resolved table model also carries extra filter
    # dimensions (season, dwelling type) beyond column_field/row_field.
    assert {f.key for f in result.available_filters} == {"dwelling_type_desc_en", "season"}
    assert result.applied_filters == {}
    # Every flag the rows carry is explained, and only those.
    flags = {cell.flag for row in result.rows for cell in row.values.values() if cell.flag}
    assert set(result.flag_legend) == flags
    assert result.flag_legend["**"].startswith("Suppressed")
    assert "4 responding entities" in result.flag_legend["**"]


async def test_get_table_data_parses_unflagged_columns_and_special_values(httpx_mock):
    """Confirmed live: a census-style administrative table (Starts and
    Completions Survey, which counts every issued permit rather than
    sampling) has NO paired quality/flag columns at all - unlike a
    statistically-sampled Rental Market Survey table. Also exercises a
    thousands-comma-separated value ("2,222") and CMHC's bare "-" nil-
    value marker (a real, counted zero, not a suppressed value)."""
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=New+Housing+Construction&CategoryLevel2=Starts+%28Actual%29"
            "&ColumnField=1&RowField=25"
        ),
        text=_TABLE_MATCHING_CRITERIA_HTML_SCSS,
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart/ExportTable",
        method="POST",
        content=_EXPORT_CSV_SCSS,
        headers={"content-type": "text/csv"},
    )
    result = await client.get_table_data("New Housing Construction", "Starts (Actual)", "1", "25")
    assert result.columns == ["Single", "Row", "All"]
    calgary = next(r for r in result.rows if r.period == "Calgary")
    assert calgary.values["Single"].value == 715.0
    assert calgary.values["Single"].flag is None
    assert calgary.values["All"].value == 2222.0  # thousands-comma stripped
    kamloops = next(r for r in result.rows if r.period == "Kamloops")
    assert kamloops.values["Row"].value == 0.0  # bare "-" is a real zero
    assert kamloops.values["All"].value == 3.0
    assert result.available_filters == []
    # A census-style table carries no reliability flags, so nothing to explain.
    assert result.flag_legend == {}


_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("fixture", "category_level_1", "category_level_2", "column_field", "row_field", "total"),
    [
        # Recorded 2026-11-09: a sampled survey table, one flag column per value.
        (
            "rms_vacancy_by_province",
            "Primary Rental Market",
            "Vacancy Rate (%)",
            "2",
            "21",
            ("Total", 3.1, "a"),
        ),
        # Recorded 2026-11-09: an administrative count, no flag columns.
        (
            "scss_starts_by_province",
            "New Housing Construction",
            "Starts (Actual)",
            "1",
            "30",
            ("Total", 19984.0, None),
        ),
    ],
)
async def test_get_table_data_labels_the_cross_tab_total_row(
    httpx_mock, fixture, category_level_1, category_level_2, column_field, row_field, total
):
    """HMIP's cross-tab export leaves its last row, the requested
    geography's total, without a label. That row is labelled with the
    geography's name, like every other row is with its province's."""
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            f"&{httpx.QueryParams({'CategoryLevel1': category_level_1})}"
            f"&{httpx.QueryParams({'CategoryLevel2': category_level_2})}"
            f"&ColumnField={column_field}&RowField={row_field}"
        ),
        text=(_FIXTURES / f"{fixture}_matching_criteria.html").read_text(encoding="utf-8"),
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart/ExportTable",
        method="POST",
        content=(_FIXTURES / f"{fixture}_export.csv").read_bytes(),
        headers={"content-type": "text/csv"},
    )
    result = await client.get_table_data(
        category_level_1, category_level_2, column_field, row_field
    )
    periods = [row.period for row in result.rows]
    assert all(periods)
    assert periods[0] == "Newfoundland and Labrador"
    assert periods[-1] == "Canada" == result.geography_name
    column, value, flag = total
    assert result.rows[-1].values[column].value == value
    assert result.rows[-1].values[column].flag == flag


def test_parse_csv_export_keeps_blank_labels_without_a_total_label():
    text = "Title\nSubtitle\n,Total,\nAlberta,4.2,a\n,3.1,a\n"
    _, rows, _ = client._parse_csv_export(text)
    assert [row.period for row in rows] == ["Alberta", ""]
    _, rows, _ = client._parse_csv_export(text, total_label="Canada")
    assert [row.period for row in rows] == ["Alberta", "Canada"]


# Subtitle lines as HMIP exported them, live on 2026-11-09.
@pytest.mark.parametrize(
    ("subtitle", "period", "as_of"),
    [
        ("October 2025 Row / Apartment", "October 2025", datetime(2025, 10, 1, tzinfo=UTC)),
        ("1990 to 2025 Row / Apartment October", "1990 to 2025", None),
        ("September 2026", "September 2026", datetime(2026, 9, 1, tzinfo=UTC)),
        (
            "January 1990 to September 2026",
            "January 1990 to September 2026",
            datetime(2026, 9, 1, tzinfo=UTC),
        ),
        ("2021", "2021", None),
        ("2009 to 2021", "2009 to 2021", None),
        (
            "octobre 2025 En rangée / Appartements",
            "octobre 2025",
            datetime(2025, 10, 1, tzinfo=UTC),
        ),
        ("1990 à 2025 En rangée / Appartements octobre", "1990 à 2025", None),
        ("décembre 2024", "décembre 2024", datetime(2024, 12, 1, tzinfo=UTC)),
        # Not a period: no reference period rather than a wrong one.
        ("Row / Apartment", None, None),
        ("Spring 2025", None, None),
        ("", None, None),
    ],
)
def test_reference_period_reads_the_subtitle_line(subtitle, period, as_of):
    assert client._reference_period(subtitle) == (period, as_of)


def _mock_export(httpx_mock, lang, match_params, matching_html, export_csv):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/{lang}/TableMapChart/TableMatchingCriteria"
            f"?{httpx.QueryParams(match_params)}"
        ),
        text=matching_html,
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/{lang}/TableMapChart/ExportTable",
        method="POST",
        content=(_FIXTURES / export_csv).read_bytes(),
        headers={"content-type": "text/csv"},
    )


def _match_params(category_level_1, category_level_2, column_field, row_field):
    return {
        "GeographyType": "Country",
        "GeographyId": "1",
        "CategoryLevel1": category_level_1,
        "CategoryLevel2": category_level_2,
        "ColumnField": column_field,
        "RowField": row_field,
    }


_RMS_PROVINCES = ("Primary Rental Market", "Vacancy Rate (%)", "2", "21")
_SCSS_PROVINCES = ("New Housing Construction", "Starts (Actual)", "1", "30")
_RMS_SERIES = ("Primary Rental Market", "Vacancy Rate (%)", "2", "TIMESERIES")


@pytest.mark.parametrize(
    ("args", "matching", "export_csv", "period", "as_of"),
    [
        (
            _RMS_PROVINCES,
            "rms_vacancy_by_province_matching_criteria.html",
            "rms_vacancy_by_province_export.csv",
            "October 2025",
            "2025-10-01T00:00:00Z",
        ),
        (
            _SCSS_PROVINCES,
            "scss_starts_by_province_matching_criteria.html",
            "scss_starts_by_province_export.csv",
            "September 2026",
            "2026-09-01T00:00:00Z",
        ),
        # The series' own rows are dated; the result states its span, and no
        # as_of month since the subtitle gives none.
        (_RMS_SERIES, None, "rms_vacancy_timeseries_export.csv", "1990 to 2025", None),
    ],
)
async def test_get_table_data_returns_the_reference_period(
    httpx_mock, args, matching, export_csv, period, as_of
):
    """Recorded exports: the period on the line under the title reaches the
    result, its citation and its provenance."""
    matching_html = (
        (_FIXTURES / matching).read_text(encoding="utf-8")
        if matching
        else _TABLE_MATCHING_CRITERIA_HTML
    )
    _mock_export(httpx_mock, "en", _match_params(*args), matching_html, export_csv)
    result = await client.get_table_data(*args)
    assert result.reference_period == period
    assert result.citation.startswith(
        "Canada Mortgage and Housing Corporation (CMHC), Housing Market Information Portal, "
        f"table {result.table_id}, "
    )
    assert result.citation.endswith(f", Canada, {period}.")
    dumped = result.model_dump(mode="json")
    assert dumped["provenance"]["as_of"] == as_of

    # Brief mode, what a model reads by default, keeps all three.
    brief = shape(dumped, "brief", tool="cmhc_get_table_data")
    assert brief is not None
    assert brief["reference_period"] == period
    assert brief["citation"] == result.citation
    assert brief["provenance"].get("as_of") == as_of


async def test_get_table_data_reference_period_in_french(httpx_mock):
    """A recorded French export: "octobre 2025", and a French citation. The
    matching-criteria page is the English recording; the table model it
    carries is the same in both languages apart from its names."""
    args = ("Marché locatif primaire", "Taux d'inoccupation (%)", "2", "21")
    _mock_export(
        httpx_mock,
        "fr",
        _match_params(*args),
        (_FIXTURES / "rms_vacancy_by_province_matching_criteria.html").read_text(encoding="utf-8"),
        "rms_vacancy_by_province_fr_export.csv",
    )
    result = await client.get_table_data(*args, lang="fr")
    assert result.reference_period == "octobre 2025"
    assert result.citation.startswith("Société canadienne d'hypothèques et de logement (SCHL)")
    assert result.citation.endswith(", Canada, octobre 2025.")
    assert result.provenance.as_of == datetime(2025, 10, 1, tzinfo=UTC)
    # Confirmed by this recording: the French export writes a decimal comma.
    assert result.rows[0].values["Studio"].value == 0.8


def test_citation_says_when_no_period_is_stated():
    citation = client._citation("2.2.1", "Historical Vacancy Rates  ", "Canada", None, "en")
    assert citation.endswith("Historical Vacancy Rates, Canada, reference period not stated.")


async def test_get_table_data_applies_and_validates_filters(httpx_mock):
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
        match_content=(
            b"TableId=2.2.1&GeographyId=1&GeographyTypeId=1&exportType=csv"
            b"&AppliedFilters%5B0%5D.Key=dwelling_type_desc_en"
            b"&AppliedFilters%5B0%5D.Value=Row"
        ),
        content=_EXPORT_CSV,
        headers={"content-type": "text/csv"},
    )
    result = await client.get_table_data(
        "Primary Rental Market",
        "Vacancy Rate (%)",
        "2",
        "TIMESERIES",
        filters={"dwelling_type_desc_en": "Row"},
    )
    assert result.applied_filters == {"dwelling_type_desc_en": "Row"}


async def test_get_table_data_rejects_unknown_filter_key(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
            "&ColumnField=2&RowField=TIMESERIES"
        ),
        text=_TABLE_MATCHING_CRITERIA_HTML,
    )
    with pytest.raises(InvalidInput, match="not available"):
        await client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            "2",
            "TIMESERIES",
            filters={"not_a_real_filter": "x"},
        )


async def test_get_table_data_rejects_invalid_filter_value(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
            "&ColumnField=2&RowField=TIMESERIES"
        ),
        text=_TABLE_MATCHING_CRITERIA_HTML,
    )
    with pytest.raises(InvalidInput, match="not valid"):
        await client.get_table_data(
            "Primary Rental Market",
            "Vacancy Rate (%)",
            "2",
            "TIMESERIES",
            filters={"season": "Winter"},
        )


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


async def test_unknown_province_id_is_refused_before_hmip(httpx_mock):
    # Live 2026-10-03: geography_type Province with id "999" returned the
    # national category list as if it were that province's.
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
    )
    with pytest.raises(InvalidInput, match="Nova Scotia"):
        await client.list_categories(geography_type="Province", geography_id="999")
    with pytest.raises(InvalidInput, match="Canada"):
        await client.list_categories(geography_type="Country", geography_id="2")
    with pytest.raises(InvalidInput, match="not one HMIP knows"):
        await client.get_table_options("a", "b", geography_type="Zone", geography_id="1")


def test_ysod_title_drops_markup():
    body = (
        "<html><head><title>First character of geography id is not a number."
        "<br>Parameter name: 999</title></head></html>"
    )
    assert client._ysod_title(body) == (
        "First character of geography id is not a number. Parameter name: 999"
    )


async def test_list_categories_rejects_bad_lang():
    with pytest.raises(InvalidInput):
        await client.list_categories(lang="de")


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.list_provinces()


async def test_french_errors_and_provenance(httpx_mock):
    with pytest.raises(InvalidInput, match="^Entrée invalide\u00a0: category_level_2 ne doit"):
        await client.get_table_data("Primary Rental Market", "  ", "2", "TIMESERIES", lang="fr")
    with pytest.raises(InvalidInput, match="l'identifiant est '1' \\(Canada\\)"):
        await client.list_categories(geography_type="Country", geography_id="2", lang="fr")
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/fr/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
    )
    provinces = await client.list_provinces(lang="fr")
    assert (provinces.provenance.licence or "").startswith("Conditions d'utilisation de la SCHL")
    assert "appelez reproduce_code" in provinces.provenance.reproduce


async def test_list_categories_without_anchors_raises_and_is_not_cached(httpx_mock):
    # A 200 page with no a[data-category-link] is a changed layout (or an
    # expired session), not "no categories": it must not be cached for 24 h.
    url = f"{constants.BASE_URL}/en/TableMapChart?geographyType=Country&geographyId=1"
    httpx_mock.add_response(url=url, text="<html><body><p>Maintenance</p></body></html>")
    with pytest.raises(UpstreamError, match="no category links"):
        await client.list_categories()
    httpx_mock.add_response(url=url, text=_CATEGORIES_HTML)
    result = await client.list_categories()
    assert result.total_count == 2
    assert result.provenance.cached is False


async def test_list_categories_without_anchors_is_bilingual(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/fr/TableMapChart?geographyType=Country&geographyId=1",
        text="<html><body></body></html>",
    )
    with pytest.raises(UpstreamError, match="aucun lien de catégorie"):
        await client.list_categories(lang="fr")


async def test_list_provinces_without_anchors_raises_and_is_not_cached(httpx_mock):
    url = f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1"
    httpx_mock.add_response(url=url, text="<div class='ProvinceContainer'></div>")
    with pytest.raises(UpstreamError, match="no province links"):
        await client.list_provinces()
    httpx_mock.add_response(url=url, text=_PROVINCES_HTML)
    result = await client.list_provinces()
    assert [p.id for p in result.provinces] == ["10", "12"]
    assert result.provenance.cached is False


async def test_list_provinces_without_anchors_is_bilingual(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/fr/Navigation/ProvincesByCountry?countryId=1",
        text="<div></div>",
    )
    with pytest.raises(UpstreamError, match="aucun lien de province"):
        await client.list_provinces(lang="fr")


def test_parse_value_cell_french_comma_is_the_decimal_mark():
    assert client._parse_value_cell("1,5", "", "fr").value == 1.5
    assert client._parse_value_cell("1 013,5", "", "fr").value == 1013.5
    # No-break and narrow no-break spaces group thousands in French typography.
    assert client._parse_value_cell("1\u00a0013,5", "", "fr").value == 1013.5
    assert client._parse_value_cell("1\u202f013", "", "fr").value == 1013.0
    assert client._parse_value_cell("3,4", "a", "fr").flag == "a"


def test_parse_value_cell_english_comma_is_a_thousands_separator():
    assert client._parse_value_cell("1,234", "").value == 1234.0
    assert client._parse_value_cell("1,234", "", "en").value == 1234.0
    assert client._parse_value_cell("2,222.5", "", "en").value == 2222.5


def test_parse_value_cell_french_keeps_special_tokens():
    assert client._parse_value_cell("**", "", "fr").value is None
    assert client._parse_value_cell("-", "", "fr").value == 0.0
    cell = client._parse_value_cell("abc", "", "fr")
    assert cell.value is None
    assert cell.flag == "abc"


async def test_get_table_data_french_export_reads_comma_as_decimal(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/fr/TableMapChart/TableMatchingCriteria"
            "?GeographyType=Country&GeographyId=1&CategoryLevel1=Marche+locatif+primaire"
            "&CategoryLevel2=Taux+d%27inoccupation&ColumnField=2&RowField=TIMESERIES"
        ),
        text=_TABLE_MATCHING_CRITERIA_HTML_SCSS,
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{constants.BASE_URL}/fr/TableMapChart/ExportTable",
        content=_csv_bytes(
            'Mises en chantier\nAout 2026\n,Unifamilial,Total,\nCalgary,"1,5","1\u00a0013,5",\n'
        ),
    )
    result = await client.get_table_data(
        "Marche locatif primaire",
        "Taux d'inoccupation",
        "2",
        "TIMESERIES",
        lang="fr",
    )
    values = {name: cell.value for name, cell in result.rows[0].values.items()}
    assert values == {"Unifamilial": 1.5, "Total": 1013.5}


def test_flag_legend_follows_lang():
    rows = [
        client.TableDataRow(
            period="2025",
            values={
                "Total": client.TableCell(value=2.1, flag="d"),
                "x": client.TableCell(value=None, flag="++"),
            },
        )
    ]
    assert set(client._flag_legend(rows, "en")) == {"d", "++"}
    assert "use with caution" in client._flag_legend(rows, "en")["d"]
    assert "prudence" in client._flag_legend(rows, "fr")["d"]


# Live 2026-11-03 (/Navigation/MetsByProvince/35): one anchor per metropolitan major area,
# ids kept as text because some start with zero.
_METROS_NL_HTML = """
<div class="option-container">
<a href="#" class="MetropolitanMajorArea option" data-type="MetropolitanMajorArea" data-id="0005" data-type-code="3">St. John's</a>
</div>
"""
_METROS_NS_HTML = """
<div class="option-container">
<a href="#" class="MetropolitanMajorArea option" data-type="MetropolitanMajorArea" data-id="0580" data-type-code="3">Halifax</a>
<a href="#" class="MetropolitanMajorArea option" data-type="MetropolitanMajorArea" data-id="0590" data-type-code="3">Kentville - Halifax Road</a>
<a href="#" class="MetropolitanMajorArea option" data-type="MetropolitanMajorArea" data-id="0595" data-type-code="3">New Glasgow - Halifax Road</a>
</div>
"""


def _mock_geographies(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
        is_reusable=True,
        is_optional=True,
    )
    for province, body in (("10", _METROS_NL_HTML), ("12", _METROS_NS_HTML)):
        httpx_mock.add_response(
            url=f"{constants.BASE_URL}/en/Navigation/MetsByProvince/{province}",
            text=body,
            is_reusable=True,
            is_optional=True,
        )


async def test_list_metropolitan_areas_reads_every_province(httpx_mock):
    _mock_geographies(httpx_mock)
    result = await client.list_metropolitan_areas()
    assert result.geography_type == "MetropolitanMajorArea"
    assert [(a.id, a.name, a.province_name) for a in result.areas] == [
        ("0005", "St. John's", "Newfoundland and Labrador"),
        ("0580", "Halifax", "Nova Scotia"),
        ("0590", "Kentville - Halifax Road", "Nova Scotia"),
        ("0595", "New Glasgow - Halifax Road", "Nova Scotia"),
    ]
    assert result.total_count == 4


async def test_list_metropolitan_areas_filters_by_name_and_province(httpx_mock):
    _mock_geographies(httpx_mock)
    by_name = await client.list_metropolitan_areas(name="halifax")
    assert [a.id for a in by_name.areas] == ["0580", "0590", "0595"]
    by_province = await client.list_metropolitan_areas(province_id="Nova Scotia")
    assert {a.province_id for a in by_province.areas} == {"12"}
    with pytest.raises(InvalidInput, match="Newfoundland"):
        await client.list_metropolitan_areas(province_id="99")


async def test_cma_alias_and_name_resolve_to_hmip_type_and_id(httpx_mock):
    """Live 2026-11-03: HMIP answers geography_type "CMA" with HTTP 500 (an unknown name
    becomes enum value 0); "MetropolitanMajorArea" with Toronto's 2270 resolves."""
    _mock_geographies(httpx_mock)
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart"
            "?geographyType=MetropolitanMajorArea&geographyId=0580"
        ),
        text=_CATEGORIES_HTML,
    )
    result = await client.list_categories(geography_type="CMA", geography_id="Halifax")
    assert (result.geography_type, result.geography_id) == ("MetropolitanMajorArea", "0580")


async def test_unknown_or_ambiguous_metro_area_is_refused(httpx_mock):
    _mock_geographies(httpx_mock)
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart?geographyType=MetropolitanMajorArea&geographyId=0580",
        text=_CATEGORIES_HTML,
    )
    # An exact name wins over the two names that contain it.
    halifax = await client.list_categories(geography_type="metro", geography_id="Halifax")
    assert halifax.geography_id == "0580"
    with pytest.raises(InvalidInput, match="No metropolitan area with id"):
        await client.list_categories(geography_type="cma", geography_id="9999")
    with pytest.raises(InvalidInput, match="No metropolitan area named"):
        await client.list_categories(geography_type="RMR", geography_id="Atlantis")
    # "Halifax Road" is part of two names and the exact name of none.
    with pytest.raises(InvalidInput, match="more than one.*0590"):
        await client.list_categories(geography_type="metro", geography_id="Halifax Road")


async def test_province_name_is_accepted_as_id(httpx_mock):
    _mock_geographies(httpx_mock)
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart?geographyType=Province&geographyId=12",
        text=_CATEGORIES_HTML,
    )
    result = await client.list_categories(geography_type="province", geography_id="nova scotia")
    assert result.geography_id == "12"


async def test_field_labels_are_turned_into_codes(httpx_mock):
    """The chat demo's model passed column_field="Bedroom Type" (live 2026-11-03); HMIP
    needs the code, "2"."""
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}/en/TableMapChart/TableCategory"
            "?GeographyType=Country&GeographyId=1"
            "&CategoryLevel1=Primary+Rental+Market&CategoryLevel2=Vacancy+Rate+%28%25%29"
        ),
        text=_TABLE_OPTIONS_HTML,
        is_reusable=True,
    )
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
        "Primary Rental Market", "Vacancy Rate (%)", "bedroom type", "Historical Time Periods"
    )
    assert (result.column_field, result.row_field) == ("2", "TIMESERIES")
    with pytest.raises(InvalidInput, match=r"column_field accepts: Bedroom Type \(2\)"):
        await client.get_table_data(
            "Primary Rental Market", "Vacancy Rate (%)", "Bedrooms", "TIMESERIES"
        )


async def test_metro_list_error_page_is_raised_and_not_cached(httpx_mock):
    """An HTTP 200 page with no list container (maintenance) must not be cached for a day:
    valid ids would be refused until it expired."""
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
        is_reusable=True,
    )
    url_nl = f"{constants.BASE_URL}/en/Navigation/MetsByProvince/10"
    httpx_mock.add_response(url=url_nl, text="<html><body>Down for maintenance</body></html>")
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/MetsByProvince/12",
        text=_METROS_NS_HTML,
        is_reusable=True,
    )
    with pytest.raises(UpstreamError, match="Newfoundland"):
        await client.list_metropolitan_areas()
    httpx_mock.add_response(url=url_nl, text=_METROS_NL_HTML)
    result = await client.list_metropolitan_areas()
    assert "0005" in {a.id for a in result.areas}


async def test_empty_metro_list_container_is_a_valid_answer(httpx_mock):
    # Live 2026-11-03: Nunavut answers the empty container.
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/ProvincesByCountry?countryId=1",
        text=_PROVINCES_HTML,
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/Navigation/MetsByProvince/10",
        text='<div class="MetropolitanMajorAreaContainer">\n</div>',
    )
    result = await client.list_metropolitan_areas(province_id="10")
    assert result.areas == []


# Core Housing Need's field codes are words, not numbers: recorded 2026-11-09.
_CHN = ("Core Housing Need", "Household Type")


def _mock_chn_options(httpx_mock):
    params = {
        "GeographyType": "Country",
        "GeographyId": "1",
        "CategoryLevel1": _CHN[0],
        "CategoryLevel2": _CHN[1],
    }
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}/en/TableMapChart/TableCategory?{httpx.QueryParams(params)}",
        text=(_FIXTURES / "chn_household_type_table_category.html").read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize(
    ("column_field", "row_field"),
    [
        # The codes exactly as cmhc_get_table_options lists them.
        ("HouseholdType", "Province"),
        # Another case: sent to HMIP in its own spelling.
        ("householdtype", "PROVINCE"),
        # The option's label still works, as for numeric tables.
        ("% of Households in Core Housing Need", "Province"),
    ],
)
async def test_get_table_data_accepts_word_field_codes(httpx_mock, column_field, row_field):
    """Until 2026-11-09 a code that was not a number or TIMESERIES was looked up
    only among the labels, so the codes cmhc_get_table_options returned for this
    table were refused as "not a field code or label of this table"."""
    _mock_chn_options(httpx_mock)
    _mock_export(
        httpx_mock,
        "en",
        _match_params(*_CHN, "HouseholdType", "Province"),
        (_FIXTURES / "chn_household_type_matching_criteria.html").read_text(encoding="utf-8"),
        "chn_household_type_export.csv",
    )
    options = await client.get_table_options(*_CHN)
    assert ("HouseholdType", "Province") in {
        (o.column_field, o.row_field) for o in options.field_options
    }
    result = await client.get_table_data(*_CHN, column_field, row_field)
    assert (result.column_field, result.row_field) == ("HouseholdType", "Province")
    assert result.table_id == "7.42.1"
    assert result.reference_period == "2021"
    assert result.rows[0].period == "Newfoundland and Labrador"
    assert result.rows[-1].period == "Canada"


async def test_get_table_data_still_rejects_an_unknown_word_field(httpx_mock):
    _mock_chn_options(httpx_mock)
    with pytest.raises(InvalidInput, match=r"'RENTQUARTILE' is not a column_field code or label.*HouseholdType"):
        await client.get_table_data(*_CHN, "RENTQUARTILE", "Province")


# ---- Edmonton (0340), recorded live 2026-11-09 ------------------------------------
# TableCategory pages (the option lists only) and TableMatchingCriteria models
# (the period list trimmed); the exports byte for byte, the monthly starts from
# January 2024 on.

_TABLE_CATEGORY = re.compile(r".*/en/TableMapChart/TableCategory\?.*")
_MATCHING = re.compile(r".*/en/TableMapChart/TableMatchingCriteria\?.*")
_EXPORT = f"{constants.BASE_URL}/en/TableMapChart/ExportTable"


@pytest.fixture
def _edmonton(monkeypatch):
    async def resolve(geography_type: str, geography_id: str, lang: str) -> tuple[str, str]:
        return "MetropolitanMajorArea", "0340"

    monkeypatch.setattr(client, "_resolve_geography", resolve)


def _fixture_text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _mock_table(httpx_mock, matching: str, export: str, category_page: str | None = None):
    if category_page:
        httpx_mock.add_response(url=_TABLE_CATEGORY, text=_fixture_text(category_page))
    httpx_mock.add_response(url=_MATCHING, text=_fixture_text(matching))
    httpx_mock.add_response(
        url=_EXPORT,
        method="POST",
        content=(_FIXTURES / export).read_bytes(),
        headers={"content-type": "text/csv"},
    )


async def test_table_options_say_which_axis_each_label_names(httpx_mock, _edmonton):
    httpx_mock.add_response(
        url=_TABLE_CATEGORY, text=_fixture_text("edmonton_average_rent_table_category.html")
    )
    result = await client.get_table_options(
        "Primary Rental Market", "Average Rent ($)", geography_type="CMA", geography_id="0340"
    )
    by_label = {o.label: (o.breakdown, o.column_field, o.row_field) for o in result.field_options}
    assert by_label["Bedroom Type"] == ("column", "2", "25")
    assert by_label["Year of Construction"] == ("column", "28", "25")
    assert by_label["Historical Time Periods"] == ("row", "2", "TIMESERIES")
    # The default table is in both lists: its row label is kept too.
    assert by_label["Survey Zones"] == ("row", "2", "25")


async def test_rent_change_accepts_the_column_label_average_rent_takes(httpx_mock, _edmonton):
    """% Change of Average Rent has no "By:" list (its column is always Bedroom Type), so
    "Bedroom Type" was refused although Average Rent ($) accepts it (live 2026-11-09)."""
    _mock_table(
        httpx_mock,
        "edmonton_rent_change_timeseries_matching_criteria.html",
        "rms_vacancy_timeseries_export.csv",
        category_page="edmonton_rent_change_table_category.html",
    )
    result = await client.get_table_data(
        "Primary Rental Market",
        "% Change of Average Rent",
        "Bedroom Type",
        "Historical Time Periods",
        geography_type="CMA",
        geography_id="0340",
    )
    assert (result.column_field, result.row_field) == ("2", "TIMESERIES")
    request = httpx_mock.get_requests(url=_MATCHING)[0]
    assert request.url.params["ColumnField"] == "2"


async def test_rent_change_refuses_a_column_label_its_title_does_not_name(httpx_mock, _edmonton):
    httpx_mock.add_response(
        url=_TABLE_CATEGORY,
        text=_fixture_text("edmonton_rent_change_table_category.html"),
        is_reusable=True,
    )
    _mock_table(
        httpx_mock,
        "edmonton_rent_change_timeseries_matching_criteria.html",
        "rms_vacancy_timeseries_export.csv",
    )
    with pytest.raises(InvalidInput, match="Year of Construction.*column_field='2'"):
        await client.get_table_data(
            "Primary Rental Market",
            "% Change of Average Rent",
            "Year of Construction",
            "TIMESERIES",
            geography_type="CMA",
            geography_id="0340",
        )
    with pytest.raises(InvalidInput) as caught:
        await client.get_table_data(
            "Primary Rental Market",
            "% Change of Average Rent",
            "2",
            "Bedrooms",
            geography_type="CMA",
            geography_id="0340",
        )
    message = str(caught.value)
    assert "row_field accepts: Survey Zones (25), Census Subdivisions (22)" in message
    assert "Historical Time Periods (TIMESERIES)" in message
    assert "one column breakdown only, code 2" in message


async def test_default_dwelling_type_is_stated(httpx_mock, _edmonton):
    """Without a filter, Edmonton's 2025 average rent is $1,493: row and apartment
    combined, CMHC's default, not the $1,464 of apartments only."""
    _mock_table(
        httpx_mock,
        "edmonton_average_rent_by_zone_matching_criteria.html",
        "edmonton_average_rent_by_zone_export.csv",
    )
    result = await client.get_table_data(
        "Primary Rental Market",
        "Average Rent ($)",
        "2",
        "25",
        geography_type="CMA",
        geography_id="0340",
    )
    assert result.rows[-1].period == "Edmonton"
    assert result.rows[-1].values["Total"].value == 1493.0
    assert result.default_filters == {"dwelling_type_desc_en": "Row / Apartment"}
    assert result.applied_filters == {"dwelling_type_desc_en": "Row / Apartment"}
    note = result.filter_notes[0]
    assert note.startswith("Dwelling Type (dwelling_type_desc_en): Row / Apartment (CMHC's default")
    assert "Other values: Row, Apartment" in note


async def test_starts_annual_totals_match_cmhcs_own_annual_export(httpx_mock, _edmonton):
    _mock_table(
        httpx_mock,
        "edmonton_starts_timeseries_matching_criteria.html",
        "edmonton_starts_timeseries_export.csv",
    )
    result = await client.get_table_data(
        "New Housing Construction",
        "Starts (Actual)",
        "1",
        "TIMESERIES",
        aggregate="annual",
        geography_type="CMA",
        geography_id="0340",
    )
    assert [row.period for row in result.rows] == ["2024", "2025"]
    # HMIP's own Frequency=Annual export of the same table, recorded the same day.
    annual = (_FIXTURES / "edmonton_starts_annual_export.csv").read_bytes().decode("cp1252")
    published = {
        row[0]: row[1:6]
        for row in csv.reader(annual.splitlines()[3:])
        if row and row[0] in ("2024", "2025")
    }
    for row in result.rows:
        expected = [float(v.replace(",", "")) for v in published[row.period]]
        assert [cell.value for cell in row.values.values()] == expected
    assert result.aggregate == "annual"
    assert result.aggregation_note is not None
    assert "summed by MapleStats" in result.aggregation_note
    assert "incomplete: 2026" in result.aggregation_note
    assert result.provenance.coverage == result.aggregation_note
    assert result.default_filters == {"dimension-18": "All"}


async def test_starts_year_to_date_compares_the_same_months(httpx_mock, _edmonton):
    _mock_table(
        httpx_mock,
        "edmonton_starts_timeseries_matching_criteria.html",
        "edmonton_starts_timeseries_export.csv",
    )
    result = await client.get_table_data(
        "New Housing Construction",
        "Starts (Actual)",
        "1",
        "TIMESERIES",
        aggregate="ytd",
        geography_type="CMA",
        geography_id="0340",
    )
    assert [row.period for row in result.rows] == [
        "January to September 2024",
        "January to September 2025",
        "January to September 2026",
    ]
    assert result.rows[-1].values["All"].value == 14202.0
    assert result.rows[-2].values["All"].value == 16484.0


@pytest.mark.parametrize(
    ("level_2", "row_field"),
    [
        ("Starts (SAAR)", "TIMESERIES"),
        ("Under Construction Inventory", "TIMESERIES"),
        ("Average Rent ($)", "TIMESERIES"),
        ("Starts (Actual)", "27"),
    ],
)
async def test_stocks_rates_and_cross_tabs_are_never_summed(level_2, row_field):
    level_1 = "Primary Rental Market" if "Rent" in level_2 else "New Housing Construction"
    with pytest.raises(InvalidInput, match="aggregate"):
        await client.get_table_data(level_1, level_2, "1", row_field, aggregate="annual")


def test_french_monthly_periods_are_read():
    assert client._monthly_period("janv. 1990") == (1990, 1)
    assert client._monthly_period("févr. 2026") == (2026, 2)
    assert client._monthly_period("août 2025") == (2025, 8)
    assert client._monthly_period("déc. 2025") == (2025, 12)
    assert client._monthly_period("Sep 2026") == (2026, 9)
    assert client._monthly_period("2025 October") is None

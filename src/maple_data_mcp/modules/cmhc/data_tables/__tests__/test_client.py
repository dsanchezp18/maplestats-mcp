"""Tests for cmhc.data_tables' client.py, shaped around the real
www.cmhc-schl.gc.ca "Data Tables" quirks confirmed live this session
(see client.py's module docstring): the default download link already
present in a static hidden input, no `selected` option on the edition/
geography <select>s (first option is the default), and the
GetFileDetails resolver API's exact request/response shape.
"""

from __future__ import annotations

import httpx
import pytest

from maple_data_mcp.modules.cmhc.data_tables import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


@pytest.fixture(autouse=True)
def _reset_shared_cache():
    cache_module._caches.clear()
    yield


_LISTING_HTML = """
<html><body>
<ul>
<li><a href="/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/urban-rental-market-survey-data-vacancy-rates">Vacancy  Rates</a></li>
<li><a href="/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/urban-rental-market-survey-data-vacancy-rates">Vacancy  Rates (again)</a></li>
<li><a href="/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/average-apartment-rents-vacant-occupied">Average Apartment Rents (Vacant &amp; Occupied)</a></li>
<li><a href="/professionals/housing-markets-data-and-research/housing-data/data-tables/household-characteristics/households-type-tenure">Households by Type and Tenure</a></li>
</ul>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
<h1>Urban Rental Market Survey Data: Vacancy Rates</h1>
<div class="pdf-landing">
<p>Vacancy rates for rental townhomes and apartments in urban centres with at least 10,000 people.</p>
</div>
<dl>
<dt>Document Type:</dt><dd id="DocumentTag">Excel</dd>
<dt>Date Published:</dt><dd id="DatePublishedTag">April 17, 2024</dd>
</dl>
<input type="hidden" id="DataSource" name="DataSource" value="/sitecore/content/CMHC/Sites/Main/Home/professionals/housing-markets-data-and-research/housing-data/data-tables/rental-market/urban-rental-market-survey-data-vacancy-rates" />
<input type="hidden" id="document-url" name="document-url" value="https://assets.cmhc-schl.gc.ca/sites/cmhc/.../urban-rental-market-survey-data-vacancy-rates-2023-en.xlsx?rev=3ae15c68" />
<select id="pdf_geo" name="pdf_geo">
<option value="{9EE6E91C-4719-412C-909E-A4B27F3FB16E}">Canada</option>
</select>
<select id="pdf_edition" name="pdf_edition">
<option value="{43CC6A09-EF7F-40D4-9CBB-3C3B1C6FBB41}">October 2023</option>
<option value="{C624D5A4-62BC-4724-BBC7-D86E975CDEA2}">October 2022</option>
</select>
</body></html>
"""

_GET_FILE_DETAILS_JSON = {
    "FileName": "",
    "Author": "CMHC",
    "DatePublished": "March 2, 2023",
    "IdNumber": "",
    "Thumbnail": "https://assets.cmhc-schl.gc.ca/sites/cmhc/shared/images/default_excel_doc.png",
    "ProductType": None,
    "DocumentUrl": (
        "https://assets.cmhc-schl.gc.ca/sites/cmhc/.../urban-rental-market-survey-data-"
        "vacancy-rates-2022-en.xlsx?rev=c42a7e1c"
    ),
}


async def test_list_tables_dedupes_and_filters_by_category(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/rental-market",
        text=_LISTING_HTML,
    )
    result = await client.list_tables("rental-market")
    assert result.total_count == 2
    slugs = {t.slug for t in result.tables}
    assert slugs == {
        "urban-rental-market-survey-data-vacancy-rates",
        "average-apartment-rents-vacant-occupied",
    }


async def test_list_tables_rejects_unknown_category():
    with pytest.raises(InvalidInput):
        await client.list_tables("not-a-real-category")


async def test_get_table_parses_detail_page(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/rental-market/"
            "urban-rental-market-survey-data-vacancy-rates"
        ),
        text=_DETAIL_HTML,
    )
    result = await client.get_table(
        "rental-market", "urban-rental-market-survey-data-vacancy-rates"
    )
    assert result.title == "Urban Rental Market Survey Data: Vacancy Rates"
    assert "Vacancy rates for rental" in result.description
    assert result.data_source.endswith("urban-rental-market-survey-data-vacancy-rates")
    assert result.document_type == "Excel"
    assert result.date_published == "April 17, 2024"
    assert [g.name for g in result.geographies] == ["Canada"]
    assert [e.label for e in result.editions] == ["October 2023", "October 2022"]
    # Confirmed live: the default download link is already in the static HTML.
    assert result.default_download_url is not None
    assert result.default_download_url.endswith("-2023-en.xlsx?rev=3ae15c68")


async def test_get_download_url_resolves_default_edition(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/rental-market/"
            "urban-rental-market-survey-data-vacancy-rates"
        ),
        text=_DETAIL_HTML,
    )
    httpx_mock.add_response(
        url=(
            f"{constants.GET_FILE_DETAILS_URL}?cityId=%7B9EE6E91C-4719-412C-909E-A4B27F3FB16E%7D"
            "&edition=%7B43CC6A09-EF7F-40D4-9CBB-3C3B1C6FBB41%7D"
            "&dataSource=%2Fsitecore%2Fcontent%2FCMHC%2FSites%2FMain%2FHome%2Fprofessionals"
            "%2Fhousing-markets-data-and-research%2Fhousing-data%2Fdata-tables%2Frental-market"
            "%2Furban-rental-market-survey-data-vacancy-rates"
            "&contextLanguage=en"
        ),
        json=_GET_FILE_DETAILS_JSON,
    )
    result = await client.get_download_url(
        "rental-market", "urban-rental-market-survey-data-vacancy-rates"
    )
    assert result.geography_id == "{9EE6E91C-4719-412C-909E-A4B27F3FB16E}"
    assert result.edition_id == "{43CC6A09-EF7F-40D4-9CBB-3C3B1C6FBB41}"
    assert result.document_url.endswith("-2022-en.xlsx?rev=c42a7e1c")
    assert result.author == "CMHC"


async def test_get_download_url_rejects_unknown_edition_id(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/rental-market/"
            "urban-rental-market-survey-data-vacancy-rates"
        ),
        text=_DETAIL_HTML,
    )
    with pytest.raises(InvalidInput, match="edition_id"):
        await client.get_download_url(
            "rental-market",
            "urban-rental-market-survey-data-vacancy-rates",
            edition_id="{NOT-A-REAL-EDITION}",
        )


async def test_get_download_url_raises_not_found_on_empty_response(httpx_mock):
    """Confirmed live: GetFileDetails returns a bare JSON empty string
    ("") rather than an object when it has nothing to resolve."""
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}{constants.DATA_TABLES_PATH}/rental-market/"
            "urban-rental-market-survey-data-vacancy-rates"
        ),
        text=_DETAIL_HTML,
    )
    httpx_mock.add_response(
        url=(
            f"{constants.GET_FILE_DETAILS_URL}?cityId=%7B9EE6E91C-4719-412C-909E-A4B27F3FB16E%7D"
            "&edition=%7BC624D5A4-62BC-4724-BBC7-D86E975CDEA2%7D"
            "&dataSource=%2Fsitecore%2Fcontent%2FCMHC%2FSites%2FMain%2FHome%2Fprofessionals"
            "%2Fhousing-markets-data-and-research%2Fhousing-data%2Fdata-tables%2Frental-market"
            "%2Furban-rental-market-survey-data-vacancy-rates"
            "&contextLanguage=en"
        ),
        json="",
    )
    with pytest.raises(NotFound):
        await client.get_download_url(
            "rental-market",
            "urban-rental-market-survey-data-vacancy-rates",
            edition_id="{C624D5A4-62BC-4724-BBC7-D86E975CDEA2}",
        )


async def test_get_table_rejects_empty_slug():
    with pytest.raises(InvalidInput):
        await client.get_table("rental-market", "  ")


async def test_timeout_raises_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(UpstreamUnavailable):
        await client.list_tables("household-characteristics")

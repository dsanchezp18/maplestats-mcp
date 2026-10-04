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

from maplestats_mcp.modules.cmhc.data_tables import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable


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
    # Doubled spaces in upstream titles are collapsed.
    assert "Vacancy Rates" in {t.title for t in result.tables}
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
    assert result.data_source is not None
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
    # FileName is empty upstream; it comes from the URL instead.
    assert result.file_name == "urban-rental-market-survey-data-vacancy-rates-2022-en.xlsx"


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


# The single-file report template, trimmed from the live page
# household-characteristics/home-equity-net-worth-tenure-canada-provinces
# (2026-10-03): no #DataSource, no selects, a hidden #document-id.
_REPORT_PATH = (
    f"{constants.DATA_TABLES_PATH}/household-characteristics/"
    "home-equity-net-worth-tenure-canada-provinces"
)
_REPORT_HTML = """
<html><head>
<link rel='alternate' hreflang='en' href='https://www.cmhc-schl.gc.ca/professionals/x' />
<link rel='alternate' hreflang='fr' href='https://www.cmhc-schl.gc.ca/professionnels/avoir-foncier' />
</head><body>
<h1 id="publicationname" class="font-bold">Home Equity and Net Worth by Tenure: Canada and  Provinces</h1>
<input id="document-id" name="document-id" type="hidden" value="2850a1fa-f31c-4d27-a6fd-75de56e2cecb" />
<div class="pdf-landing"><div>
<p>Home equity and net worth data for all homeowners, renters and for all households.</p>
<dl><dt>Author:</dt><dd>CMHC</dd><dt>Document Type:</dt><dd>Excel</dd>
<dt>Date Published:</dt><dd>March 31, 2018</dd></dl>
<div class="button-panel"><a href="#" id="report-download"
 onclick="dl_Downloads('March 31, 2018', this);">Download</a></div>
</div></div>
</body></html>
"""
# The French page has its own document id (live 2026-10-03): the English
# id resolves to the English file even with contextLanguage=fr.
_REPORT_HTML_FR = """
<html><body>
<h1>Avoir foncier et valeur nette selon le mode d'occupation : Canada et provinces</h1>
<input id="document-id" type="hidden" value="7d33243c-8bbc-4231-8e0e-7e9fe56f9a89" />
<div class="pdf-landing"><div><p>Données sur l'avoir foncier.</p>
<dl><dt>Auteur :</dt><dd>SCHL</dd><dt>Type de document :</dt><dd>Excel</dd>
<dt>Date de publication :</dt><dd>31 mars 2018</dd></dl></div></div>
</body></html>
"""
_REPORT_FILE = (
    "https://assets.cmhc-schl.gc.ca/sf/project/cmhc/pubsandreports/excel/"
    "table_23_homeequity_net_worth_canada_provinces_en_w.xls?rev=840c74ea"
)
_REPORT_FILE_FR = (
    "https://assets.cmhc-schl.gc.ca/sf/project/cmhc/pubsandreports/excel/"
    "table_23_homeequity_net_worth_canada_provinces_fr_w.xls?rev=fd1a03f5"
)


async def test_single_file_report_page_resolves_its_download(httpx_mock):
    # 52 of the 72 listed tables use this template and used to fail with
    # "page had no #DataSource value".
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_REPORT_PATH}", text=_REPORT_HTML)
    httpx_mock.add_response(
        url=(
            f"{constants.GET_REPORT_FILE_URL}?documentId=2850a1fa-f31c-4d27-a6fd-75de56e2cecb"
            "&contextLanguage=en"
        ),
        json=_REPORT_FILE,
    )
    table = await client.get_table(
        "household-characteristics", "home-equity-net-worth-tenure-canada-provinces"
    )
    assert table.title == "Home Equity and Net Worth by Tenure: Canada and Provinces"
    assert table.data_source is None
    assert table.document_id == "2850a1fa-f31c-4d27-a6fd-75de56e2cecb"
    assert (table.author, table.document_type, table.date_published) == (
        "CMHC",
        "Excel",
        "March 31, 2018",
    )
    assert table.default_download_url == _REPORT_FILE
    link = await client.get_download_url(
        "household-characteristics", "home-equity-net-worth-tenure-canada-provinces"
    )
    assert link.document_url == _REPORT_FILE
    assert link.file_name == "table_23_homeequity_net_worth_canada_provinces_en_w.xls"
    assert link.geography_id is None and link.edition_id is None
    with pytest.raises(InvalidInput, match="single file"):
        await client.get_download_url(
            "household-characteristics",
            "home-equity-net-worth-tenure-canada-provinces",
            edition_id="{X}",
        )


async def test_french_table_reads_the_french_page(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_REPORT_PATH}", text=_REPORT_HTML)
    httpx_mock.add_response(
        url="https://www.cmhc-schl.gc.ca/professionnels/avoir-foncier", text=_REPORT_HTML_FR
    )
    httpx_mock.add_response(
        url=(
            f"{constants.GET_REPORT_FILE_URL}?documentId=7d33243c-8bbc-4231-8e0e-7e9fe56f9a89"
            "&contextLanguage=fr"
        ),
        json=_REPORT_FILE_FR,
    )
    table = await client.get_table(
        "household-characteristics", "home-equity-net-worth-tenure-canada-provinces", lang="fr"
    )
    assert table.title.startswith("Avoir foncier")
    assert (table.author, table.date_published) == ("SCHL", "31 mars 2018")
    assert table.french_slug == "avoir-foncier"
    assert table.default_download_url == _REPORT_FILE_FR
    link = await client.get_download_url(
        "household-characteristics", "home-equity-net-worth-tenure-canada-provinces", lang="fr"
    )
    assert link.file_name == "table_23_homeequity_net_worth_canada_provinces_fr_w.xls"


# Pairing, shaped on the live sitemap (2026-10-03): a byte-order mark, and
# /en and /fr prefixes that the site's own links leave out.
_FR_BASE = f"{constants.FR_DATA_TABLES_PATH}/caracteristiques-des-menages"
_HC_BASE = f"{constants.DATA_TABLES_PATH}/household-characteristics"
_BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
_SITEMAP = f"""{_BOM}<?xml version="1.0" encoding="utf-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>{constants.BASE_URL}{_HC_BASE}/home-equity-net-worth-tenure-canada-provinces</loc>
    <xhtml:link rel="alternate" hreflang="en" href="{constants.BASE_URL}/en{_HC_BASE}/home-equity-net-worth-tenure-canada-provinces" />
    <xhtml:link rel="alternate" hreflang="fr" href="{constants.BASE_URL}/fr{_FR_BASE}/avoir-foncier" />
  </url>
  <url>
    <loc>{constants.BASE_URL}{_HC_BASE}/household-count-size</loc>
    <xhtml:link rel="alternate" hreflang="en" href="{constants.BASE_URL}/en{_HC_BASE}/household-count-size" />
    <xhtml:link rel="alternate" hreflang="fr" href="{constants.BASE_URL}/fr{_FR_BASE}/nombre-menages-taille" />
  </url>
  <url>
    <loc>{constants.BASE_URL}/</loc>
    <xhtml:link rel="alternate" hreflang="en" href="{constants.BASE_URL}/en/" />
    <xhtml:link rel="alternate" hreflang="fr" href="{constants.BASE_URL}/fr/" />
  </url>
</urlset>"""
_HC_LISTING = f"""<ul>
<li><a href="{_HC_BASE}/home-equity-net-worth-tenure-canada-provinces">Home Equity and Net Worth</a></li>
<li><a href="{_HC_BASE}/household-count-size">Household Count and Size</a></li>
<li><a href="{_HC_BASE}/no-french-twin">English Only Table</a></li>
</ul>"""
# The live French listing links one page twice, once under another table's
# title; such a page's title is read from the page itself.
_FR_LISTING = f"""<ul>
<li><a href="{_FR_BASE}/avoir-foncier">Avoir foncier et valeur  nette</a></li>
<li><a href="{_FR_BASE}/nombre-menages-taille">M&eacute;nages selon le type</a></li>
<li><a href="{_FR_BASE}/nombre-menages-taille">Nombre de m&eacute;nages et taille</a></li>
</ul>"""
_COUNT_FR_HTML = """<html><body><h1>Nombre de ménages et taille des ménages</h1>
<input id="document-id" type="hidden" value="abc" /></body></html>"""
_NO_TWIN_HTML = """<html><body><h1>English Only Table</h1>
<input id="document-id" type="hidden" value="def" /></body></html>"""


async def test_french_listing_pairs_tables_through_cmhc_language_links(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_HC_BASE}", text=_HC_LISTING)
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP)
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_FR_BASE}", text=_FR_LISTING)
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}{_FR_BASE}/nombre-menages-taille", text=_COUNT_FR_HTML
    )
    # Not in the sitemap: the English page's own language link is read, and
    # this one has none.
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}{_HC_BASE}/no-french-twin", text=_NO_TWIN_HTML
    )
    # A French category name is accepted.
    result = await client.list_tables("caracteristiques-des-menages", lang="fr")
    assert result.category == "household-characteristics"
    assert [(t.slug, t.english_slug, t.title) for t in result.tables] == [
        (
            "avoir-foncier",
            "home-equity-net-worth-tenure-canada-provinces",
            "Avoir foncier et valeur nette",
        ),
        (
            "nombre-menages-taille",
            "household-count-size",
            "Nombre de ménages et taille des ménages",
        ),
        ("no-french-twin", "no-french-twin", "English Only Table"),
    ]
    assert result.tables[0].path == f"{_FR_BASE}/avoir-foncier"
    assert result.tables[2].note is not None
    assert result.tables[2].note.startswith("Aucune page française pour ce tableau :")
    assert result.note is not None and "no-french-twin" in result.note
    assert "sans page française gardent leur titre anglais :" in result.note
    assert (result.provenance.licence or "").startswith("Conditions d'utilisation de la SCHL")


async def test_french_errors_are_french():
    with pytest.raises(InvalidInput, match="^Entrée invalide : category doit être"):
        await client.list_tables("nothing", lang="fr")
    with pytest.raises(InvalidInput, match="slug ne doit pas être vide"):
        await client.get_table("household-characteristics", " ", lang="fr")


async def test_french_slug_reads_its_english_twin(httpx_mock):
    # Each call first tries the slug as an English page (a 404 is not cached).
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}{_HC_BASE}/avoir-foncier", status_code=404, is_reusable=True
    )
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP)
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_REPORT_PATH}", text=_REPORT_HTML)
    httpx_mock.add_response(
        url=(
            f"{constants.GET_REPORT_FILE_URL}?documentId=2850a1fa-f31c-4d27-a6fd-75de56e2cecb"
            "&contextLanguage=en"
        ),
        json=_REPORT_FILE,
    )
    table = await client.get_table("household-characteristics", "avoir-foncier")
    assert table.slug == "home-equity-net-worth-tenure-canada-provinces"
    link = await client.get_download_url("household-characteristics", "avoir-foncier")
    assert link.document_url == _REPORT_FILE


async def test_unknown_slug_stays_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{constants.BASE_URL}{_HC_BASE}/nope", status_code=404)
    httpx_mock.add_response(url=constants.SITEMAP_URL, text=_SITEMAP)
    with pytest.raises(NotFound):
        await client.get_table("household-characteristics", "nope")

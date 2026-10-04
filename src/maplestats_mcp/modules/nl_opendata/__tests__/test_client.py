from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.nl_opendata import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_LISTING_HTML = """
<div id="Master_ContentPlaceHolder1_DataSets">
  <div class="row-fluid well">
    <h2>Births by Age of Mother</h2>
    <strong>Date Released: </strong><span>2014-03-19</span><br/>
    <strong>Date Modified: </strong><span>2022-10-24</span><br/>
    <strong>Publisher: </strong><span>Open Data Newfoundland and Labrador</span><br/>
    <strong>Creator: </strong><span>NL Statistics Agency</span><br/>
    <a href="/public/opendata/page/?page-id=datasetdetails&amp;id=65">View</a>
  </div>
  <div class="row-fluid well">
    <h2>Hospitals</h2>
    <strong>Date Released: </strong><span>2013-12-09</span><br/>
    <strong>Date Modified: </strong><span>2019-04-01</span><br/>
    <strong>Publisher: </strong><span>Open Data Newfoundland and Labrador</span><br/>
    <strong>Creator: </strong><span>NL Statistics Agency</span><br/>
    <a href="/public/opendata/page/?page-id=datasetdetails&amp;id=69">View</a>
  </div>
</div>
"""

_DETAIL_HTML = """
<div id="Master_ContentPlaceHolder1_DataSets">
  <div class="row-fluid"><div class="well">
    <h2>Births by Age of Mother</h2>
    <dl class="dl-horizontal">
      <dt><strong>Title:</strong></dt><dd>Births by Age of Mother</dd>
      <dt><strong>Type:</strong></dt><dd>Tabular</dd>
      <dt><strong>Creator:</strong></dt><dd>NL Statistics Agency</dd>
      <dt><strong>Contact Email:</strong></dt><dd>finance@gov.nl.ca</dd>
      <dt><strong>Geographical Coverage:</strong></dt><dd>Newfoundland and Labrador</dd>
      <dt><strong>Contributor:</strong></dt><dd>Health Information Centre</dd>
      <dt><strong>Publisher:</strong></dt><dd>Open Data Newfoundland and Labrador</dd>
      <dt><strong>Temporal Coverage:</strong></dt><dd>1993-2021</dd>
      <dt><strong>Released Date:</strong></dt><dd>2014-03-19</dd>
      <dt><strong>Modified Date:</strong></dt><dd>2022-10-24</dd>
      <dt><strong>Rights:</strong></dt><dd>Open Government Licence</dd>
    </dl>
    <div id="Master_ContentPlaceHolder1_tags"><ul>
      <li><a href="/public/opendata/page/?page-id=datasets-tag&amp;id=63">Births</a></li>
      <li><a href="/public/opendata/page/?page-id=datasets-tag&amp;id=62">demographics</a></li>
    </ul></div>
    <div id="Master_ContentPlaceHolder1_downloads"><table>
      <tr><th>Title</th><th>Revision</th><th>Format</th><th>Revision Date</th><th>File size</th><th>Action</th></tr>
      <tr><td>Births by Age of Mother</td><td>8</td><td>CSV</td><td>2022-10-24</td>
        <td>5.13 MB (5381545 bytes)</td>
        <td><a href="/public/opendata/filedownload/?file-id=17368">Download file</a></td></tr>
    </table></div>
  </div></div>
</div>
"""

_EXPLORE_HTML = """
<div id="tagcontainer">
  <a href="/public/opendata/page/?page-id=datasets-tag&amp;id=62">demographics</a>
  <a href="/public/opendata/page/?page-id=datasets-tag&amp;id=35">health</a>
  <a href="/public/opendata/page/?page-id=datasets-tag&amp;id=62">demographics</a>
</div>
"""


async def test_search_filters_and_paginates_html_listing(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-tabular",
        text=_LISTING_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.search_datasets("birth", dataset_type="tabular", limit=5)
    assert result.total_count == 1
    assert result.returned_count == 1
    assert result.datasets[0].id == "65"
    assert result.datasets[0].released_date is not None
    assert result.datasets[0].released_date.year == 2014


async def test_search_all_combines_tabular_and_spatial_and_paginates(httpx_mock):
    spatial_html = (
        _LISTING_HTML.replace("Births by Age of Mother", "Coastal Change Data")
        .replace("id=65", "id=741")
        .replace("id=69", "id=86")
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-tabular",
        text=_LISTING_HTML,
        headers={"content-type": "text/html"},
    )
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-spatial",
        text=spatial_html,
        headers={"content-type": "text/html"},
    )
    result = await client.search_datasets("", dataset_type="all", limit=1, offset=1)
    assert result.total_count == 4
    assert result.returned_count == 1
    assert result.datasets[0].id == "741"


async def test_search_sends_live_date_sort_parameters(httpx_mock):
    httpx_mock.add_response(
        url=(
            f"{constants.BASE_URL}?page-id=datasets-tabular-date&sortby=datareleased"
            "&order=descending"
        ),
        text=_LISTING_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.search_datasets("", dataset_type="tabular", sort="released_desc")
    assert result.datasets[0].title == "Births by Age of Mother"


async def test_get_dataset_parses_metadata_topics_and_files(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasetdetails&id=65",
        text=_DETAIL_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.get_dataset("65")
    assert result.dataset_type == "Tabular"
    assert result.geographic_coverage == "Newfoundland and Labrador"
    assert result.topics == ["Births", "demographics"]
    assert result.files[0].id == "17368"
    assert result.files[0].size_bytes == 5381545
    assert result.files[0].download_url.endswith("file-id=17368")


async def test_list_tags_deduplicates_explore_tag_links(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=explore",
        text=_EXPLORE_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.list_tags()
    assert result.total_count == 2
    assert [tag.id for tag in result.tags] == ["62", "35"]


async def test_blank_detail_page_is_typed_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasetdetails&id=999999",
        text="<html><title>Dataset Details</title></html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(NotFound):
        await client.get_dataset("999999")


async def test_http_404_is_typed_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasetdetails&id=999999",
        status_code=404,
        text="not found",
    )
    with pytest.raises(NotFound):
        await client.get_dataset("999999")


async def test_invalid_inputs_are_typed():
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", limit=0)
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", offset=-1)
    with pytest.raises(InvalidInput):
        await client.search_datasets("x", dataset_type="bad")  # type: ignore[arg-type]
    with pytest.raises(InvalidInput):
        await client.get_dataset(" ")


# tag_population.html (id=4) and tag_unknown.html (id=999999) are the live tag
# pages of 2026-10-03, unchanged. The unknown id answers HTTP 200 with a
# "[There are no Data Sets that match your search.]" card.
_HERE = Path(__file__).parent


def _html(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def _mock_page(httpx_mock, query: str, text: str) -> None:
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?{query}", text=text, headers={"content-type": "text/html"}
    )


_TABULAR_WITH_POPULATION = _LISTING_HTML.replace("Hospitals", "Population Estimates").replace(
    "id=69", "id=70"
)
_EXPLORE_WITH_POPULATION = _EXPLORE_HTML.replace(
    "</div>", '<a href="/public/opendata/page/?page-id=datasets-tag&amp;id=4">population</a></div>'
)


async def test_unknown_tag_id_is_invalid_input(httpx_mock):
    _mock_page(httpx_mock, "page-id=datasets-tag&id=999999", _html("tag_unknown.html"))
    _mock_page(httpx_mock, "page-id=explore", _EXPLORE_WITH_POPULATION)
    with pytest.raises(InvalidInput, match="'999999' is not a tag on the portal"):
        await client.search_datasets(tag_id="999999")


async def test_known_tag_with_no_datasets_is_an_empty_success(httpx_mock):
    _mock_page(httpx_mock, "page-id=datasets-tag&id=35", _html("tag_unknown.html"))
    _mock_page(httpx_mock, "page-id=explore", _EXPLORE_WITH_POPULATION)
    result = await client.search_datasets(tag_id="35")
    assert result.total_count == 0


async def test_tag_search_fills_dataset_type_from_the_listings(httpx_mock):
    _mock_page(httpx_mock, "page-id=datasets-tag&id=4", _html("tag_population.html"))
    _mock_page(httpx_mock, "page-id=datasets-tabular", _TABULAR_WITH_POPULATION)
    _mock_page(
        httpx_mock,
        "page-id=datasets-spatial",
        "<div id='Master_ContentPlaceHolder1_DataSets'></div>",
    )
    result = await client.search_datasets(tag_id="4", limit=10)
    kinds = {d.id: d.dataset_type for d in result.datasets}
    # Live tag 4 lists datasets 65, 62, 70 and 241; the fixture listing has 65 and 70.
    assert set(kinds) == {"65", "62", "70", "241"}
    assert kinds["65"] == "tabular" and kinds["70"] == "tabular"
    assert kinds["62"] is None and kinds["241"] is None
    assert "2 tagged dataset(s) are in neither" in (result.provenance.coverage or "")


async def test_query_matches_every_word_in_any_order(httpx_mock):
    _mock_page(httpx_mock, "page-id=datasets-tabular", _TABULAR_WITH_POPULATION)
    # Live 2026-10-03 this phrase found nothing: it was matched as one substring.
    result = await client.search_datasets(
        "population estimates newfoundland", dataset_type="tabular"
    )
    assert [d.title for d in result.datasets] == ["Population Estimates"]
    assert (
        await client.search_datasets("ESTIMATES Population", dataset_type="tabular")
    ).total_count == 1
    assert (
        await client.search_datasets("population births", dataset_type="tabular")
    ).total_count == 0


async def test_missing_listing_container_is_upstream_error(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-tabular",
        text="<html><body>unexpected page</body></html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(UpstreamError):
        await client.search_datasets("x", dataset_type="tabular")


# French (lang="fr"): errors, provenance text and licence; English unchanged.


async def test_french_search_provenance_and_licence(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-tabular",
        text=_LISTING_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.search_datasets("birth", dataset_type="tabular", limit=5, lang="fr")
    assert (result.provenance.coverage or "").startswith(
        "1 jeux de données renvoyés sur 1 correspondants."
    )
    assert "pagination côté serveur" in (result.provenance.limits or "")
    assert "Licence du gouvernement ouvert – Terre-Neuve-et-Labrador" in (
        result.provenance.licence or ""
    )


async def test_english_search_provenance_unchanged(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasets-tabular",
        text=_LISTING_HTML,
        headers={"content-type": "text/html"},
    )
    result = await client.search_datasets("birth", dataset_type="tabular", limit=5)
    assert result.provenance.coverage == "1 of 1 matching records returned"


async def test_french_errors(httpx_mock):
    with pytest.raises(InvalidInput, match="Entrée invalide : limit doit être compris"):
        await client.search_datasets(limit=0, lang="fr")
    with pytest.raises(InvalidInput, match="dataset_id ne doit pas être vide"):
        await client.get_dataset(" ", lang="fr")
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}?page-id=datasetdetails&id=999999",
        text="<html><title>Dataset Details</title></html>",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(NotFound, match="est introuvable"):
        await client.get_dataset("999999", lang="fr")

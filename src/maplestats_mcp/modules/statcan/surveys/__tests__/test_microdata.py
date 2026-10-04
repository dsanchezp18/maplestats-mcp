from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


# Row shapes confirmed live 2026-10-02: linked survey with cycles and a
# lower-case p2sv.pl link; a <br>-separated list of record numbers with "N/A";
# an unlinked row under the generic bucket 8006 whose acronym is a <ul>.
_RDC_HTML = """
<html><body><table><tbody>
<tr class="active"><th scope="col"><p>Record number</p></th>
<th scope="col"><p>Survey name</p></th><th scope="col"><p>Acronym</p></th></tr>
<tr><th scope="row"><p>2103</p></th><td><p><a href="https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&amp;SDDS=2103">Annual Survey of Manufacturing and Logging Industries (ASML)</a></p>
<ul><li>ASML 2022</li><li>ASML 2023</li></ul></td><td><p>ASML</p></td></tr>
<tr><th scope="row"><p>2318</p></th><td><p><a href="https://www23.statcan.gc.ca/imdb/p2sv.pl?Function=getSurvey&amp;SDDS=2318">Industrial Product Price Index (IPPI)</a></p>
<ul><li>IPPI All Years</li></ul></td><td><p>IPPI</p></td></tr>
<tr><th scope="row"><p>N/A<br/>8006</p></th><td><p>Starts and Completion Survey (SCS) All Years</p>
<ul><li>SCS 1989</li><li>SCS 1990</li></ul></td><td><ul><li>SCS</li></ul></td></tr>
<tr><th scope="row"><p>3226<br/>5015</p></th><td><p>Canadian Community Health Survey <strong>linked</strong> to ELMLP Keys</p>
<ul><li>CCHS ELMLP All Years</li></ul></td><td><p>CCHS_ELMLP</p></td></tr>
</tbody></table></body></html>
"""

# RTRA: one <details> per survey under an h2 section, a link list that mixes
# SDDS= (survey record) and Id= (single cycle) links, one captioned table per
# dataset, and a dataset that deletes no variable (empty last cell).
_RTRA_HTML = """
<html><body><main>
<h2>Sélection de la langue</h2>
<h2>Social data</h2>
<details><summary>Canadian Community Health Survey (CCHS)</summary>
<h4 class="hidden">Canadian Community Health Survey (CCHS)</h4><h5>Survey details</h5>
<ul class="list-unstyled">
<li><a href="https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&amp;Id=5285">CCHS - Mental Health and Well-being - 2002</a></li>
<li><a href="https://www23.statcan.gc.ca/imdb/p2SV.pl?Function=getSurvey&amp;SDDS=5152">CCHS - Stigma - 2008</a></li>
</ul>
<table><caption>CCHS 2002</caption>
<tr><th>Tag Name</th><th>Dataset Name</th><th>Rounding Base</th><th>Weight Name</th><th>Deleted Variables</th></tr>
<tr><th>CCHS2002</th><td>HS</td><td>500</td><td>WTSB_M</td><td>ADMB_DAT ADMB_LHH PROVBIR</td></tr></table>
<table><caption>CCHS 2022 Provincial File</caption>
<tr><th>Tag Name</th><th>Dataset Name</th><th>Rounding Base</th><th>Weight Name</th><th>Deleted Variables</th></tr>
<tr><th>CCHS2022P</th><td>CCHS2022</td><td>10</td><td>WTS_M</td><td></td></tr>
<tr><th>CCHS2022Q</th><td>CCHS2022</td><td></td><td>WTS_M</td><td>GEODPC</td></tr></table>
</details>
<h2>Administrative data</h2>
<details><summary>Canadian Cancer Registry (CCR)</summary><h5>Survey details</h5>
<ul class="list-unstyled"><li>Canadian Cancer Registry</li></ul>
<table><caption>CCR 1992-2015</caption>
<tr><th>Tag Name</th><th>Dataset Name</th><th>Rounding Base</th><th>Weight Name</th><th>Deleted Variables</th></tr>
<tr><th>CCR</th><td>CCR</td><td>5</td><td>WEIGHT</td><td>PPROVBIR TPIN</td></tr></table>
</details>
</main></body></html>
"""

_RDC_URL = constants.RDC_URL_EN
_RTRA_URL = constants.RTRA_URL_EN


async def test_rdc_parses_record_numbers_cycles_and_links(httpx_mock):
    httpx_mock.add_response(url=_RDC_URL, content=_RDC_HTML.encode())
    result = await client.search_rdc_holdings()
    assert result.total_matched == 4
    asml = result.holdings[0]
    assert asml.record_numbers == [2103]
    assert asml.cycles == ["ASML 2022", "ASML 2023"]
    assert asml.detail_url is not None and asml.detail_url.endswith("SDDS=2103")


async def test_rdc_handles_na_multi_number_unlinked_and_list_acronym(httpx_mock):
    httpx_mock.add_response(url=_RDC_URL, content=_RDC_HTML.encode())
    result = await client.search_rdc_holdings()
    scs = result.holdings[2]
    assert scs.record_numbers == [8006]
    assert scs.detail_url is None
    assert scs.acronym == "SCS"
    linked = result.holdings[3]
    assert linked.record_numbers == [3226, 5015]
    assert linked.name == "Canadian Community Health Survey linked to ELMLP Keys"


async def test_rdc_query_matches_cycles_and_requires_every_word(httpx_mock):
    httpx_mock.add_response(url=_RDC_URL, content=_RDC_HTML.encode())
    assert (await client.search_rdc_holdings("scs 1990")).total_matched == 1
    assert (await client.search_rdc_holdings("scs price")).total_matched == 0
    assert (await client.search_rdc_holdings("2318")).holdings[0].acronym == "IPPI"


async def test_rdc_french_page_uses_french_url(httpx_mock):
    httpx_mock.add_response(url=constants.RDC_URL_FR, content=_RDC_HTML.encode())
    result = await client.search_rdc_holdings(lang="fr", limit=1)
    assert result.returned_count == 1
    assert result.provenance.url == constants.RDC_URL_FR
    assert (result.provenance.limits or "").startswith("Une liste des fonds, pas des données")
    assert "Licence ouverte de Statistique Canada" in (result.provenance.licence or "")


async def test_microdata_errors_in_french(httpx_mock):
    with pytest.raises(InvalidInput, match="limit doit être entre 1 et"):
        await client.search_rtra_datasets(limit=0, lang="fr")
    httpx_mock.add_response(url=constants.RDC_URL_FR, content=b"<html><table></table></html>")
    with pytest.raises(UpstreamError, match="aucune ligne de tableau"):
        await client.search_rdc_holdings(lang="fr")
    with pytest.raises(InvalidInput, match="limit must be between 1 and"):
        await client.search_rtra_datasets(limit=0)


async def test_rdc_empty_table_is_an_error_not_a_result(httpx_mock):
    httpx_mock.add_response(url=_RDC_URL, content=b"<html><body><table></table></body></html>")
    with pytest.raises(UpstreamError):
        await client.search_rdc_holdings()


async def test_rtra_parses_tables_sections_and_links(httpx_mock):
    httpx_mock.add_response(url=_RTRA_URL, content=_RTRA_HTML.encode())
    result = await client.search_rtra_datasets()
    assert result.total_matched == 4
    first = result.datasets[0]
    assert first.category == "Social data"
    assert first.tag_name == "CCHS2002"
    assert first.table_label == "CCHS 2002"
    assert first.rounding_base == 500
    assert first.weight_name == "WTSB_M"
    assert first.deleted_variables == ["ADMB_DAT", "ADMB_LHH", "PROVBIR"]
    assert [(link.sdds_id, link.instance_id) for link in first.survey_links] == [
        (None, 5285),
        (5152, None),
    ]
    cancer = result.datasets[-1]
    assert cancer.category == "Administrative data"
    assert cancer.survey_links == []


async def test_rtra_blank_cells_become_empty_or_none(httpx_mock):
    httpx_mock.add_response(url=_RTRA_URL, content=_RTRA_HTML.encode())
    result = await client.search_rtra_datasets("cchs 2022")
    assert [d.tag_name for d in result.datasets] == ["CCHS2022P", "CCHS2022Q"]
    assert result.datasets[0].deleted_variables == []
    assert result.datasets[1].rounding_base is None


async def test_rtra_deleted_variable_filter_is_case_insensitive(httpx_mock):
    httpx_mock.add_response(url=_RTRA_URL, content=_RTRA_HTML.encode())
    result = await client.search_rtra_datasets(deleted_variable="provbir")
    assert [d.tag_name for d in result.datasets] == ["CCHS2002"]


async def test_microdata_tools_reject_bad_lang_and_limit():
    with pytest.raises(InvalidInput):
        await client.search_rdc_holdings(lang="de")
    with pytest.raises(InvalidInput):
        await client.search_rtra_datasets(limit=0)

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.borealis import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_SEARCH = re.compile(re.escape(constants.SEARCH_URL) + r"\?.*")
_FILES = re.compile(re.escape(constants.FILES_URL) + r"\?.*")
_EXPORT = re.compile(re.escape(constants.DDI_EXPORT_URL) + r"\?.*")
_PID = "doi:10.5683/SP3/TVVQPG"

# Shapes from live responses, 2026-10-02. The abstract arrives as escaped HTML.
_OAI_DDI = b"""<codeBook xmlns="ddi:codebook:2_5" version="2.5">
<docDscr><citation><titlStmt><titl>Labour Force Survey, September 2023</titl></titlStmt>
<verStmt source="archive"><version date="2026-03-28" type="RELEASED">6</version></verStmt>
<biblCit>Labour Statistics Division, 2023, Borealis, V6</biblCit></citation></docDscr>
<stdyDscr><citation><titlStmt><titl>Labour Force Survey, September 2023</titl>
<altTitl>Enqu\xc3\xaate sur la population active, septembre 2023</altTitl></titlStmt>
<prodStmt><producer abbr="LSD">Labour Statistics Division</producer></prodStmt>
<serStmt><serName>Labour Force Survey</serName></serStmt></citation>
<stdyInfo><subject><keyword xml:lang="en">Social Sciences</keyword><keyword>Employment</keyword>
<topcClas>Labour and Employment</topcClas></subject>
<abstract>The LFS provides estimates.&lt;br>&lt;br>Revised in &lt;b>January 2025&lt;/b>.</abstract>
<sumDscr><timePrd event="start" date="2023-10-10">2023-10-10</timePrd>
<timePrd event="end" date="2023-10-16">2023-10-16</timePrd><nation>Canada</nation>
<anlyUnit>Individuals</anlyUnit><universe>Population 15 and over.</universe></sumDscr></stdyInfo>
<method><dataColl><sampProc>Stratified multi-stage &lt;p>design&lt;/p></sampProc></dataColl></method>
<dataAccs><useStmt><restrctn>For non-profit research only.</restrctn></useStmt>
<notes type="DVN:TOU">&lt;h2>Statistics Canada Open Licence&lt;/h2>&lt;p>Use freely.&lt;/p></notes></dataAccs>
</stdyDscr></codeBook>"""

_FULL_DDI = b"""<codeBook xmlns="ddi:codebook:2_5" version="2.5"><dataDscr>
<var ID="v1" name="SURVMNTH"><location fileid="f1"/><labl level="variable">Survey month</labl>
<catgry><catValu>5</catValu></catgry><catgry><catValu>2</catValu></catgry></var>
<var ID="v2" name="LFSSTAT"><location fileid="f1"/><labl level="variable">Labour force status</labl></var>
<var ID="v3" name="UNION"><location fileid="f1"/></var>
</dataDscr><fileDscr ID="f1"><fileTxt><fileName>LFS_September_2023.tab</fileName></fileTxt></fileDscr>
</codeBook>"""

_FILES_MIXED = {
    "status": "OK",
    "data": [
        {
            "label": "LFS_September_2023.tab",
            "restricted": False,
            "dataFile": {
                "id": 1056407,
                "filesize": 11352347,
                "contentType": "text/tab-separated-values",
            },
        },
        {
            "label": "PCCF_V2603.zip",
            "restricted": True,
            "dataFile": {"id": 9, "filesize": 34159169},
        },
    ],
}


async def test_search_uses_all_public_collections_and_not_dli(httpx_mock):
    httpx_mock.add_response(
        url=_SEARCH,
        json={
            "status": "OK",
            "data": {
                "total_count": 7,
                "items": [
                    {
                        "name": "Labour Force Survey, September 2023",
                        "global_id": _PID,
                        "url": "https://doi.org/10.5683/SP3/TVVQPG",
                        "name_of_dataverse": "PUMFs",
                        "description": "<p>The LFS</p> provides estimates.",
                        "keywords": ["Employment"],
                        "producers": None,
                        "fileCount": 21,
                    }
                ],
            },
        },
    )
    result = await client.search_odesi_datasets("labour force")
    assert result.total_matched == 7
    dataset = result.datasets[0]
    assert dataset.persistent_id == _PID
    assert dataset.description == "The LFS provides estimates."
    assert dataset.producers == []
    request = httpx_mock.get_requests()[0]
    query = request.url.query.decode()
    assert query.count("subtree=") == 6
    assert "subtree=dli" not in query
    assert "labour+AND+force" in query or "labour%20AND%20force" in query


async def test_search_collection_narrows_subtree(httpx_mock):
    httpx_mock.add_response(url=_SEARCH, json={"status": "OK", "data": {"total_count": 0}})
    await client.search_odesi_datasets("focus", collection="polls")
    query = httpx_mock.get_requests()[0].url.query.decode()
    assert "subtree=pop" in query and query.count("subtree=") == 1


async def test_dataset_detail_flattens_html_and_separates_public_from_restricted(httpx_mock):
    httpx_mock.add_response(url=_EXPORT, content=_OAI_DDI)
    httpx_mock.add_response(url=_FILES, json=_FILES_MIXED)
    detail = await client.get_odesi_dataset("https://doi.org/10.5683/SP3/TVVQPG")
    assert detail.persistent_id == _PID
    assert detail.abstract == "The LFS provides estimates. Revised in January 2025."
    assert detail.time_period == "2023-10-10 to 2023-10-16"
    assert detail.version == "V6"
    assert detail.alt_titles == ["Enquête sur la population active, septembre 2023"]
    assert detail.sampling == "Stratified multi-stage design"
    assert detail.terms_of_use is not None and "Open Licence" in detail.terms_of_use
    assert [f.name for f in detail.public_files] == ["LFS_September_2023.tab"]
    assert detail.public_files[0].download_url.endswith("/api/access/datafile/1056407")
    assert detail.restricted_file_names == ["PCCF_V2603.zip"]
    assert "1 of 2 files are public" in detail.access_summary


async def test_dataset_all_restricted_gives_no_links(httpx_mock):
    httpx_mock.add_response(url=_EXPORT, content=_OAI_DDI)
    httpx_mock.add_response(
        url=_FILES,
        json={
            "status": "OK",
            "data": [{"label": "a.tab", "restricted": True, "dataFile": {"id": 1}}],
        },
    )
    detail = await client.get_odesi_dataset(_PID)
    assert detail.public_files == []
    assert detail.access_summary.startswith("All 1 files are restricted")


async def test_variables_search_matches_name_or_label_and_names_the_file(httpx_mock):
    httpx_mock.add_response(url=_EXPORT, content=_FULL_DDI)
    result = await client.search_odesi_variables(_PID, "labour status")
    assert [v.name for v in result.variables] == ["LFSSTAT"]
    assert result.total_variables == 3
    assert result.variables[0].file_name == "LFS_September_2023.tab"
    everything = await client.search_odesi_variables(_PID, "survmnth")
    assert everything.variables[0].categories == 2


async def test_variables_export_failed_403_is_a_note_not_an_error(httpx_mock):
    httpx_mock.add_response(
        url=_EXPORT, status_code=403, json={"status": "ERROR", "message": "Export Failed"}
    )
    result = await client.search_odesi_variables("doi:10.5683/SP3/TDQHW1")
    assert result.total_variables == 0
    assert result.note is not None and "variable-level DDI" in result.note


async def test_unknown_dataset_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_EXPORT, status_code=404, json={"status": "ERROR"})
    with pytest.raises(NotFound):
        await client.get_odesi_dataset("doi:10.5683/SP3/NOPE00")


async def test_bad_inputs_are_rejected():
    with pytest.raises(InvalidInput):
        await client.get_odesi_dataset("not a doi")
    with pytest.raises(InvalidInput):
        await client.search_odesi_datasets(collection="dli")
    with pytest.raises(InvalidInput):
        await client.search_odesi_variables(_PID, limit=0)

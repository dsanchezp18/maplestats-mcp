"""Requested members that come back with no series, shaped like table
18-10-0004-01 (CPI) on 2026-11-09: mortgage interest cost (product 85) is
published for Canada (geography 2) only, so a key asking for Ontario (14) or
Toronto (16) with it returns a partial result or StatCan's empty document."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.statcan.sdmx import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


_STRUCTURE_URL = f"{constants.BASE_URL}structure/Data_Structure_18100004"
_DATA_URL = f"{constants.BASE_URL}data/DF_18100004/"

_STRUCTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
               xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
               xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <mes:Structures>
    <str:Dataflows><str:Dataflow id="DF_18100004" agencyID="StatCan" version="1.0"/></str:Dataflows>
    <str:Codelists>
      <str:Codelist id="CL_Geography">
        <str:Code id="2"><com:Name xml:lang="en">Canada</com:Name><com:Name xml:lang="fr">Canada</com:Name></str:Code>
        <str:Code id="14"><com:Name xml:lang="en">Ontario</com:Name><com:Name xml:lang="fr">Ontario</com:Name></str:Code>
        <str:Code id="16"><com:Name xml:lang="en">Toronto, Ontario</com:Name><com:Name xml:lang="fr">Toronto, Ontario</com:Name></str:Code>
      </str:Codelist>
      <str:Codelist id="CL_Products_and_product_groups">
        <str:Code id="2"><com:Name xml:lang="en">All-items</com:Name><com:Name xml:lang="fr">Ensemble</com:Name></str:Code>
        <str:Code id="85"><com:Name xml:lang="en">Mortgage interest cost</com:Name><com:Name xml:lang="fr">Coût de l'intérêt hypothécaire</com:Name></str:Code>
      </str:Codelist>
    </str:Codelists>
    <str:DataStructures>
      <str:DataStructure id="Data_Structure_18100004">
        <str:DataStructureComponents>
          <str:DimensionList>
            <str:Dimension id="Geography" position="1">
              <str:LocalRepresentation><str:Enumeration><Ref id="CL_Geography"/></str:Enumeration></str:LocalRepresentation>
            </str:Dimension>
            <str:Dimension id="Products_and_product_groups" position="2">
              <str:LocalRepresentation><str:Enumeration><Ref id="CL_Products_and_product_groups"/></str:Enumeration></str:LocalRepresentation>
            </str:Dimension>
            <str:TimeDimension id="TIME_PERIOD" position="3"/>
          </str:DimensionList>
        </str:DataStructureComponents>
      </str:DataStructure>
    </str:DataStructures>
  </mes:Structures>
</mes:Structure>
"""

_HEAD = (
    "<?xml version='1.0' encoding='UTF-8'?><message:GenericData "
    'xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
    'xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic">'
    "<message:DataSet>"
)

# StatCan's answer to a key matching nothing (live 2026-11-09 for 16.85).
_NO_MATCH_XML = _HEAD + "</generic:Series> </message:DataSet> </message:GenericData>"


def _data(*keys: tuple[str, str]) -> bytes:
    series = "".join(
        "<generic:Series><generic:SeriesKey>"
        f'<generic:Value id="Geography" value="{geo}"/>'
        f'<generic:Value id="Products_and_product_groups" value="{product}"/>'
        '</generic:SeriesKey><generic:Obs><generic:ObsDimension value="2026-09"/>'
        '<generic:ObsValue value="183.2"/></generic:Obs></generic:Series>'
        for geo, product in keys
    )
    return (_HEAD + series + "</message:DataSet></message:GenericData>").encode()


async def test_partial_match_names_the_member_that_returned_nothing(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}2+14.85?lastNObservations=1", content=_data(("2", "85"))
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, content=_STRUCTURE_XML.encode())
    result = await client.get_data(18100004, "2+14.85", last_n_observations=1)
    assert [s.series_key["Geography"] for s in result.series] == ["2"]
    assert result.provenance.limits is not None
    assert "no series for Geography 14 (Ontario)" in result.provenance.limits
    assert "does not publish" in result.provenance.limits


async def test_partial_match_note_follows_lang(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}2+14.85?lastNObservations=1", content=_data(("2", "85"))
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, content=_STRUCTURE_XML.encode())
    result = await client.get_data(18100004, "2+14.85", last_n_observations=1, lang="fr")
    assert result.provenance.limits is not None
    assert "aucune série pour Geography 14 (Ontario)" in result.provenance.limits


async def test_partial_match_without_structure_still_names_the_member_id(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}2+14.85?lastNObservations=1", content=_data(("2", "85"))
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, status_code=403)
    result = await client.get_data(18100004, "2+14.85", last_n_observations=1)
    assert result.provenance.limits is not None
    assert "no series for dimension 1 14" in result.provenance.limits


async def test_missing_combinations_are_listed_when_every_member_came_back(httpx_mock):
    # Ontario has all-items; Canada has both: 14.85 is not published.
    httpx_mock.add_response(
        url=f"{_DATA_URL}2+14.2+85?lastNObservations=1",
        content=_data(("2", "2"), ("2", "85"), ("14", "2")),
    )
    result = await client.get_data(18100004, "2+14.2+85", last_n_observations=1)
    assert result.provenance.limits is not None
    assert "1 of 4 requested combinations have no series" in result.provenance.limits
    assert "14.85" in result.provenance.limits


async def test_full_match_adds_no_note_and_no_structure_request(httpx_mock):
    httpx_mock.add_response(url=f"{_DATA_URL}2.85?lastNObservations=1", content=_data(("2", "85")))
    result = await client.get_data(18100004, "2.85", last_n_observations=1)
    assert result.provenance.limits is None
    assert all("/structure/" not in str(r.url) for r in httpx_mock.get_requests())


async def test_empty_combination_says_where_it_is_published(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}16.85?lastNObservations=1", content=_NO_MATCH_XML.encode()
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, content=_STRUCTURE_XML.encode())
    # Probe with the (small) geography wildcarded: only Canada has the product.
    httpx_mock.add_response(url=f"{_DATA_URL}.85?lastNObservations=1", content=_data(("2", "85")))
    # And with the product wildcarded: Toronto has all-items only.
    httpx_mock.add_response(url=f"{_DATA_URL}16.?lastNObservations=1", content=_data(("16", "2")))
    with pytest.raises(NotFound) as exc_info:
        await client.get_data(18100004, "16.85", last_n_observations=1)
    message = str(exc_info.value)
    assert "matched no series" in message
    assert "does not publish this combination" in message
    assert "Geography 16 (Toronto, Ontario)" in message
    assert "Products_and_product_groups 85 (Mortgage interest cost)" in message
    assert "Geography has series only for: 2 (Canada)" in message
    assert "Products_and_product_groups has series only for: 2 (All-items)" in message
    assert "sdmx_get_structure" in message


async def test_empty_combination_names_a_member_the_table_does_not_have(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}999.85?lastNObservations=1", content=_NO_MATCH_XML.encode()
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, content=_STRUCTURE_XML.encode())
    with pytest.raises(NotFound, match="Not a member of this table: Geography 999"):
        await client.get_data(18100004, "999.85", last_n_observations=1)


async def test_empty_combination_in_french(httpx_mock):
    httpx_mock.add_response(
        url=f"{_DATA_URL}16.85?lastNObservations=1", content=_NO_MATCH_XML.encode()
    )
    httpx_mock.add_response(url=_STRUCTURE_URL, content=_STRUCTURE_XML.encode())
    httpx_mock.add_response(url=f"{_DATA_URL}.85?lastNObservations=1", content=_data(("2", "85")))
    httpx_mock.add_response(
        url=f"{_DATA_URL}16.?lastNObservations=1", content=_NO_MATCH_XML.encode()
    )
    with pytest.raises(NotFound) as exc_info:
        await client.get_data(18100004, "16.85", last_n_observations=1, lang="fr")
    message = str(exc_info.value)
    assert "ne publie pas cette combinaison" in message
    assert "Coût de l'intérêt hypothécaire" in message
    # French text gets a no-break space before the colon.
    assert "Geography n'a de séries que pour : 2 (Canada)" in message
    assert "aucun membre de Products_and_product_groups" in message

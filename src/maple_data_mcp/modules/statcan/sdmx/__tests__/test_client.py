"""Tests for the SDMX client against synthetic SDMX-ML fixtures shaped
exactly like the live XML fetched from StatCan this session (structure
and Generic Data documents)."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.statcan.sdmx import client, constants
from maple_data_mcp.shared.errors import InvalidInput

_STRUCTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
               xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
               xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <mes:Structures>
    <str:Dataflows>
      <str:Dataflow id="DF_18100004" agencyID="StatCan" version="1.0"/>
    </str:Dataflows>
    <str:Codelists>
      <str:Codelist id="CL_Geography" agencyID="StatCan" version="1.0">
        <str:Code id="1">
          <com:Name xml:lang="en">Canada</com:Name>
          <com:Name xml:lang="fr">Canada</com:Name>
        </str:Code>
        <str:Code id="2">
          <com:Name xml:lang="en">Ontario</com:Name>
          <com:Name xml:lang="fr">Ontario</com:Name>
          <str:Parent><Ref id="1"/></str:Parent>
        </str:Code>
        <str:Code id="3">
          <com:Name xml:lang="en">Quebec</com:Name>
          <com:Name xml:lang="fr">Quebec</com:Name>
          <str:Parent><Ref id="1"/></str:Parent>
        </str:Code>
      </str:Codelist>
    </str:Codelists>
    <str:DataStructures>
      <str:DataStructure id="Data_Structure_18100004">
        <str:DataStructureComponents>
          <str:DimensionList>
            <str:Dimension id="Geography" position="1">
              <str:LocalRepresentation>
                <str:Enumeration><Ref id="CL_Geography"/></str:Enumeration>
              </str:LocalRepresentation>
            </str:Dimension>
            <str:TimeDimension id="TIME_PERIOD" position="2"/>
          </str:DimensionList>
        </str:DataStructureComponents>
      </str:DataStructure>
    </str:DataStructures>
  </mes:Structures>
</mes:Structure>
"""

_DATA_XML = """<?xml version='1.0' encoding='UTF-8'?>
<message:GenericData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
                      xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic">
  <message:DataSet>
    <generic:Series>
      <generic:SeriesKey>
        <generic:Value id="Geography" value="1"/>
      </generic:SeriesKey>
      <generic:Attributes>
        <generic:Value id="VECTOR_ID" value="41690973"/>
        <generic:Value id="SCALAR_FACTOR" value="0"/>
        <generic:Value id="NB_DECIMAL" value="1"/>
      </generic:Attributes>
      <generic:Obs>
        <generic:ObsDimension value="2026-07"/>
        <generic:ObsValue value="169.9"/>
      </generic:Obs>
      <generic:Obs>
        <generic:ObsDimension value="2026-08"/>
        <generic:ObsValue value="169.8"/>
      </generic:Obs>
    </generic:Series>
  </message:DataSet>
</message:GenericData>
"""


def _parse(xml_text: str):
    from xml.etree import ElementTree as ET

    return ET.fromstring(xml_text.encode("utf-8"))


def test_parse_structure_extracts_dataflow_and_dimension_with_codes():
    root = _parse(_STRUCTURE_XML)
    dataflow_id, dimensions = client._parse_structure(root)
    assert dataflow_id == "DF_18100004"
    assert len(dimensions) == 1
    geo = dimensions[0]
    assert geo.dimension_id == "Geography"
    assert geo.codelist_id == "CL_Geography"
    assert {c.id for c in geo.codes} == {"1", "2", "3"}
    ontario = next(c for c in geo.codes if c.id == "2")
    assert ontario.name_en == "Ontario"
    assert ontario.parent_id == "1"


async def test_get_key_for_dimension_returns_only_leaf_codes(httpx_mock):
    httpx_mock.add_response(
        url=f"{constants.BASE_URL}structure/Data_Structure_18100004",
        content=_STRUCTURE_XML.encode("utf-8"),
    )
    result = await client.get_key_for_dimension(18100004, dimension_position=1)
    # "1" (Canada) is a parent of "2" and "3" -> it must be excluded from the
    # leaf set, since including it would double-count national totals
    # alongside their provincial breakdown.
    assert result.leaf_code_count == 2
    assert set(result.or_key.split("+")) == {"2", "3"}


def test_parse_data_extracts_series_key_attributes_and_observations():
    root = _parse(_DATA_XML)
    series = client._parse_data(root, max_rows=500)
    assert len(series) == 1
    s = series[0]
    assert s.series_key == {"Geography": "1"}
    assert s.vector_id == 41690973
    assert s.scalar_factor == 0
    assert s.decimals == 1
    assert len(s.observations) == 2
    assert s.observations[0].period == "2026-07"
    assert s.observations[0].value == 169.9


def test_parse_data_respects_max_rows_cap():
    root = _parse(_DATA_XML)
    series = client._parse_data(root, max_rows=1)
    assert len(series[0].observations) == 1


async def test_get_data_rejects_last_n_with_start_period():
    with pytest.raises(InvalidInput):
        await client.get_data(18100004, "2", start_period="2020-01", last_n_observations=5)

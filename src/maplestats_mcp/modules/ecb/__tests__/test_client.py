"""Tests for ecb/client.py, shaped on live answers from 2026-11-07: SDMX-ML 2.1
structures with English and other names, code lists cut by an "Allowed"
content constraint, csvdata with a KEY column and series attributes, 400 for a
key of the wrong length and 404 for no data."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.ecb import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = "https://data-api.ecb.europa.eu/service/"
CATALOGUE = re.compile(re.escape(BASE + "dataflow/ECB") + r"$")
STRUCTURE = re.compile(re.escape(BASE + "dataflow/ECB/EXR") + r"\?.*")
DATA = re.compile(re.escape(BASE + "data/EXR/") + r".*")

_NS = (
    'xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
    'xmlns:str="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure" '
    'xmlns:com="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"'
)

_CATALOGUE = f"""<?xml version='1.0' encoding='UTF-8'?><mes:Structure {_NS}><mes:Structures>
<str:Dataflows>
<str:Dataflow id="EXR" agencyID="ECB" version="1.0"><com:Name xml:lang="en">Exchange Rates</com:Name>
<str:Structure><Ref id="ECB_EXR1" agencyID="ECB" version="1.0" class="DataStructure"/></str:Structure></str:Dataflow>
<str:Dataflow id="ZZZ" agencyID="ECB" version="1.0"><com:Name xml:lang="de">Etwas</com:Name>
<str:Structure><Ref id="ECB_ZZZ" agencyID="ECB" version="1.0" class="DataStructure"/></str:Structure></str:Dataflow>
</str:Dataflows></mes:Structures></mes:Structure>"""


def _codelist(cl: str, codes: list[tuple[str, str]]) -> str:
    items = "".join(
        f'<str:Code id="{c}"><com:Name xml:lang="en">{n}</com:Name></str:Code>' for c, n in codes
    )
    return f'<str:Codelist id="{cl}" agencyID="ECB" version="1.0">{items}</str:Codelist>'


def _dim(dim: str, position: int, cl: str) -> str:
    return (
        f'<str:Dimension id="{dim}" position="{position}">'
        f'<str:ConceptIdentity><Ref id="{dim}" class="Concept"/></str:ConceptIdentity>'
        f'<str:LocalRepresentation><str:Enumeration><Ref id="{cl}" class="Codelist"/>'
        "</str:Enumeration></str:LocalRepresentation></str:Dimension>"
    )


_STRUCTURE = f"""<?xml version='1.0' encoding='UTF-8'?><mes:Structure {_NS}><mes:Structures>
<str:Codelists>
{_codelist("CL_FREQ", [("D", "Daily"), ("M", "Monthly")])}
{_codelist("CL_CURRENCY", [("CAD", "Canadian dollar"), ("USD", "US dollar"), ("EUR", "Euro"), ("XXX", "Unused")])}
{_codelist("CL_EXR_TYPE", [("SP00", "Spot")])}
{_codelist("CL_EXR_SUFFIX", [("A", "Average or standardised measure for given frequency")])}
{_codelist("CL_UNIT", [("CAD", "Canadian dollar"), ("PCPA", "Percent per annum")])}
{_codelist("CL_UNIT_MULT", [("0", "Units"), ("6", "Millions")])}
</str:Codelists>
<str:Concepts><str:ConceptScheme id="ECB_CONCEPTS">
<str:Concept id="CURRENCY"><com:Name xml:lang="en">Currency</com:Name></str:Concept>
</str:ConceptScheme></str:Concepts>
<str:DataStructures><str:DataStructure id="ECB_EXR1" agencyID="ECB" version="1.0">
<str:DataStructureComponents><str:DimensionList>
{_dim("FREQ", 1, "CL_FREQ")}{_dim("CURRENCY", 2, "CL_CURRENCY")}
{_dim("CURRENCY_DENOM", 3, "CL_CURRENCY")}{_dim("EXR_TYPE", 4, "CL_EXR_TYPE")}
{_dim("EXR_SUFFIX", 5, "CL_EXR_SUFFIX")}
<str:TimeDimension id="TIME_PERIOD" position="6"/>
</str:DimensionList></str:DataStructureComponents></str:DataStructure></str:DataStructures>
<str:Constraints><str:ContentConstraint id="EXR_CONSTRAINTS" type="Allowed">
<str:ConstraintAttachment><str:Dataflow><Ref id="EXR" class="Dataflow"/></str:Dataflow></str:ConstraintAttachment>
<str:CubeRegion include="true"><com:KeyValue id="CURRENCY"><com:Value>CAD</com:Value><com:Value>USD</com:Value></com:KeyValue></str:CubeRegion>
</str:ContentConstraint></str:Constraints>
</mes:Structures></mes:Structure>"""

_HEADER = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,"
    "TITLE,TITLE_COMPL,UNIT,UNIT_MULT\n"
)
_DATA = _HEADER + (
    "EXR.D.CAD.EUR.SP00.A,D,CAD,EUR,SP00,A,2026-11-05,1.5675,A,Canadian dollar/Euro ECB "
    'reference exchange rate,"ECB reference exchange rate, Canadian dollar/Euro, 2.15 pm (C.E.T.)",'
    "CAD,0\n"
    "EXR.D.CAD.EUR.SP00.A,D,CAD,EUR,SP00,A,2026-11-04,1.5701,A,Canadian dollar/Euro ECB "
    'reference exchange rate,"ECB reference exchange rate, Canadian dollar/Euro, 2.15 pm (C.E.T.)",'
    "CAD,0\n"
    "EXR.D.CAD.EUR.SP00.A,D,CAD,EUR,SP00,A,2026-11-06,NaN,A,Canadian dollar/Euro ECB "
    'reference exchange rate,"ECB reference exchange rate, Canadian dollar/Euro, 2.15 pm (C.E.T.)",'
    "CAD,0\n"
)
_NODATA = _HEADER + (
    "EXR.D.CAD.EUR.SP00.A,D,CAD,EUR,SP00,A,,,,Canadian dollar/Euro ECB reference exchange "
    "rate,,CAD,0\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,,,,US dollar/Euro ECB reference exchange rate,,USD,0\n"
)


@pytest.fixture
def exr(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, text=_CATALOGUE, is_optional=True)
    httpx_mock.add_response(url=STRUCTURE, text=_STRUCTURE, is_optional=True)


async def test_indicator_rows_sorted_with_canadian_pair(exr, httpx_mock):
    httpx_mock.add_response(url=DATA, text=_DATA)
    result = await client.get_indicator("eur_cad", last_n=5)
    assert [(r.date, r.value) for r in result.rows] == [
        ("2026-11-04", 1.5701),
        ("2026-11-05", 1.5675),
    ]
    row = result.rows[0]
    assert (row.series_id, row.unit, row.frequency) == (
        "EXR.D.CAD.EUR.SP00.A",
        "CAD per EUR",
        "Daily",
    )
    assert "FXEURCAD" in (result.compare_with_canada or "")
    assert result.series[0].key == "D.CAD.EUR.SP00.A"
    assert "format=csvdata" in result.csv_url
    assert "ECB statistics" in (result.provenance.licence or "")
    request = httpx_mock.get_requests(url=DATA)[0]
    assert request.url.params["lastNObservations"] == "5"


async def test_describe_keeps_allowed_codes_and_filters(exr):
    structure = await client.describe_dataset("exr")
    assert structure.key_template == "FREQ.CURRENCY.CURRENCY_DENOM.EXR_TYPE.EXR_SUFFIX"
    currency = structure.dimensions[1]
    assert currency.name == "Currency"
    assert [c.id for c in currency.codes] == ["CAD", "USD"]
    # A dimension the constraint does not name keeps its whole code list.
    assert [c.id for c in structure.dimensions[2].codes] == ["CAD", "USD", "EUR", "XXX"]
    canadian = await client.describe_dataset("EXR", code_query="canadian")
    assert [c.id for c in canadian.dimensions[1].codes] == ["CAD"]
    assert structure.example_key == "D.CAD.EUR.SP00.A"


async def test_search_series_lists_titles(exr, httpx_mock):
    httpx_mock.add_response(url=DATA, text=_NODATA)
    found = await client.search_series("EXR", "D..EUR.SP00.A", query="canadian")
    assert [s.key for s in found.series] == ["D.CAD.EUR.SP00.A"]
    request = httpx_mock.get_requests(url=DATA)[0]
    assert request.url.params["detail"] == "nodata"


async def test_key_checks_and_errors(exr, httpx_mock):
    with pytest.raises(InvalidInput):
        await client.get_series("EXR", "D.CAD.EUR")
    with pytest.raises(InvalidInput):
        await client.get_series("EXR", "D.CAD.EUR.SP00.A", start_period="May 2024")
    httpx_mock.add_response(url=DATA, status_code=404, text="No results found.")
    with pytest.raises(NotFound):
        await client.get_series("EXR", "D.ZZZ.EUR.SP00.A", last_n=1)
    with pytest.raises(NotFound):
        await client.describe_dataset("NOPE")
    with pytest.raises(InvalidInput):
        await client.get_indicator("gdp")


async def test_list_datasets_english_name_and_query(exr):
    listed = await client.list_datasets()
    assert [d.id for d in listed.datasets] == ["EXR", "ZZZ"]
    assert listed.datasets[1].name == "Etwas"
    found = await client.list_datasets(query="exchange", lang="fr")
    assert [d.id for d in found.datasets] == ["EXR"]
    assert found.datasets[0].description and "euro" in found.datasets[0].description

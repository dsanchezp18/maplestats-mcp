"""Tests for fed/client.py, shaped on the release zips read live on 2026-11-07:
SDMX-ML 1.0 compact data with a header Name and Prepared, several DataSets
(one of them discontinued), a series repeated in two groups, 'ND' observations
carrying -9999, RXI$US series quoted in US dollars, UNIT_MULT written 1e+09
while the code list writes 1000000000, and a struct file with a DOCTYPE."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from maplestats_mcp.modules.fed import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

H10_URL = "https://www.federalreserve.gov/releases/h10/data/FRB_h10_xml.zip"
H15_URL = "https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip"

_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<message:MessageGroup xmlns:message="http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message"
 xmlns:common="http://www.SDMX.org/resources/SDMXML/schemas/v1_0/common"
 xmlns:frb="http://www.federalreserve.gov/structure/compact/common">
  <message:Header>
    <message:ID>{code}</message:ID>
    <message:Name>{name}</message:Name>
    <message:Prepared>2026-11-02T16:52:42</message:Prepared>
    <message:Sender id="FRB"><message:Name>Federal Reserve Board</message:Name></message:Sender>
  </message:Header>
"""


def _series(attrs: str, short: str, obs: list[tuple[str, str, str]]) -> str:
    rows = "".join(
        f'<frb:Obs OBS_STATUS="{s}" OBS_VALUE="{v}" TIME_PERIOD="{d}" />' for d, v, s in obs
    )
    return (
        f"<kf:Series {attrs}><frb:Annotations><common:Annotation>"
        "<common:AnnotationType>Short Description</common:AnnotationType>"
        f"<common:AnnotationText>{short}</common:AnnotationText></common:Annotation>"
        "</frb:Annotations>" + rows + "</kf:Series>"
    )


_H10_DATA = (
    _HEADER.format(code="H10", name="G.5/H.10 - Foreign Exchange Rates")
    + '<frb:DataSet id="H10" xmlns:kf="http://www.federalreserve.gov/structure/compact/H10_H10">'
    + _series(
        'CURRENCY="CAD" FREQ="9" FX="CAD" SERIES_NAME="RXI_N.B.CA" UNIT="Currency" UNIT_MULT="1"',
        "Canada Dollar",
        [
            ("2026-10-28", "1.4036", "A"),
            ("2026-10-29", "1.3975", "A"),
            ("2026-10-30", "1.3957", "A"),
            ("2026-11-02", "-9999", "ND"),
        ],
    )
    + _series(
        'CURRENCY="EUR" FREQ="9" FX="EUR" SERIES_NAME="RXI$US_N.B.EU" UNIT="Currency" '
        'UNIT_MULT="1"',
        "Euro Area Euro",
        [("2026-10-30", "1.1163", "A")],
    )
    + _series(
        'CURRENCY="CAD" FREQ="129" FX="CAD" SERIES_NAME="RXI_N.M.CA" UNIT="Currency:_Per_USD" '
        'UNIT_MULT="1"',
        "Canada Dollar",
        [("2026-09-30", "1.3972", "A"), ("2026-10-31", "1.4135", "A")],
    )
    + "</frb:DataSet></message:MessageGroup>"
)

_STRUCT = """<?xml version="1.0"?>
<!DOCTYPE message:Structure>
<message:Structure xmlns:message="http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message"
 xmlns:structure="http://www.SDMX.org/resources/SDMXML/schemas/v1_0/structure">
  <message:CodeLists>
    <structure:CodeList id="CL_FREQ" agency="FRB">
      <structure:Code value="9"><structure:Description>Business day</structure:Description></structure:Code>
      <structure:Code value="129"><structure:Description>Monthly</structure:Description></structure:Code>
    </structure:CodeList>
    <structure:CodeList id="CL_FX" agency="FRB">
      <structure:Code value="CAD"><structure:Description>Canadian dollar</structure:Description></structure:Code>
      <structure:Code value="EUR"><structure:Description>Euro</structure:Description></structure:Code>
    </structure:CodeList>
    <structure:CodeList id="CL_UNIT_MULT" agency="FRB">
      <structure:Code value="1"><structure:Description>One</structure:Description></structure:Code>
      <structure:Code value="1000000000"><structure:Description>Billions</structure:Description></structure:Code>
    </structure:CodeList>
  </message:CodeLists>
  <message:Concepts>
    <structure:Concept id="FX"><structure:Name>Foreign exchange</structure:Name></structure:Concept>
  </message:Concepts>
  <message:KeyFamilies>
    <structure:KeyFamily id="H10" agency="FRB">
      <structure:Name>Foreign Exchange Rates</structure:Name>
      <structure:Components>
        <structure:Dimension concept="FREQ" codelist="CL_FREQ"/>
        <structure:Dimension concept="FX" codelist="CL_FX"/>
        <structure:Attribute concept="UNIT_MULT" codelist="CL_UNIT_MULT"/>
      </structure:Components>
    </structure:KeyFamily>
  </message:KeyFamilies>
</message:Structure>"""

_H15_DATA = (
    _HEADER.format(code="H15", name="H.15 Selected Interest Rates")
    + '<frb:DataSet id="H15" xmlns:kf="http://www.federalreserve.gov/structure/compact/H15_H15">'
    + _series(
        'CURRENCY="NA" FREQ="9" INSTRUMENT="TCMNOM" MATURITY="Y10" SERIES_NAME="RIFLGFCY10_N.B" '
        'UNIT="Percent:_Per_Year" UNIT_MULT="1"',
        "10-year Treasury constant maturity",
        [("2026-11-04", "4.90", "A"), ("2026-11-05", "4.84", "A")],
    )
    + _series(
        'CURRENCY="USD" FREQ="129" SERIES_NAME="M2.M" UNIT="Currency" UNIT_MULT="1e+09"',
        "M2; Seasonally adjusted",
        [("2026-09-30", "23413.9", "A")],
    )
    + "</frb:DataSet>"
    + '<frb:DataSet id="discontinued" xmlns:kf="http://www.federalreserve.gov/structure/compact/H15_discontinued">'
    + _series(
        'CURRENCY="NA" FREQ="9" INSTRUMENT="TCMNOM" MATURITY="Y10" SERIES_NAME="RIFLGFCY10_N.B" '
        'UNIT="Percent:_Per_Year" UNIT_MULT="1"',
        "A duplicate that must not replace the first copy",
        [("1990-01-02", "8.0", "A")],
    )
    + _series(
        'CURRENCY="NA" FREQ="9" INSTRUMENT="TCMNOM" MATURITY="Y30" SERIES_NAME="OLD30_N.B" '
        'UNIT="Percent:_Per_Year" UNIT_MULT="1"',
        "30-year Treasury, old series",
        [("2001-01-02", "5.5", "A")],
    )
    + "</frb:DataSet></message:MessageGroup>"
)


def _zip(code: str, data: str, struct: str | None = _STRUCT) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{code}_data.xml", data)
        if struct is not None:
            archive.writestr(f"{code}_struct.xml", struct)
    return buffer.getvalue()


@pytest.fixture
def h10(httpx_mock):
    httpx_mock.add_response(url=H10_URL, content=_zip("H10", _H10_DATA))


@pytest.fixture
def h15(httpx_mock):
    httpx_mock.add_response(url=H15_URL, content=_zip("H15", _H15_DATA))


async def test_indicator_rows_drop_no_data_and_name_the_canadian_pair(h10):
    result = await client.get_indicator("cad_per_usd", last_n=5)
    assert [(r.date, r.value) for r in result.rows] == [
        ("2026-10-28", 1.4036),
        ("2026-10-29", 1.3975),
        ("2026-10-30", 1.3957),
    ]
    row = result.rows[0]
    assert (row.series_id, row.unit, row.frequency) == ("RXI_N.B.CA", "CAD per USD", "Business day")
    assert "FXUSDCAD" in (result.compare_with_canada or "")
    info = result.series[0]
    assert info.dimensions[0].label == "Canadian dollar"
    assert result.provenance.as_of is not None
    assert "public domain" in (result.provenance.licence or "").lower()


async def test_dollar_quoted_series_and_date_bounds(h10):
    euro = await client.get_series("H10", ["rxi$us_n.b.eu"], start_date="2026")
    assert euro.rows[0].unit == "USD per EUR"
    monthly = await client.get_series("H10", ["RXI_N.M.CA"], end_date="2026-09")
    assert [r.date for r in monthly.rows] == ["2026-09-30"]


async def test_first_copy_wins_and_multiplier_word(h15):
    result = await client.get_series("H15", ["RIFLGFCY10_N.B", "M2.M"], last_n=1)
    assert [(r.series_id, r.value) for r in result.rows] == [
        ("RIFLGFCY10_N.B", 4.84),
        ("M2.M", 23413.9),
    ]
    assert result.series[1].unit == "USD, billions"
    assert result.series[1].unit_multiplier == "1e+09"


async def test_search_ranks_and_hides_discontinued(h15):
    result = await client.search_series("treasury 10", release="H15")
    assert [s.series_id for s in result.series] == ["RIFLGFCY10_N.B"]
    old = await client.search_series("treasury", release="H15", include_discontinued=True)
    assert "OLD30_N.B" in [s.series_id for s in old.series]
    assert next(s for s in old.series if s.series_id == "OLD30_N.B").discontinued


async def test_describe_lists_groups_and_codes(h10):
    structure = await client.describe_release("h10")
    assert structure.series_count == 3
    assert structure.frequencies == ["Business day", "Monthly"]
    fx = structure.groups[0].dimensions[0]
    assert (fx.id, fx.name) == ("FX", "Foreign exchange")
    assert [c.code for c in fx.codes] == ["CAD", "EUR"]
    assert "RXI_N.B.CA" in structure.example_series


async def test_errors(h10):
    with pytest.raises(InvalidInput):
        await client.get_series("Z1", ["X"])
    with pytest.raises(NotFound):
        await client.get_series("H10", ["NOPE"])
    with pytest.raises(InvalidInput):
        await client.get_series("H10", ["RXI_N.B.CA"], start_date="Jan 2024")
    with pytest.raises(NotFound):
        await client.get_series("H10", ["RXI_N.B.CA"], start_date="2030")
    with pytest.raises(InvalidInput):
        await client.get_indicator("gdp")


async def test_french_error_and_bad_zip(httpx_mock):
    httpx_mock.add_response(url=H10_URL, content=b"<html>not a zip</html>")
    with pytest.raises(UpstreamError):
        await client.get_series("H10", ["RXI_N.B.CA"])
    with pytest.raises(InvalidInput, match=re.compile("publication", re.IGNORECASE)):
        await client.describe_release("XX", lang="fr")


async def test_list_releases_is_offline():
    releases = await client.list_releases(lang="fr")
    codes = [r.code for r in releases.releases]
    assert {"H15", "H10", "G17"} <= set(codes)
    assert all(r.data_url.endswith("_xml.zip") for r in releases.releases)

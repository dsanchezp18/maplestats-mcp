"""Tests for modules/justice_laws/client.py, shaped on live 2026-09-23 XML."""

from __future__ import annotations

import pytest

from maple_data_mcp.modules.justice_laws import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_BASE = "http://laws-lois.justice.gc.ca"
_INDEX = f"""<?xml version="1.0" encoding="utf-8"?>
<ActsRegsList><Acts>
<Act><UniqueId>A-1</UniqueId><OfficialNumber>A-1</OfficialNumber><Language>eng</Language>
<LinkToXML>{_BASE}/eng/XML/A-1.xml</LinkToXML>
<LinkToHTMLToC>{_BASE}/eng/acts/A-1/index.html</LinkToHTMLToC>
<Title>Access to Information Act</Title><CurrentToDate>2026-07-21</CurrentToDate></Act>
<Act><UniqueId>A-1</UniqueId><OfficialNumber>A-1</OfficialNumber><Language>fra</Language>
<LinkToXML>{_BASE}/fra/XML/A-1.xml</LinkToXML>
<LinkToHTMLToC>{_BASE}/fra/lois/A-1/index.html</LinkToHTMLToC>
<Title>Loi sur l’accès à l’information</Title><CurrentToDate>2026-07-21</CurrentToDate></Act>
</Acts><Regulations>
<Regulation id="734629e" olid="723140f"><UniqueId>SOR-2007-151</UniqueId><Language>eng</Language>
<LinkToXML>{_BASE}/eng/XML/SOR-2007-151.xml</LinkToXML>
<LinkToHTMLToC>{_BASE}/eng/regulations/SOR-2007-151/index.html</LinkToHTMLToC>
<Title>“MV Sonia” Remission Order, 2007</Title><CurrentToDate>2026-07-21</CurrentToDate></Regulation>
<Regulation id="723140f" olid="734629e"><UniqueId>DORS-2007-151</UniqueId><Language>fra</Language>
<LinkToXML>{_BASE}/fra/XML/DORS-2007-151.xml</LinkToXML>
<LinkToHTMLToC>{_BASE}/fra/reglements/DORS-2007-151/index.html</LinkToHTMLToC>
<Title>Décret de remise concernant le « MV Sonia » (2007)</Title></Regulation>
</Regulations></ActsRegsList>""".encode()

_ACT = b"""<?xml version="1.0"?><Statute xmlns:lims="http://justice.gc.ca/lims"
 lims:lastAmendedDate="2026-06-14" in-force="yes" xml:lang="en">
<Identification><LongTitle>An Act to extend the present laws of Canada</LongTitle></Identification>
<Body>
<Heading level="1"><TitleText>Short Title</TitleText></Heading>
<Section lims:lastAmendedDate="2002-12-31"><MarginalNote>Short title</MarginalNote><Label>1</Label>
<Text>This Act may be cited as the <XRefExternal>Access to Information Act</XRefExternal>.</Text>
<HistoricalNote><HistoricalNoteSubItem>1980-81-82-83, c. 111</HistoricalNoteSubItem></HistoricalNote>
</Section>
<Heading level="1"><TitleText>Access to Government Records</TitleText></Heading>
<Section lims:lastAmendedDate="2019-06-21"><MarginalNote>Right to access to records</MarginalNote>
<Label>4</Label>
<Subsection><Label>(1)</Label><Text>every person who is</Text>
<Paragraph><Label>(a)</Label><Text>a Canadian citizen, or</Text></Paragraph>
<ContinuedSectionSubsection><Text>has a right to access.</Text></ContinuedSectionSubsection>
</Subsection>
</Section>
</Body></Statute>"""


async def test_search_ranks_exact_citation_and_filters_language(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, content=_INDEX)
    result = await client.search("access information")
    assert [law.id for law in result.laws] == ["A-1"]
    assert result.laws[0].url.startswith("https://")
    french = await client.search("information", lang="fr")
    assert french.laws[0].title == "Loi sur l’accès à l’information"
    by_citation = await client.search("SOR/2007-151", kind="regulation")
    assert by_citation.laws[0].id == "SOR-2007-151"
    with pytest.raises(InvalidInput):
        await client.search("   ")


async def test_outline_and_section_text(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, content=_INDEX)
    httpx_mock.add_response(url="https://laws-lois.justice.gc.ca/eng/XML/A-1.xml", content=_ACT)
    outline = await client.get_outline("a-1")
    assert outline.section_count == 2
    assert outline.in_force is True
    assert outline.sections[1].heading == "Access to Government Records"
    assert outline.sections[1].last_amended is not None

    section = await client.get_section("A-1", "4")
    assert section.marginal_note == "Right to access to records"
    assert section.text.splitlines() == [
        "4",
        "  (1) every person who is",
        "    (a) a Canadian citizen, or",
        "    has a right to access.",
    ]
    assert section.url == "https://laws-lois.justice.gc.ca/eng/acts/A-1/section-4.html"
    first = await client.get_section("A-1", "1")
    assert "1980-81-82-83" not in first.text
    with pytest.raises(NotFound, match="no section"):
        await client.get_section("A-1", "999")


async def test_regulation_switches_to_french_twin(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, content=_INDEX)
    httpx_mock.add_response(
        url="https://laws-lois.justice.gc.ca/fra/XML/DORS-2007-151.xml",
        content=b"<Regulation><Body><Section><Label>1</Label><Text>Remise</Text></Section></Body></Regulation>",
    )
    section = await client.get_section("SOR/2007-151", "1", lang="fr")
    assert section.law.id == "DORS-2007-151"
    assert section.url.endswith("/fra/reglements/DORS-2007-151/art-1.html")


async def test_unknown_law_and_bad_offset(httpx_mock):
    httpx_mock.add_response(url=constants.INDEX_URL, content=_INDEX)
    with pytest.raises(NotFound):
        await client.get_outline("Z-99")
    with pytest.raises(InvalidInput):
        await client.get_outline("A-1", offset=-1)

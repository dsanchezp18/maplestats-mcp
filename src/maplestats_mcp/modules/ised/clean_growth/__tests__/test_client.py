"""Parsers run against the real pages saved 2026-09-25 (investment_en.html,
investment_fr.html), so a layout change shows up as a test diff."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from maplestats_mcp.modules.ised.clean_growth import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

_HERE = Path(__file__).parent
_EN = (_HERE / "investment_en.html").read_text(encoding="utf-8")
_FR = (_HERE / "investment_fr.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def test_amounts_and_percentages_in_both_languages():
    assert client.parse_amount("0.20 billion", "en") == 200_000_000
    assert client.parse_amount("0,20\xa0milliards", "fr") == 200_000_000
    assert client.parse_percent("16\xa0%", "fr") == 16.0
    assert client.parse_amount("n/a", "en") is None
    # An unknown scale word is not read as plain dollars.
    assert client.parse_amount("0.20 trillion", "en") is None


def test_comma_is_thousands_in_english_and_decimal_in_french():
    # The old parser read every comma as a decimal mark: "1,200 million" became 1.2 million.
    assert client.parse_amount("1,200 million", "en") == 1_200_000_000
    assert client.parse_amount("$1,200.5 million", "en") == 1_200_500_000
    assert client.parse_amount("1,5 milliard", "fr") == 1_500_000_000
    assert client.parse_amount("1,5\xa0milliards", "fr") == 1_500_000_000
    # French groups thousands with a (no-break) space, not a comma.
    assert client.parse_amount("1\u202f200 millions", "fr") == 1_200_000_000
    assert client.parse_percent("16,5\xa0%", "fr") == 16.5
    assert client.parse_percent("1,000%", "en") == 1000.0


def test_headline_from_prose():
    headline = client.parse_headline(_EN)
    assert headline.period == "2016-2024"
    assert (headline.programs, headline.organizations) == (57, 22)
    assert headline.committed_cad == 29e9
    assert headline.agreements == 8300
    assert headline.median_agreement_cad == 278_000
    assert headline.non_repayable_share_percent == 58
    assert headline.business_support_cad == 12.94e9
    assert headline.jobs_created_or_maintained == 198_000
    assert headline.not_found == []


async def test_unread_figures_are_named_in_limits(httpx_mock):
    reworded = _EN.replace("median agreement value is", "typical agreement is worth").replace(
        "0.20 billion", "0.20 trillion"
    )
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], text=reworded)
    result = await client.federal_investment("en")
    assert result.headline.median_agreement_cad is None
    assert result.headline.not_found == ["median_agreement_cad"]
    assert result.by_year[0].value_cad is None
    assert result.by_year[0].value_as_published == "0.20 trillion"
    limits = result.provenance.limits or ""
    assert "not found in the page text and are null: median_agreement_cad" in limits
    assert "could not be read (see value_as_published): 1" in limits


def test_tables_drop_footnote_markers():
    by_year, by_province, by_subsector = client.parse_tables(_EN, "en")
    assert by_year[0].label == "2016" and by_year[0].value_cad == 200_000_000
    # The yearly values add up to the $29 billion headline (29.64).
    assert round(sum(r.value_cad or 0 for r in by_year) / 1e9, 2) == 29.64
    assert by_province[2].label == "Ontario" and by_province[2].share_percent == 29
    assert "Other 5 subsectors" in [r.label for r in by_subsector]  # no "table 3 note 3"


def test_french_labels_and_notes():
    by_year, by_province, _ = client.parse_tables(_FR, "fr")
    assert by_province[0].label == "Provinces de l'Atlantique"
    assert by_year[-1].value_cad == 4_340_000_000
    notes = client.parse_notes(_FR)
    assert notes[0].startswith("Les projets de technologies propres")
    assert not any("Retour" in note for note in notes)


async def test_federal_investment_uses_english_numbers(httpx_mock):
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], text=_EN)
    httpx_mock.add_response(url=constants.PAGE_URLS["fr"], text=_FR)
    result = await client.federal_investment("fr")
    assert result.headline.committed_cad == 29e9
    assert result.by_subsector[1].label == "Transport"
    assert result.records_resource_id == constants.GRANTS_RESOURCE_ID
    assert result.pdf_url.endswith("-fr.pdf")


async def test_missing_tables_raise(httpx_mock):
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], text="<html><main></main></html>")
    with pytest.raises(UpstreamError, match="three data tables"):
        await client.federal_investment("en")
    with pytest.raises(InvalidInput):
        await client.federal_investment("de")


async def test_french_provenance_text_is_french(httpx_mock):
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], text=_EN)
    httpx_mock.add_response(url=constants.PAGE_URLS["fr"], text=_FR)
    result = await client.federal_investment("fr")
    assert (result.provenance.freshness or "").startswith("mis à jour à chaque diffusion")
    assert "Agrégats tels que publiés ;" in (result.provenance.limits or "")


async def test_french_missing_tables_error_is_french(httpx_mock):
    empty = "<html><main></main></html>"
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], text=empty)
    httpx_mock.add_response(url=constants.PAGE_URLS["fr"], text=empty)
    with pytest.raises(UpstreamError) as excinfo:
        await client.federal_investment("fr")
    assert str(excinfo.value).startswith("La source amont a renvoyé une réponse inattendue :")
    assert "trois tableaux" in str(excinfo.value)


class _CountingStream(httpx.AsyncByteStream):
    """A body with no Content-Length that counts the chunks the client pulled."""

    def __init__(self, chunks: int, size: int) -> None:
        self.chunks, self.size, self.pulled = chunks, size, 0

    async def __aiter__(self):
        for _ in range(self.chunks):
            self.pulled += 1
            yield b"x" * self.size


async def test_oversized_page_stops_at_the_cap_instead_of_loading_it(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "MAX_PAGE_BYTES", 1_000)
    body = _CountingStream(chunks=50, size=500)
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], stream=body)
    with pytest.raises(UpstreamError, match="larger than 1,000 bytes"):
        await client.federal_investment("en")
    assert body.pulled <= 3


async def test_oversized_page_error_is_in_the_language_asked_for(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "MAX_PAGE_BYTES", 1_000)
    httpx_mock.add_response(url=constants.PAGE_URLS["en"], stream=_CountingStream(50, 500))
    with pytest.raises(UpstreamError, match="dépasse"):
        await client.federal_investment("fr")

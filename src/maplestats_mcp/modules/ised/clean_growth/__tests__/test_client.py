"""Parsers run against the real pages saved 2026-09-25 (investment_en.html,
investment_fr.html), so a layout change shows up as a test diff."""

from __future__ import annotations

from pathlib import Path

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
    assert client.parse_amount("0.20 billion") == 200_000_000
    assert client.parse_amount("0,20\xa0milliards") == 200_000_000
    assert client.parse_percent("16\xa0%") == 16.0
    assert client.parse_amount("n/a") is None


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


def test_tables_drop_footnote_markers():
    by_year, by_province, by_subsector = client.parse_tables(_EN)
    assert by_year[0].label == "2016" and by_year[0].value_cad == 200_000_000
    # The yearly values add up to the $29 billion headline (29.64).
    assert round(sum(r.value_cad or 0 for r in by_year) / 1e9, 2) == 29.64
    assert by_province[2].label == "Ontario" and by_province[2].share_percent == 29
    assert "Other 5 subsectors" in [r.label for r in by_subsector]  # no "table 3 note 3"


def test_french_labels_and_notes():
    by_year, by_province, _ = client.parse_tables(_FR)
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

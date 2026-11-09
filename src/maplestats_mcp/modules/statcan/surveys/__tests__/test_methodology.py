"""IMDB methodology sections, parsed from recorded survey records.

The fixtures are IMDB records fetched on 2026-11-09 and saved unchanged:
the Labour Force Survey (3701, a household sample survey, English and French),
the Consumer Price Index (2301, a price sample from several sources) and the
Death database (3233, an administrative census of registrations).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maplestats_mcp.modules.statcan.surveys import client, constants
from maplestats_mcp.modules.statcan.surveys.schemas import SurveyMethodology
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.brief import shape
from maplestats_mcp.shared.errors import InvalidInput

_FIXTURES = Path(__file__).parent / "fixtures"
_ALL_SECTIONS = list(SurveyMethodology.model_fields)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _page(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _mock(httpx_mock, survey_id: int, lang: str = "en") -> None:
    base = constants.IMDB_BASE_URL_FR if lang == "fr" else constants.IMDB_BASE_URL_EN
    suffix = "fra" if lang == "fr" else "eng"
    httpx_mock.add_response(
        url=f"{base}?Function=getSurvey&SDDS={survey_id}",
        content=_page(f"imdb_{survey_id}_{suffix}.html"),
        headers={"Content-Type": "text/html"},  # IMDB sends no charset; the page is UTF-8
    )


def test_section_names_match_the_headings_table():
    assert _ALL_SECTIONS == list(constants.IMDB_SECTION_HEADINGS)


async def test_lfs_record_has_every_section_and_its_key_facts(httpx_mock):
    _mock(httpx_mock, 3701)
    result = await client.get_survey_metadata(3701)

    assert result.name == "Labour Force Survey (LFS)"
    assert result.status == "Active"
    assert result.frequency == "Monthly"
    assert result.reference_period == "Usually the week containing the 15th day of the month"
    assert result.collection_period == "The ten days immediately following the reference period"
    assert result.response == "mandatory"
    assert result.collection_methods == "Data are collected directly from survey respondents."
    assert result.survey_design == "This is a sample survey with a cross-sectional design."
    assert len(result.sample_size) == 1
    assert "65,000 households" in result.sample_size[0]

    sections = result.methodology.model_dump()
    assert all(sections[name] for name in _ALL_SECTIONS)
    assert sections["target_population"].startswith(
        "The Labour Force Survey (LFS) target population includes all persons aged 15"
    )
    # HTML escapes are decoded and <br><br> becomes a paragraph break.
    assert "&#" not in sections["sampling"]
    assert "\n\n" in sections["target_population"]


async def test_sections_are_shortened_without_a_section_argument(httpx_mock):
    _mock(httpx_mock, 3701)
    result = await client.get_survey_metadata(3701)

    assert "sampling" in result.trimmed_sections
    assert "instrument_design" not in result.trimmed_sections  # 413 characters, kept whole
    for name in result.trimmed_sections:
        text = getattr(result.methodology, name)
        assert text.endswith(" [...]")
        assert len(text) <= constants.IMDB_SECTION_CHARS + len(" [...]")
    assert result.provenance.limits is not None
    assert "section=[...]" in result.provenance.limits


async def test_section_argument_returns_those_sections_in_full(httpx_mock):
    _mock(httpx_mock, 3701)
    result = await client.get_survey_metadata(3701, section=["sampling", "disclosure_control"])

    assert result.trimmed_sections == []
    assert result.provenance.limits is None
    assert result.methodology.target_population is None
    assert result.methodology.data_accuracy is None
    sampling = result.methodology.sampling
    assert sampling is not None
    assert "approximately 65,000 households" in sampling
    assert not sampling.endswith("[...]")
    disclosure = result.methodology.disclosure_control
    assert disclosure is not None
    assert "Nunavut: 200" in disclosure
    # The short summary fields come from the full page whatever the argument.
    assert result.response == "mandatory"


async def test_section_argument_accepts_one_name(httpx_mock):
    _mock(httpx_mock, 3701)
    result = await client.get_survey_metadata(3701, section="data_accuracy")

    assert result.methodology.data_accuracy is not None
    assert result.methodology.data_accuracy.startswith("Since the LFS is a sample survey")
    assert result.methodology.sampling is None


async def test_unknown_section_raises():
    with pytest.raises(InvalidInput, match="unknown section 'methods'"):
        await client.get_survey_metadata(3701, section=["sampling", "methods"])


async def test_cpi_record_from_several_sources(httpx_mock):
    _mock(httpx_mock, 2301)
    result = await client.get_survey_metadata(2301, section="data_sources")

    assert result.name == "Consumer Price Index (CPI)"
    assert result.response == "mandatory"
    assert result.collection_methods is not None
    assert result.collection_methods.startswith(
        "Data are collected directly from survey respondents, extracted from administrative files"
    )
    assert result.survey_design == "This is a sample survey."
    assert result.collection_period is None  # the CPI record states none
    assert result.reference_period is not None
    assert "2002" in result.reference_period
    assert any("1,000,000 price quotes" in s for s in result.sample_size)
    data_sources = result.methodology.data_sources
    assert data_sources is not None
    assert data_sources.startswith("Responding to this survey is mandatory.")


async def test_administrative_census_record(httpx_mock):
    _mock(httpx_mock, 3233)
    result = await client.get_survey_metadata(3233)

    assert result.collection_methods == "Data are extracted from administrative files."
    assert result.survey_design == "This survey is a census with a cross-sectional design."
    assert result.sample_size == []  # a census: no sample to size
    assert result.methodology.sampling == (
        "This survey is a census with a cross-sectional design.\n\nNo sampling is done."
    )
    assert result.methodology.instrument_design is not None
    assert "does not apply" in result.methodology.instrument_design
    assert result.collection_period is not None
    assert result.collection_period.startswith("For annual data, approximately 13 months")


async def test_french_record(httpx_mock):
    _mock(httpx_mock, 3701, lang="fr")
    result = await client.get_survey_metadata(3701, lang="fr", section="sampling")

    assert result.name == "Enquête sur la population active (EPA)"
    assert result.status == "Active"
    assert result.frequency == "Mensuelle"
    assert result.response == "obligatoire"
    assert (
        result.collection_methods == "Les données sont obtenues directement auprès des répondants."
    )
    assert result.survey_design == "Il s'agit d'une enquête transversale par échantillon."
    assert result.reference_period == "Habituellement la semaine où tombe le 15ième jour du mois"
    assert any("65 000 ménages" in s for s in result.sample_size)
    assert result.methodology.sampling is not None
    assert result.methodology.sampling.startswith("Il s'agit d'une enquête transversale")


async def test_brief_result_keeps_the_section_text(httpx_mock):
    _mock(httpx_mock, 3701)
    result = await client.get_survey_metadata(3701)
    full = result.model_dump(mode="json")

    brief = shape(full, "brief", "en")
    assert brief is not None
    assert brief["methodology"] == {k: v for k, v in full["methodology"].items() if v}
    assert brief["sample_size"] == full["sample_size"]
    assert brief["trimmed_sections"] == full["trimmed_sections"]
    assert brief["response"] == "mandatory"
    assert "section=[...]" in brief["provenance"]["limits"]

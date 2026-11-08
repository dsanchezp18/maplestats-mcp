"""Tests for ilo/client.py on responses recorded live on 2026-11-08
(fixtures/): the dataflow list in English and French (8 of its 1,215 flows),
the structure of DF_UNE_DEAP_SEX_AGE_RT (area codelist and constraint cut to
ten codes) and SDMX-CSV data in English (annual, four areas) and French
(monthly). The 404 text and the HTTP 500 Oracle error are the API's own."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.ilo import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

FIXTURES = Path(__file__).parent / "fixtures"

CATALOGUE = "https://sdmx.ilo.org/rest/dataflow/ILO/all/latest"
STRUCTURE = re.compile(
    r"https://sdmx\.ilo\.org/rest/dataflow/ILO/DF_UNE_DEAP_SEX_AGE_RT/latest\?.*"
)
DATA = re.compile(r"https://sdmx\.ilo\.org/rest/data/ILO,DF_UNE_DEAP_SEX_AGE_RT,/.*")


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _mock(httpx_mock, csv_name: str | None = "data_une_en.csv", lang: str = "en"):
    httpx_mock.add_response(
        url=CATALOGUE,
        json=_json(f"dataflows_{lang}.json"),
        is_optional=True,
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=STRUCTURE, json=_json("structure_une.json"), is_optional=True, is_reusable=True
    )
    if csv_name:
        httpx_mock.add_response(url=DATA, text=_text(csv_name))


def _data_requests(httpx_mock):
    return [r for r in httpx_mock.get_requests() if "/rest/data/" in str(r.url)]


# ------------------------------------------------------------------ search


async def test_search_ranks_name_matches_and_flags_modelled(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_json("dataflows_en.json"))
    result = await client.search_datasets("unemployment rate")
    ids = [d.id for d in result.datasets]
    assert ids[0] == "DF_UNE_DEAP_SEX_AGE_RT"
    modelled = next(d for d in result.datasets if d.id == "DF_UNE_2EAP_SEX_AGE_RT")
    assert modelled.modelled is True
    assert result.datasets[0].modelled is False
    # HTML is gone and LAST_UPDATE (dd/mm/yyyy) is read as ISO.
    assert "<" not in result.datasets[0].description
    assert result.datasets[0].last_updated and result.datasets[0].last_updated.startswith("2026-")
    assert result.provenance.commercial_use == "allowed"
    assert "CC BY 4.0" in (result.provenance.licence or "")


async def test_search_in_french_folds_accents(httpx_mock):
    httpx_mock.add_response(
        url=CATALOGUE, json=_json("dataflows_fr.json"), match_headers={"Accept-Language": "fr"}
    )
    result = await client.search_datasets("chomage par sexe et age", lang="fr")
    assert result.datasets[0].id == "DF_UNE_DEAP_SEX_AGE_RT"
    assert "chômage" in result.datasets[0].name.lower()


async def test_search_needs_words():
    with pytest.raises(InvalidInput, match="words"):
        await client.search_datasets("the of")


# --------------------------------------------------------------- structure


async def test_describe_gives_codes_with_data_and_a_canada_key(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    result = await client.describe_dataset("ILO,DF_UNE_DEAP_SEX_AGE_RT")
    assert result.key_template == "REF_AREA.FREQ.MEASURE.SEX.AGE"
    assert result.example_key == "CAN..UNE_DEAP_RT.."
    area = result.dimensions[0]
    assert {"CAN", "USA", "X01"} <= {c.id for c in area.codes}
    sex = next(d for d in result.dimensions if d.id == "SEX")
    assert ("SEX_T", "Total") in [(c.id, c.name) for c in sex.codes]
    assert "lastNObservations=1" in result.csv_url and "csvfilewithlabels" in result.csv_url
    assert result.citation.startswith("International Labour Organization (")


async def test_unknown_dataset_is_not_found(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    with pytest.raises(NotFound, match="ilo_search_datasets"):
        await client.describe_dataset("DF_NOPE")


async def test_bad_dataset_id_is_invalid():
    with pytest.raises(InvalidInput):
        await client.describe_dataset("unemployment")


# --------------------------------------------------------------------- data


async def test_get_data_parses_rows_units_sources_and_status(httpx_mock):
    _mock(httpx_mock)
    result = await client.get_data(
        "DF_UNE_DEAP_SEX_AGE_RT", "can+usa+gbr+x01.a.une_deap_rt.sex_t.age_ythadult_yge15", last_n=3
    )
    # Codes are normalised to the API's case before the request.
    assert result.key == "CAN+USA+GBR+X01.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15"
    request = _data_requests(httpx_mock)[0]
    assert request.url.params["lastNObservations"] == "3"
    canada = next(s for s in result.series if s.ref_area == "CAN")
    assert canada.source == "LFS - Labour Force Survey"
    assert canada.unit == "Percentage" and canada.frequency == "Annual"
    rows = [r for r in result.rows if r.ref_area == "CAN"]
    assert [r.period for r in rows] == sorted(r.period for r in rows)
    assert any(r.period == "2025" and abs(r.value - 6.819) < 1e-9 for r in rows)
    usa = [r for r in result.rows if r.ref_area == "USA"]
    assert any(r.status == "Break in series" for r in usa)
    assert any("harmonises national survey figures" in n for n in result.notes)


async def test_get_data_in_french_reads_monthly_periods(httpx_mock):
    _mock(httpx_mock, csv_name="data_une_fr.csv", lang="fr")
    result = await client.get_data(
        "DF_UNE_DEAP_SEX_AGE_RT", "CAN.M.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15", last_n=3, lang="fr"
    )
    assert all(r.period.startswith("2026-M") for r in result.rows)
    assert result.series[0].frequency == "Mensuel"
    assert result.series[0].unit == "Pourcentage"
    assert result.citation.startswith("Organisation internationale du Travail")


async def test_unknown_area_fails_before_a_request(httpx_mock):
    # ILOSTAT answers an unknown area with HTTP 500 (ORA-00936).
    _mock(httpx_mock, csv_name=None)
    with pytest.raises(InvalidInput, match="ZZZ is not a REF_AREA code"):
        await client.get_data(
            "DF_UNE_DEAP_SEX_AGE_RT", "ZZZ.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15"
        )
    assert not _data_requests(httpx_mock)


async def test_short_key_is_explained(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    with pytest.raises(InvalidInput, match="5 parts in the order REF_AREA.FREQ.MEASURE.SEX.AGE"):
        await client.get_data("DF_UNE_DEAP_SEX_AGE_RT", "CAN.A")


async def test_open_key_without_periods_is_refused(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    with pytest.raises(InvalidInput, match="last_n or start_period"):
        await client.get_data("DF_UNE_DEAP_SEX_AGE_RT", "...SEX_T.")


async def test_no_data_404_is_not_found(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    httpx_mock.add_response(
        url=DATA,
        status_code=404,
        text="No data is found. Please adjust your query parameters and try again.",
    )
    with pytest.raises(NotFound, match="in the periods asked for"):
        await client.get_data(
            "DF_UNE_DEAP_SEX_AGE_RT",
            "CAN.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15",
            start_period="2040",
        )


async def test_server_error_is_an_upstream_error(httpx_mock):
    _mock(httpx_mock, csv_name=None)
    httpx_mock.add_response(url=DATA, status_code=500, text="ORA-00936: missing expression")
    with pytest.raises(UpstreamError, match="HTTP 500"):
        await client.get_data(
            "DF_UNE_DEAP_SEX_AGE_RT", "CAN.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15"
        )


async def test_bad_period_is_invalid():
    with pytest.raises(InvalidInput, match="SDMX period"):
        await client.get_data("DF_UNE_DEAP_SEX_AGE_RT", "CAN.A...", start_period="last year")


# --------------------------------------------------------------- comparison


async def test_compare_puts_canada_first_and_ranks_countries_only(httpx_mock):
    _mock(httpx_mock)
    result = await client.compare_countries(
        "unemployment_rate", compare_with=["US", "uk", "world", "XYZ"]
    )
    request = _data_requests(httpx_mock)[0]
    assert "/CAN+USA+GBR+X01.A.UNE_DEAP_RT.SEX_T.AGE_YTHADULT_YGE15" in str(request.url)
    assert request.url.params["lastNObservations"] == "10"
    assert [c.area_code for c in result.countries] == ["CAN", "USA", "GBR", "X01"]
    # X01 (World) is shown but not ranked; Canada's 6.8 is above the US and UK.
    assert result.canada_rank == 1 and result.ranked_countries == 3
    assert result.rank_period == "2025"
    assert any("XYZ" in n for n in result.notes)
    assert any("status" in n for n in result.notes)
    assert result.frequency == "annual" and result.sex == "total"


async def test_compare_checks_frequency_and_sex():
    with pytest.raises(InvalidInput, match="frequencies: annual"):
        await client.compare_countries("labour_income_share", frequency="monthly")
    with pytest.raises(InvalidInput, match="no breakdown by sex"):
        await client.compare_countries("minimum_wage_ppp", sex="female")
    with pytest.raises(InvalidInput, match="Unknown indicator"):
        await client.compare_countries("gdp")
    with pytest.raises(InvalidInput, match="not an ILOSTAT area code"):
        await client.compare_countries("unemployment_rate", compare_with=["United-States-of-A"])

"""Tests for oecd/client.py on responses recorded live on 2026-11-07
(fixtures/): the dataflow list (13 of its 1,552 flows, an archived stub, an
ESTAT flow and one that mentions third-party data among them), the Economic
Outlook and house-price structures (codelists and constraints cut to a few
codes) and SDMX-CSV data in English and French. The error statuses (404
NoRecordsFound, 413, 429) are the ones the API sent or documents."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.oecd import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

FIXTURES = Path(__file__).parent / "fixtures"

CATALOGUE = "https://sdmx.oecd.org/public/rest/dataflow/all"
EO_STRUCTURE = re.compile(
    r"https://sdmx\.oecd\.org/public/rest/dataflow/OECD\.ECO\.MAD/DSD_EO@DF_EO/latest\?.*"
)
HOUSE_STRUCTURE = re.compile(
    r"https://sdmx\.oecd\.org/public/rest/dataflow/OECD\.ECO\.MPD/"
    r"DSD_AN_HOUSE_PRICES@DF_HOUSE_PRICES/latest\?.*"
)
EO_DATA = re.compile(r"https://sdmx\.oecd\.org/public/rest/data/OECD\.ECO\.MAD,DSD_EO@DF_EO,/.*")


def _json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_state():
    cache_module._caches.clear()
    client.BUDGET.reset()
    yield
    client.BUDGET.reset()


def _mock_eo(httpx_mock, csv_name: str | None = "data_eo_en.csv"):
    httpx_mock.add_response(
        url=CATALOGUE, json=_json("dataflows.json"), is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=EO_STRUCTURE, json=_json("structure_eo.json"), is_optional=True, is_reusable=True
    )
    if csv_name:
        httpx_mock.add_response(url=EO_DATA, text=_text(csv_name))


def _data_requests(httpx_mock):
    return [r for r in httpx_mock.get_requests() if "/rest/data/" in str(r.url)]


# ------------------------------------------------------------------ search


async def test_search_ranks_name_matches_and_flags_archived(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_json("dataflows.json"))
    result = await client.search_datasets("economic outlook")
    ids = [d.id for d in result.datasets]
    assert ids[0] == "DSD_EO@DF_EO"
    assert "DSD_EO_114@DF_EO_114" in ids
    eo = result.datasets[0]
    # HTML and the hidden keyword block are gone from what a reader sees.
    assert "<div" not in eo.description and "visibility" not in eo.description
    assert eo.description.startswith("The OECD Economic Outlook presents")
    assert "df%5Bid%5D=DSD_EO%40DF_EO" in eo.explorer_url
    assert result.provenance.commercial_use == "allowed"
    assert "60 data downloads an hour" in (result.provenance.limits or "")

    productivity = await client.search_datasets("productivity levels")
    archived = next(d for d in productivity.datasets if d.id == "DSD_PDB@DF_PDB_LV")
    assert archived.archived
    # Search reads the cached list: one request for both searches.
    assert len(httpx_mock.get_requests()) == 1


async def test_search_needs_words_and_a_sane_limit(httpx_mock):
    with pytest.raises(InvalidInput, match="English words"):
        await client.search_datasets("the of")
    with pytest.raises(InvalidInput, match="anglais"):
        await client.search_datasets("  ", lang="fr")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_datasets("tax", limit=500)
    assert not httpx_mock.get_requests()


# --------------------------------------------------------------- structure


async def test_describe_reads_constraint_codes_and_dates(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    result = await client.describe_dataset("dsd_eo@df_eo")
    assert result.id == "DSD_EO@DF_EO" and result.agency == "OECD.ECO.MAD"
    assert result.key_template == "REF_AREA.MEASURE.FREQ"
    assert result.example_key == "CAN.."
    areas = {c.id for c in result.dimensions[0].codes}
    # MEX is in the codelist but not in the availability constraint.
    assert "CAN" in areas and "MEX" not in areas
    assert result.dimensions[0].name == "Reference area"
    assert result.last_updated == "2026-06-03T07:02:44+00:00"
    assert result.observation_count == 1_303_640
    assert result.first_period == "1960-01-01" and result.last_period == "2027-12-31"
    assert result.citation.startswith("OECD (2026), Economic Outlook 119, OECD Data Explorer")
    assert result.provenance.commercial_use == "allowed"
    assert "section 3 Data" in (result.provenance.licence or "")
    structure_request = httpx_mock.get_requests()[-1]
    assert structure_request.headers["Accept"] == constants.STRUCTURE_ACCEPT
    assert structure_request.headers["Accept-Language"] == "en"
    assert "references=all" in str(structure_request.url)


async def test_dataset_ids_with_agency_and_archived_stubs(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    result = await client.describe_dataset("OECD.ECO.MAD,DSD_EO@DF_EO")
    assert result.id == "DSD_EO@DF_EO"
    with pytest.raises(NotFound, match="not an OECD Data Explorer dataset"):
        await client.describe_dataset("OECD.SDD.TPS,DSD_EO@DF_EO")
    with pytest.raises(NotFound, match="archived"):
        await client.describe_dataset("DSD_PDB@DF_PDB_LV")
    with pytest.raises(InvalidInput):
        await client.describe_dataset("DSD_EO; drop")


async def test_third_party_and_other_owners_are_flagged(httpx_mock):
    httpx_mock.add_response(url=CATALOGUE, json=_json("dataflows.json"))
    catalogue, _ = await client._catalogue("en")
    pollution, use = client._licence(catalogue["DSD_FUA_ENV@DF_POLLUTION"], "en")
    assert pollution.startswith("Warning:") and "third-party data" in pollution
    assert use == "varies"
    estat, use = client._licence(catalogue["SEEA_AEA_A"], "fr")
    assert estat.startswith("Attention") and "ESTAT" in estat and use == "varies"
    eo, use = client._licence(catalogue["DSD_EO@DF_EO"], "en")
    assert eo == constants.LICENCE and use == "allowed"


# -------------------------------------------------------------------- data


async def test_get_data_returns_sorted_tidy_rows(httpx_mock):
    _mock_eo(httpx_mock)
    result = await client.get_data("DSD_EO@DF_EO", "can+USA+gbr.gdpv_annpct.A", start_period="2024")
    assert result.key == "CAN+USA+GBR.GDPV_ANNPCT.A"
    assert [s.key for s in result.series] == [
        "CAN.GDPV_ANNPCT.A",
        "GBR.GDPV_ANNPCT.A",
        "USA.GDPV_ANNPCT.A",
    ]
    canada = result.series[0]
    assert canada.ref_area_name == "Canada" and canada.frequency == "Annual"
    assert canada.unit == "Percent per annum" and canada.unit_multiplier == "Units"
    assert canada.base_period == "2017"
    assert canada.latest_period == "2027"
    assert canada.latest_value == pytest.approx(1.6865854732046)
    canada_rows = [r for r in result.rows if r.ref_area == "CAN"]
    assert [r.period for r in canada_rows] == ["2024", "2025", "2026", "2027"]
    assert canada_rows[0].unit == "Percent per annum" and canada_rows[0].frequency == "Annual"
    assert result.csv_url.endswith("startPeriod=2024&format=csvfilewithlabels")
    request = _data_requests(httpx_mock)[0]
    assert request.headers["Accept"] == constants.DATA_ACCEPT
    assert str(request.url).endswith("/CAN+USA+GBR.GDPV_ANNPCT.A?startPeriod=2024")


async def test_get_data_in_french_uses_french_labels(httpx_mock):
    _mock_eo(httpx_mock, "data_eo_fr.csv")
    result = await client.get_data("DSD_EO@DF_EO", "CAN+USA.GDPV_ANNPCT.A", last_n=4, lang="fr")
    canada = result.series[0]
    assert canada.ref_area_name == "Canada" and canada.frequency == "Annuelle"
    assert canada.unit == "Pourcentage par an"
    us = result.series[1]
    assert us.ref_area_name == "États-Unis"
    # "0: " has no French label; the code stands in.
    assert canada.unit_multiplier == "0"
    assert result.citation.startswith("OCDE (2026)")
    assert _data_requests(httpx_mock)[0].headers["Accept-Language"] == "fr"
    assert "lastNObservations=4" in str(_data_requests(httpx_mock)[0].url)


async def test_keys_are_checked_before_spending_a_download(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    with pytest.raises(InvalidInput, match="needs 3 parts"):
        await client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT")
    with pytest.raises(InvalidInput, match="ZZZ is not a REF_AREA code"):
        await client.get_data("DSD_EO@DF_EO", "CAN+ZZZ.GDPV_ANNPCT.A")
    with pytest.raises(InvalidInput, match="MEX is not a REF_AREA code"):
        await client.get_data("DSD_EO@DF_EO", "MEX.GDPV_ANNPCT.A")
    with pytest.raises(InvalidInput, match="SDMX period"):
        await client.get_data("DSD_EO@DF_EO", "CAN.UNR.A", start_period="last year")
    assert not _data_requests(httpx_mock)


async def test_wildcards_become_empty_parts(httpx_mock):
    _mock_eo(httpx_mock)
    result = await client.get_data("DSD_EO@DF_EO", "CAN+USA+GBR.*.A", last_n=4)
    assert result.key == "CAN+USA+GBR..A"
    assert "/CAN+USA+GBR..A?" in str(_data_requests(httpx_mock)[0].url)


async def test_no_records_is_not_found(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    httpx_mock.add_response(url=EO_DATA, status_code=404, text="NoRecordsFound")
    with pytest.raises(NotFound, match="in the periods asked for"):
        await client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT.A", start_period="2040")


async def test_last_n_refused_on_large_datasets(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    httpx_mock.add_response(url=EO_DATA, status_code=413, text="Request Entity Too Large")
    with pytest.raises(InvalidInput, match="start_period instead"):
        await client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT.A", last_n=3)


async def test_429_blocks_further_requests(httpx_mock):
    _mock_eo(httpx_mock, csv_name=None)
    httpx_mock.add_response(url=EO_DATA, status_code=429, headers={"Retry-After": "600"})
    with pytest.raises(UpstreamUnavailable, match="HTTP 429"):
        await client.get_data("DSD_EO@DF_EO", "CAN.GDPV_ANNPCT.A", start_period="2024")
    with pytest.raises(UpstreamUnavailable, match="about 10 minutes"):
        await client.get_data("DSD_EO@DF_EO", "USA.GDPV_ANNPCT.A", start_period="2024")
    assert len(_data_requests(httpx_mock)) == 1


async def test_hourly_budget_is_kept_and_cache_hits_are_free(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "DATA_BUDGET_PER_HOUR", 1)
    _mock_eo(httpx_mock)
    await client.get_data("DSD_EO@DF_EO", "CAN+USA+GBR.GDPV_ANNPCT.A", start_period="2024")
    again = await client.get_data("DSD_EO@DF_EO", "CAN+USA+GBR.GDPV_ANNPCT.A", start_period="2024")
    assert again.provenance.cached
    with pytest.raises(UpstreamUnavailable, match="sa part"):
        await client.get_data("DSD_EO@DF_EO", "CAN.UNR.A", start_period="2024", lang="fr")
    assert len(_data_requests(httpx_mock)) == 1


# -------------------------------------------------------------- comparison


async def test_compare_puts_canada_first_and_ranks(httpx_mock):
    _mock_eo(httpx_mock)
    result = await client.compare_countries("real_gdp_growth", ["GB", "us", "NZ", "OECD"])
    # NZL is not in the (cut) availability constraint, so it is not asked for.
    assert (
        str(_data_requests(httpx_mock)[0].url)
        .split("/")[-1]
        .startswith("CAN+GBR+USA+OECD.GDPV_ANNPCT.A?lastNObservations=8")
    )
    assert [c.area_code for c in result.countries] == ["CAN", "GBR", "USA"]
    assert result.countries[0].unit == "Percent per annum"
    assert result.rank_period == "2027" and result.ranked_countries == 3
    # 2027: USA 1.80, CAN 1.69, GBR below both in the recording.
    assert result.canada_rank == 2
    assert any("NZL" in n and "OECD" in n for n in result.notes)
    assert any("projections" in n for n in result.notes)
    assert result.dataset_name == "Economic Outlook 119"


async def test_compare_rejects_unknown_input(httpx_mock):
    with pytest.raises(InvalidInput, match="Indicators: real_gdp_growth"):
        await client.compare_countries("gdp")
    with pytest.raises(InvalidInput, match="not an OECD area code"):
        await client.compare_countries("real_gdp_growth", ["U.S."])
    assert not httpx_mock.get_requests()


def test_open_keys_are_bounded():
    dims = [{"id": "A", "codes": [[str(i), ""] for i in range(400)]}, {"id": "B", "codes": []}]
    assert client._max_series(".X", dims) == 400
    assert client._max_series("1+2.", dims) == 2
    with pytest.raises(InvalidInput, match="can match up to 400"):
        client._too_broad("DF", ".X", 400, "en")


def test_g7_alias_and_iso2_codes():
    assert client._areas(["G7", "AU", "uk"], "en") == list(constants.G7) + ["AUS"]


def test_every_indicator_key_has_one_area_slot():
    for name, spec in constants.INDICATORS.items():
        assert spec.key.split(".").count("{area}") == 1, name
        assert spec.label_fr and spec.default_last_n > 0, name

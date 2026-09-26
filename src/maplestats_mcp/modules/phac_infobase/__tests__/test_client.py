"""Tests on rows trimmed from live Health Infobase files (2026-09-26).

Each fixture reproduces a quirk seen live: suppressed cells ("Suppr.",
"X", "n/a", "n.d."), UTF-8 files with and without a BOM, Windows-1252
French files with decimal commas, the DOS code page 850 congenital
anomalies file, R row-number columns with an empty header, a ZIP member
with accents in its name, JSON nulls from the API, and missing files
that answer 302 to /404.html instead of 404.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import httpx
import pytest

from maplestats_mcp.modules.phac_infobase import client, constants
from maplestats_mcp.modules.phac_infobase.catalogue import BY_ID, DATASETS, TOPICS
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

_LM = "Tue, 22 Sep 2026 13:25:27 GMT"
_HARMS_EN = BY_ID["opioid_stimulant_harms"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _url(path: str) -> str:
    return path if path.startswith("https://") else constants.BASE_URL + path


def _zip(name: str, body: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.txt", "Data on opioid- and stimulant-related harms")
        archive.writestr(name, body)
    return buffer.getvalue()


_HARMS_CSV = (
    "Substance,Source,Specific_Measure,Region,PRUID,Time_Period,Year_Quarter,"
    "Aggregator,Disaggregator,Unit,Value\n"
    "Opioids,Deaths,Overall numbers,Canada,1,By year,2022,,,Number,7525\n"
    "Opioids,Deaths,Overall numbers,Canada,1,By year,2023,,,Number,8083\n"
    "Opioids,Deaths,Overall numbers,Canada,1,By quarter,2026 Q1,,,Number,1180\n"
    "Opioids,Deaths,Overall numbers,Canada,1,By year,2026 (Jan to Mar),,,Number,1180\n"
    "Opioids,Deaths,Overall numbers,Nunavut,62,By year,2023,,,Number,Suppr.\n"
    "Opioids,Deaths,Overall numbers,Ontario,35,By year,2023,,,Number,2567\n"
    "Stimulants,Emergency Medical Services (EMS),Sex,Ontario,35,By year,2016,,Male,Number,n/a\n"
)


def _mock_harms(httpx_mock) -> None:
    httpx_mock.add_response(
        url=_url(_HARMS_EN.url_en),
        content=_zip("SubstanceHarmsData.csv", _HARMS_CSV.encode()),
        headers={"Last-Modified": _LM},
    )


async def test_harms_zip_filters_dates_geography_and_markers(httpx_mock):
    _mock_harms(httpx_mock)
    result = await client.query(
        "opioid_stimulant_harms",
        filters={"source": "deaths", "Unit": "Number", "Time_Period": "By year"},
        start="2023",
        end="2023",
    )
    assert result.geo_column == "Region" and result.date_column == "Year_Quarter"
    assert [r["Region"] for r in result.rows] == ["Canada", "Nunavut", "Ontario"]
    assert result.markers[0].value == "Suppr." and "suppressed" in result.markers[0].meaning
    assert result.provenance.as_of is not None and result.provenance.as_of.year == 2026
    assert result.total_rows == 7

    # "ON" resolves to Ontario; the cached file is reused.
    ontario = await client.query("opioid_stimulant_harms", geography="ON", columns=["value"])
    assert ontario.columns == ["Value"] and [r["Value"] for r in ontario.rows] == ["n/a", "2567"]
    assert ontario.provenance.cached

    # "2026 Q1" and "2026 (Jan to Mar)" both start in 2026; oldest first, most recent kept.
    recent = await client.query("opioid_stimulant_harms", geography="Canada", limit=2)
    assert [r["Year_Quarter"] for r in recent.rows] == ["2026 Q1", "2026 (Jan to Mar)"]
    assert recent.matching_rows == 4


async def test_french_zip_member_with_accents_in_cp1252(httpx_mock):
    body = (
        "Substance,Source,Mesure_Spéficique,Région,PRUID,Période_Temps,Année_Trimestre,"
        "Aggrégateur,Désaggrégateur,Unité,Valeur\n"
        "Opioïdes,Mortalité,Nombres totaux,Québec,24,Par année,2023,,,Nombre,n.d.\n"
        "Opioïdes,Mortalité,Nombres totaux,Canada,1,Par année,2023,,,Taux brut,21.2\n"
    ).encode("cp1252")
    httpx_mock.add_response(
        url=_url(_HARMS_EN.url_fr or ""), content=_zip("DonnéesMéfaitsSubstances.csv", body)
    )
    result = await client.query("opioid_stimulant_harms", geography="Quebec", lang="fr")
    assert result.geo_column == "Région" and result.date_column == "Année_Trimestre"
    assert result.rows[0]["Valeur"] == "n.d."
    assert result.markers[0].meaning == "non disponible"
    assert result.title.startswith("Décès")


async def test_describe_reports_columns_coverage_and_markers(httpx_mock):
    _mock_harms(httpx_mock)
    described = await client.describe_dataset("opioid_stimulant_harms")
    assert described.row_count == 7 and described.encoding == "utf-8"
    assert described.date_start == "2016-01-01" and described.date_end == "2026-01-01"
    assert described.geo_values == ["Canada", "Nunavut", "Ontario"]
    assert described.last_modified == _LM
    value = next(c for c in described.columns if c.name == "Value")
    assert value.numeric  # markers do not make a numeric column non-numeric
    assert {m.value for m in described.markers} == {"Suppr.", "n/a"}
    source = next(c for c in described.columns if c.name == "Source")
    assert source.sample_values[0] == "Deaths"
    assert not described.decimal_comma


async def test_french_decimal_comma_windows_1252(httpx_mock):
    entry = BY_ID["ccdi_indicators_2018"]
    # Comma decimals are quoted, as in the live file.
    body = (
        "Domaine,Groupe d'indicateur,Mesure,Données les plus récentes [a],L'élément,"
        "Intervalle de confiance inférieur de 95%,Intervalle de confiance supérieur à 95%,"
        "Source de données\xa0,,,,\n"
        'Déterminants sociaux,Éducation,% de la population,"12,2",%,"11,8","12,7",'
        "ESCC 2016,,,,\n"
        ",,[l] Ces chiffres sont des projections,,,,,,,,,\n"
    )
    httpx_mock.add_response(url=_url(entry.url_fr or ""), content=body.encode("cp1252"))
    described = await client.describe_dataset("ccdi_indicators_2018", lang="fr")
    assert described.encoding == "cp1252" and described.decimal_comma
    # Trailing empty-header columns are dropped; the header's NBSP is stripped.
    assert [c.name for c in described.columns][-1] == "Source de données"
    assert len(described.columns) == 8 and described.file_language == "fr"


async def test_code_page_850_french_file(httpx_mock):
    entry = BY_ID["congenital_anomalies"]
    body = (
        "Condition,ICD10,Year,Number,Rate,Lower 95% CI,Upper 95% Ci,Population,Scale,Source\n"
        'Anomalies du tube neural,"Q00, Q01 (un nouveau-né ne sera compté qu\'une fois)",'
        "2005,137,5.08,4.26,6,Naissances vivantes,Taux par 10\xa0000 naissances (IC à 95\xa0%),"
        "ICIS\n"
    ).encode("cp850")
    httpx_mock.add_response(url=_url(entry.url_fr or ""), content=body)
    result = await client.query("congenital_anomalies", lang="fr")
    assert "nouveau-né" in result.rows[0]["ICD10"]
    assert "IC à 95" in result.rows[0]["Scale"]


async def test_bom_and_r_row_number_column(httpx_mock):
    entry = BY_ID["tuberculosis_incidence_by_province"]
    body = (
        '﻿"","surveillance_year","province_territory","incidence","cases"\n'
        '"1",2015,"AB",5.1,210\n"2",2016,"AB",5.7,238\n"3",2024,"NU",87.5,36\n'
        '"4",2024,"Canada",6.1,2507\n\n'
    ).encode()
    httpx_mock.add_response(url=_url(entry.url_en), content=body)
    result = await client.query("tuberculosis_incidence_by_province", geography="Nunavut")
    assert result.columns == ["surveillance_year", "province_territory", "incidence", "cases"]
    assert result.rows == [
        {
            "surveillance_year": "2024",
            "province_territory": "NU",
            "incidence": "87.5",
            "cases": "36",
        }
    ]
    canada = await client.query("tuberculosis_incidence_by_province", geography="CAN")
    assert canada.returned_count == 1


async def test_pruid_geography_column(httpx_mock):
    entry = BY_ID["wastewater_daily"]
    body = (
        "Date,Location,region,measureid,fractionid,viral_load,seven_day_rolling_avg,pruid\n"
        "2026-07-11,Montreal South,Montreal,covN2,solid,0.36,0.18,24\n"
        "2026-07-15,Montreal South,Montreal,covN2,solid,1.28,0.82,24\n"
        "2026-07-12,Winnipeg West End,Winnipeg,covN2,solid,2.95,2.95,46\n"
    )
    httpx_mock.add_response(url=_url(entry.url_en), text=body)
    result = await client.query("wastewater_daily", geography="Québec", start="2026-07-12")
    assert [r["Date"] for r in result.rows] == ["2026-07-15"]
    by_code = await client.query("wastewater_daily", geography="46")
    assert by_code.rows[0]["Location"] == "Winnipeg West End"


async def test_api_table_nulls_and_updated_at(httpx_mock):
    entry = BY_ID["cnisp_vri_incidence"]
    httpx_mock.add_response(
        url=_url(entry.url_en),
        json=[
            {"Week": "2020-03-15", "virus": "COVID-19", "age_group": "Adult", "rate": "5.3"},
            {"Week": "2020-03-15", "virus": "RSV", "age_group": "Adult", "rate": None},
            {"Week": "2026-09-06", "virus": "RSV", "age_group": "Pediatric", "rate": 2.45},
        ],
    )
    httpx_mock.add_response(
        url=constants.API_URL + "/cnisp-vri",
        json={"tables": ["vri_rates"], "updatedAt": "2026-09-18T17:45:33Z"},
    )
    described = await client.describe_dataset("cnisp_vri_incidence")
    assert described.encoding == "json" and described.last_modified == "2026-09-18T17:45:33Z"
    rate = next(c for c in described.columns if c.name == "rate")
    assert rate.empty_cells == 1 and rate.numeric
    assert described.provenance.as_of is not None and described.provenance.as_of.day == 18
    result = await client.query("cnisp_vri_incidence", filters={"virus": "rsv"})
    assert [r["rate"] for r in result.rows] == ["", "2.45"]


async def test_missing_file_redirects_to_404_page(httpx_mock):
    entry = BY_ID["measles_cases_by_province"]
    httpx_mock.add_response(
        url=_url(entry.url_en),
        status_code=302,
        headers={"Location": "https://health-infobase.canada.ca/404.html"},
    )
    with pytest.raises(NotFound):
        await client.describe_dataset("measles_cases_by_province")


async def test_html_page_and_bad_zip(httpx_mock):
    httpx_mock.add_response(
        url=_url(BY_ID["measles_outbreaks"].url_en), html="<!DOCTYPE html><html></html>"
    )
    with pytest.raises(NotFound):
        await client.describe_dataset("measles_outbreaks")
    httpx_mock.add_response(url=_url(BY_ID["mpox_cases_by_age_gender"].url_en), content=b"PK\x00")
    with pytest.raises(UpstreamError):
        await client.describe_dataset("mpox_cases_by_age_gender")


async def test_zip_without_matching_member(httpx_mock):
    httpx_mock.add_response(
        url=_url(BY_ID["mpox_cases_by_age_gender"].url_en),
        content=_zip("mpox_key_updates.csv", b"a,b\n1,2\n"),
    )
    with pytest.raises(UpstreamError, match="mpox_demographics"):
        await client.describe_dataset("mpox_cases_by_age_gender")


async def test_upstream_failures(httpx_mock):
    url = _url(BY_ID["fluwatch_outbreaks"].url_en)
    httpx_mock.add_response(url=url, status_code=503, is_reusable=True)
    with pytest.raises(UpstreamError):
        await client.describe_dataset("fluwatch_outbreaks")
    httpx_mock.reset()
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), url=url, is_reusable=True)
    with pytest.raises(UpstreamUnavailable):
        await client.describe_dataset("fluwatch_outbreaks")


async def test_invalid_arguments(httpx_mock):
    with pytest.raises(NotFound):
        await client.query("no_such_dataset")
    with pytest.raises(InvalidInput):
        await client.query("measles_cases_by_province", limit=0)
    with pytest.raises(InvalidInput):
        await client.query("rvdss_weekly_detections", start="last week")
    with pytest.raises(InvalidInput):
        await client.query("rvdss_weekly_detections", start="2024-02-31")
    with pytest.raises(InvalidInput):
        await client.query("rvdss_weekly_detections", start="2025", end="2024")
    entry = BY_ID["measles_cases_by_province"]
    httpx_mock.add_response(
        url=_url(entry.url_en),
        text="pruid,pt_name,num_new_cases,num_cases,last_onset_epi_week\n48,Alberta,0,311,22\n",
    )
    with pytest.raises(InvalidInput, match="no date column"):
        await client.query("measles_cases_by_province", start="2024")
    with pytest.raises(InvalidInput, match="Unknown column"):
        await client.query("measles_cases_by_province", filters={"province": "Alberta"})
    ok = await client.query("measles_cases_by_province", geography="alta")
    assert ok.rows[0]["num_cases"] == "311"
    measles_weekly = BY_ID["measles_weekly_by_province"]
    httpx_mock.add_response(
        url=_url(measles_weekly.url_en),
        text="Epidemiological week of rash onset,48: Alberta,01: Canada\n1,24,45\nTOTAL,311,1120\n",
    )
    with pytest.raises(InvalidInput, match="no geography column"):
        await client.query("measles_weekly_by_province", geography="Alberta")


def test_list_datasets_topics_and_french_query():
    everything = client.list_datasets()
    assert everything.total_count == len(DATASETS)
    assert {t.key for t in everything.topics} == set(TOPICS)
    fr = client.list_datasets(query="rougeole", lang="fr")
    assert fr.datasets and all(d.topic == "infectious_disease" for d in fr.datasets)
    assert fr.datasets[0].topic_label.startswith("Rougeole")
    accentless = client.list_datasets(query="opioides stimulants")
    assert any(d.id == "opioid_stimulant_harms" for d in accentless.datasets)
    harms = next(d for d in accentless.datasets if d.id == "opioid_stimulant_harms")
    assert harms.languages == ["en", "fr"] and not harms.archived
    covid = client.list_datasets(topic="covid19")
    assert covid.datasets and all(d.archived for d in covid.datasets)
    with pytest.raises(InvalidInput):
        client.list_datasets(topic="nutrition")


def test_catalogue_is_consistent():
    assert len(BY_ID) == len(DATASETS), "duplicate dataset ids"
    for entry in DATASETS:
        assert entry.topic in TOPICS, entry.id
        assert entry.frequency in constants.FREQUENCIES, entry.id
        for url in (entry.url_en, entry.url_fr):
            if url and url.startswith("https://"):
                assert url.split("/")[2] in constants.ALLOWED_HOSTS, entry.id
        assert (entry.kind == "zip") == bool(entry.member_en), entry.id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-08-30", date(2025, 8, 30)),
        ("2026-09-04 13:32:50", date(2026, 9, 4)),
        ("2026 Q1", date(2026, 1, 1)),
        ("2025 Q4", date(2025, 10, 1)),
        ("2026 (Jan to Mar)", date(2026, 1, 1)),
        ("2024-10", date(2024, 10, 1)),
        ("2024-2025", date(2024, 1, 1)),
        ("2024-25", date(2024, 1, 1)),
        ("2015-2018", date(2015, 1, 1)),
        ("30-08-2025", date(2025, 8, 30)),
        ("2016", date(2016, 1, 1)),
        ("All", None),
        ("max_cases", None),
        ("", None),
        ("202535", None),
    ],
)
def test_parse_period(value, expected):
    assert client.parse_period(value) == expected


def test_geo_matcher():
    quebec = client.geo_matcher("QC")
    assert quebec("Québec") and quebec("Quebec") and quebec("24") and not quebec("Ontario")
    pei = client.geo_matcher("Île-du-Prince-Édouard")
    assert pei("PE") and pei("Prince Edward Island") and pei("PEI")
    nwt = client.geo_matcher("T.N.-O.")
    assert nwt("NT") and nwt("Northwest Territories")
    city = client.geo_matcher("winnipeg")
    assert city("Winnipeg, Manitoba") and not city("Manitoba")

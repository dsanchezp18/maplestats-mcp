"""Tests for eurostat/client.py against responses recorded live on 2026-11-07.

fixtures/: the table of contents cut to the folders holding a few datasets
(English and French), two SDMX 2.1 structures with annotations and German
names stripped, two JSON-stat answers, the 404 SOAP fault for an unknown
dataset and the 413 for a request over 5 million cells. Quirks covered:
unknown geo codes dropped silently (US in namq_10_gdp), flags labelled in the
answer's language, discontinued datasets (prc_hicp_manr) ranked below their
replacement, and codes checked before Eurostat would ignore them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from maplestats_mcp.modules.eurostat import client
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
TOC = re.compile(
    r"https://ec\.europa\.eu/eurostat/api/dissemination/catalogue/toc/txt\?lang=(en|fr)"
)
STRUCTURE = re.compile(
    r"https://ec\.europa\.eu/eurostat/api/dissemination/sdmx/2\.1/dataflow/ESTAT/(\w+)/latest\?.*"
)
DATA = re.compile(
    r"https://ec\.europa\.eu/eurostat/api/dissemination/statistics/1\.0/data/(\w+)\?.*"
)


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _toc(httpx_mock) -> None:
    for lang in ("en", "fr"):
        httpx_mock.add_response(
            url=re.compile(TOC.pattern.replace("(en|fr)", lang)),
            content=_read(f"toc_{lang}.txt"),
            is_optional=True,
            is_reusable=True,
        )


def _structure(httpx_mock, code: str) -> None:
    httpx_mock.add_response(
        url=re.compile(STRUCTURE.pattern.replace(r"(\w+)", code.upper())),
        content=_read(f"structure_{code}.xml"),
        headers={"content-type": "application/vnd.sdmx.structure+xml;version=2.1"},
        is_reusable=True,
    )


def _data_requests(httpx_mock) -> list:
    return [r for r in httpx_mock.get_requests() if "/statistics/" in str(r.url)]


async def test_search_ranks_current_dataset_above_discontinued(httpx_mock):
    _toc(httpx_mock)
    result = await client.search_datasets("harmonised index consumer prices monthly")
    codes = [d.code for d in result.datasets]
    assert codes.index("prc_hicp_minr") < codes.index("prc_hicp_manr")
    minr = next(d for d in result.datasets if d.code == "prc_hicp_minr")
    assert minr.type == "dataset" and minr.data_end and minr.last_update
    assert "Economy and finance" in minr.theme or "Prices" in minr.theme


async def test_search_matches_english_words_in_french_list(httpx_mock):
    _toc(httpx_mock)
    result = await client.search_datasets("unemployment monthly", lang="fr")
    assert "une_rt_m" in [d.code for d in result.datasets]
    hit = next(d for d in result.datasets if d.code == "une_rt_m")
    assert "chômage" in hit.title.lower()


async def test_search_by_code_first(httpx_mock):
    _toc(httpx_mock)
    result = await client.search_datasets("teina225")
    assert result.datasets[0].code == "teina225"
    assert result.datasets[0].type == "table"


async def test_search_rejects_empty_query():
    with pytest.raises(InvalidInput):
        await client.search_datasets("of the")


async def test_describe_lists_codes_with_data_and_flags(httpx_mock):
    _toc(httpx_mock)
    _structure(httpx_mock, "namq_10_gdp")
    result = await client.describe_dataset("namq_10_gdp", lang="fr")
    dims = {d.id: d for d in result.dimensions}
    assert list(dims) == ["freq", "unit", "s_adj", "na_item", "geo"]
    geo = {c.id: c.label for c in dims["geo"].codes}
    assert geo["DE"] == "Allemagne" and "EA21" in geo
    assert "US" not in geo
    assert result.example_filters["geo"] == ["EU27_2020"]
    flags = {f.flag: f.label for f in result.flags}
    assert flags["p"] == "provisoire" and flags["b"] == "rupture de série"
    assert result.data_end and result.provenance.licence


async def test_describe_unknown_dataset(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(STRUCTURE.pattern.replace(r"(\w+)", "NOPE_X")),
        status_code=404,
        content=_read("structure_not_found.xml"),
    )
    with pytest.raises(NotFound, match="not available for dissemination"):
        await client.describe_dataset("nope_x")


async def test_get_data_tidy_rows_and_missing_geo(httpx_mock):
    _structure(httpx_mock, "namq_10_gdp")
    httpx_mock.add_response(url=DATA, content=_read("data_namq_10_gdp.json"))
    result = await client.get_data(
        "namq_10_gdp",
        {"unit": ["clv_pch_pre"], "s_adj": "SCA", "na_item": ["B1GQ"]},
        geo=["EU27", "euro area", "Germany", "US"],
        last_n=3,
    )
    request = _data_requests(httpx_mock)[0]
    params = request.url.params
    assert params.get_list("geo") == ["EU27_2020", "EA21", "DE", "US"]
    assert params["unit"] == "CLV_PCH_PRE" and params["lastTimePeriod"] == "3"
    assert result.missing_geo == ["US"]
    assert set(result.fixed) == {"freq", "s_adj", "na_item"}
    assert {r.geo for r in result.rows} == {"EU27_2020", "EA21", "DE"}
    first = result.rows[0]
    assert first.unit == "CLV_PCH_PRE" and first.value is not None
    flagged = [r for r in result.rows if r.flag]
    assert flagged and all(r.flag_label == "provisional" for r in flagged if r.flag == "p")
    # The US is asked for but absent, so no commercial-use restriction applies.
    assert result.provenance.commercial_use == "varies"


async def test_get_data_french_labels_and_two_units(httpx_mock):
    _structure(httpx_mock, "teina225")
    httpx_mock.add_response(url=DATA, content=_read("data_teina225_fr.json"))
    result = await client.get_data("teina225", geo=["FR", "Allemagne"], last_n=2, lang="fr")
    assert _data_requests(httpx_mock)[0].url.params["lang"] == "FR"
    units = {r.unit for r in result.rows}
    assert units == {"PC_GDP", "MIO_EUR"}
    assert {r.geo_label for r in result.rows} == {"France", "Allemagne"}


async def test_get_data_default_period_note(httpx_mock):
    _structure(httpx_mock, "teina225")
    httpx_mock.add_response(url=DATA, content=_read("data_teina225_fr.json"))
    result = await client.get_data("teina225", geo=["FR", "DE"])
    assert _data_requests(httpx_mock)[0].url.params["lastTimePeriod"] == "12"
    assert any("last 12 periods" in n for n in result.notes)


async def test_get_data_unknown_code_refused_before_request(httpx_mock):
    _structure(httpx_mock, "namq_10_gdp")
    with pytest.raises(InvalidInput, match="not a code of unit"):
        await client.get_data("namq_10_gdp", {"unit": ["NOPE"]}, last_n=1)
    with pytest.raises(InvalidInput, match="no dimension"):
        await client.get_data("namq_10_gdp", {"sector": ["S13"]}, last_n=1)
    with pytest.raises(InvalidInput, match="not a geo code"):
        await client.get_data("namq_10_gdp", geo=["Atlantis"], last_n=1)
    assert not _data_requests(httpx_mock)


async def test_get_data_too_many_series_refused(httpx_mock):
    _structure(httpx_mock, "namq_10_gdp")
    with pytest.raises(InvalidInput, match="series"):
        await client.get_data("namq_10_gdp", last_n=1)
    assert not _data_requests(httpx_mock)


async def test_get_data_last_n_with_period_refused():
    with pytest.raises(InvalidInput, match="not both"):
        await client.get_data("teina225", start_period="2020", last_n=2)


async def test_get_data_413_becomes_invalid_input(httpx_mock):
    _structure(httpx_mock, "teina225")
    httpx_mock.add_response(url=DATA, status_code=413, content=_read("data_too_big.json"))
    with pytest.raises(InvalidInput, match="EXTRACTION_TOO_BIG"):
        await client.get_data("teina225", geo=["FR"], last_n=1)


async def test_get_data_empty_answer_is_not_found(httpx_mock):
    _structure(httpx_mock, "teina225")
    httpx_mock.add_response(
        url=DATA,
        json={
            "version": "2.0",
            "label": "x",
            "id": ["geo", "time"],
            "size": [1, 0],
            "dimension": {
                "geo": {"category": {"index": {"FR": 0}, "label": {"FR": "France"}}},
                "time": {"category": {"index": {}, "label": {}}},
            },
            "value": {},
        },
    )
    with pytest.raises(NotFound):
        await client.get_data("teina225", geo=["FR"], start_period="2035")


async def test_asynchronous_warning_is_unavailable(httpx_mock):
    _structure(httpx_mock, "teina225")
    httpx_mock.add_response(
        url=DATA, json={"warning": {"status": 413, "label": "ASYNCHRONOUS_RESPONSE. id"}}
    )
    with pytest.raises(UpstreamUnavailable, match="asynchronous"):
        await client.get_data("teina225", geo=["FR"], last_n=1)


async def test_compare_marks_non_eu_data_not_commercial(httpx_mock):
    _structure(httpx_mock, "namq_10_gdp")
    httpx_mock.add_response(url=DATA, content=_read("data_namq_10_gdp.json"))
    result = await client.compare("gdp_growth_quarterly", geo=["EU27", "EURO_AREA", "DE", "US"])
    assert [s.geo for s in result.series] == ["EU27_2020", "EA21", "DE"]
    assert result.missing_geo == ["US"]
    assert "36-10-0104-01" in result.canada_counterpart
    assert result.filters["na_item"] == "B1GQ"
    de = result.series[-1]
    assert de.latest_value is not None and de.latest_time
    assert de.observations[0].time < de.latest_time


def test_jsonstat_flat_index_and_flags():
    payload = {
        "id": ["unit", "geo", "time"],
        "size": [1, 2, 2],
        "dimension": {
            "unit": {"category": {"index": {"PC": 0}, "label": {"PC": "Percent"}}},
            "geo": {
                "category": {"index": ["FR", "DE"], "label": {"FR": "France", "DE": "Germany"}}
            },
            "time": {"category": {"index": {"2024": 0, "2025": 1}}},
        },
        "value": {"0": 1.5, "3": 2.5},
        "status": {"1": "c", "3": "bep"},
        "extension": {"status": {"label": {"bep": "break, estimated, provisional"}}},
    }
    parsed = client._parse_jsonstat(payload)
    cells = [(c["geo"], c["time"], v, f) for c, v, f in parsed["cells"]]
    assert cells == [
        ("FR", "2024", 1.5, None),
        ("FR", "2025", None, "c"),
        ("DE", "2025", 2.5, "bep"),
    ]
    assert client._flag_label("bep", "en", parsed["flag_labels"]) == "break, estimated, provisional"
    assert client._flag_label("ep", "fr") == "estimé, provisoire"

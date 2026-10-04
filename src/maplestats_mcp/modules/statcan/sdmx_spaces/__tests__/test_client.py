"""Tests for the extra StatCan SDMX spaces client.

Fixtures are shaped like what api.statcan.gc.ca and sdmx-sfs.statcan.gc.ca
really answered on 2026-10-02 (a structure fetched with references=all for
CCEI:GHG_IPCC_TABLE 2.0, the dataflow list, SDMX-CSV 2.0 data, the plain-text
404/422/400 bodies and the search service's response), including the quirks:
an empty body, a body cut off mid-row, a semicolon-delimited CSV, a key with
more segments than the flow has dimensions, and the NonProductionDataflow
annotation on every flow.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.statcan.sdmx_spaces import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import (
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)

CCEI = constants.SPACES["ccei"].base_url
SHARED = constants.SPACES["stcshared"].base_url
LIST_URL = f"{CCEI}/dataflow/all/all/latest"
STRUCT_URL = f"{CCEI}/dataflow/CCEI/GHG_IPCC_TABLE/latest?references=all"
DATA_BASE = f"{CCEI}/data/CCEI,GHG_IPCC_TABLE,2.0"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield
    cache_module._caches.clear()


def _flow(agency: str, flow_id: str, version: str, name: str, description: str = "") -> dict:
    item: dict[str, Any] = {
        "id": flow_id,
        "version": version,
        "agencyID": agency,
        "isFinal": True,
        "name": name,
        "names": {"en": name},
        "annotations": [{"type": "NonProductionDataflow", "text": "true", "texts": {"en": "true"}}],
        "structure": f"urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure={agency}:{flow_id}(1.6)",
    }
    if description:
        item["description"] = description
    return item


LIST_PAYLOAD = {
    "data": {
        "dataflows": [
            _flow(
                "CCEI",
                "GHG_IPCC_TABLE",
                "2.0",
                "Greenhouse gas emissions based on the IPCC 2006 guidelines",
                "<p>Contains GHG files by IPCC sector.</p>\n<p><strong>Release date:</strong> "
                "2026-04-14</p><p><strong>Source:</strong> Environment and Climate Change "
                'Canada - <a href="https://data.ec.gc.ca/">Inventory</a></p>',
            ),
            _flow("CCEI", "DF_NRCAN_EE", "1.0", "Energy efficiency indicators"),
            _flow(
                "STC", "DF_38100097", "1.0", "Physical flow account for greenhouse gas emissions"
            ),
            _flow("CA1.CCEI", "DF_11100222", "2.0", "Household spending, Canada"),
            _flow("CA1", "DF_RURAL_12100138_SWITCH", "1.0", "Commerce des biens"),
            _flow("CA1.RURAL", "DF_RURAL_12100138", "1.0", "Trade in goods by exporter"),
        ]
    }
}


def _codes(*triples: tuple[str, str, str | None]) -> list[dict]:
    out = []
    for code_id, name, parent in triples:
        item: dict[str, Any] = {"id": code_id, "name": name, "names": {"en": name}}
        if parent:
            item["parent"] = parent
        out.append(item)
    return out


def _dimension(dim_id: str, position: int, codelist: str) -> dict:
    return {
        "id": dim_id,
        "position": position,
        "type": "Dimension",
        "conceptIdentity": f"urn:sdmx:org.sdmx.infomodel.conceptscheme.Concept=CCEI:CS_GHG(1.2).{dim_id}",
        "localRepresentation": {
            "enumeration": f"urn:sdmx:org.sdmx.infomodel.codelist.Codelist={codelist}"
        },
    }


STRUCTURE_PAYLOAD = {
    "data": {
        "dataflows": [
            {
                **_flow("CCEI", "GHG_IPCC_TABLE", "2.0", "Greenhouse gas emissions (IPCC)"),
                "structure": "urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure=CCEI:GHG_IPCC_TABLE(1.6)",
            }
        ],
        "dataStructures": [
            {
                "id": "GHG_IPCC_TABLE",
                "version": "1.6",
                "agencyID": "CCEI",
                "dataStructureComponents": {
                    "attributeList": {"attributes": [{"id": "UNIT_MEASURE"}, {"id": "OBS_STATUS"}]},
                    "dimensionList": {
                        "dimensions": [
                            _dimension("FREQ", 0, "STC:CL_FREQ(1.3)"),
                            _dimension("REF_AREA", 1, "STC:CL_AREA(1.6)"),
                            _dimension("IPCC_CATEGORY", 2, "CCEI:CL_IPCC(2.0)"),
                        ],
                        "timeDimensions": [{"id": "TIME_PERIOD", "position": 3}],
                    },
                },
            }
        ],
        "conceptSchemes": [
            {
                "id": "CS_GHG",
                "version": "1.2",
                "agencyID": "CCEI",
                "concepts": [
                    {"id": "FREQ", "name": "Frequency"},
                    {"id": "REF_AREA", "name": "Geography"},
                    {"id": "IPCC_CATEGORY", "name": "Sector category"},
                ],
            }
        ],
        "codelists": [
            {
                "id": "CL_FREQ",
                "version": "1.3",
                "agencyID": "STC",
                "codes": _codes(("A", "Annual", None), ("M", "Monthly", None)),
            },
            {
                "id": "CL_AREA",
                "version": "1.6",
                "agencyID": "STC",
                "codes": _codes(
                    ("CA", "Canada", None),
                    ("CA_AB", "Alberta", "CA"),
                    ("CA_BC", "British Columbia", "CA"),
                    ("CA_YT", "Yukon", "CA"),
                ),
            },
            {
                "id": "CL_IPCC",
                "version": "2.0",
                "agencyID": "CCEI",
                "codes": _codes(("0", "Total", None), ("100", "ENERGY", "0")),
            },
        ],
        "contentConstraints": [
            {
                "id": "CR_A_GHG_IPCC_TABLE",
                "type": "Actual",
                "validFrom": "2026-04-21T19:53:10Z",
                "annotations": [{"id": "obs_count", "title": "451360", "type": "sdmx_metrics"}],
                "constraintAttachment": {
                    "dataflows": [
                        "urn:sdmx:org.sdmx.infomodel.datastructure.Dataflow=CCEI:GHG_IPCC_TABLE(2.0)"
                    ]
                },
                "cubeRegions": [
                    {
                        "isIncluded": True,
                        "keyValues": [
                            {"id": "FREQ", "values": ["A"]},
                            {"id": "REF_AREA", "values": ["CA", "CA_AB", "CA_BC"]},
                            {"id": "IPCC_CATEGORY", "values": ["0", "100"]},
                            {
                                "id": "TIME_PERIOD",
                                "timeRange": {
                                    "startPeriod": {"period": "1990-01-01T00:00:00"},
                                    "endPeriod": {"period": "2024-12-31T00:00:00"},
                                },
                            },
                        ],
                    }
                ],
            }
        ],
    }
}

CSV_HEADER = (
    "STRUCTURE,STRUCTURE_ID,ACTION,FREQ,REF_AREA,IPCC_CATEGORY,TIME_PERIOD,OBS_VALUE,"
    "UNIT_MEASURE,OBS_STATUS"
)


def _csv(*rows: str, header: str = CSV_HEADER, newline: bool = True) -> str:
    return "\n".join([header, *rows]) + ("\n" if newline else "")


def _row(area: str, period: str, value: str, status: str = "A", category: str = "0") -> str:
    return f"DATAFLOW,CCEI:GHG_IPCC_TABLE(2.0),I,A,{area},{category},{period},{value},KT,{status}"


def _mock_structure(httpx_mock, payload=None):
    httpx_mock.add_response(url=STRUCT_URL, json=payload or STRUCTURE_PAYLOAD)


# ----------------------------------------------------------------- list


async def test_list_flows_counts_agencies_and_strips_html(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    result = await client.list_flows("ccei")
    assert result.total_flows == result.matched == 6
    assert result.agencies == {"CA1": 1, "CA1.CCEI": 1, "CA1.RURAL": 1, "CCEI": 2, "STC": 1}
    assert result.non_production_flows == 6
    first = result.flows[0]
    assert first.flow == "CCEI,GHG_IPCC_TABLE,2.0"
    assert "<p>" not in first.description
    assert "Release date: 2026-04-14" in first.description
    assert "NonProductionDataflow" in (result.provenance.coverage or "")


async def test_list_flows_filters_by_words_and_agency(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    greenhouse = await client.list_flows("ccei", query="greenhouse gas")
    assert [f.id for f in greenhouse.flows] == ["GHG_IPCC_TABLE", "DF_38100097"]
    only_stc = await client.list_flows("ccei", query="greenhouse", agency="stc")
    assert [f.id for f in only_stc.flows] == ["DF_38100097"]
    rural = await client.list_flows("ccei", agency="rural")  # matches CA1.RURAL, not CA1
    assert [f.id for f in rural.flows] == ["DF_RURAL_12100138"]
    nothing = await client.list_flows("ccei", query="zzzz")
    assert nothing.matched == 0 and nothing.flows == []


async def test_list_flows_pages_and_says_so(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    page = await client.list_flows("ccei", limit=2, offset=2)
    assert len(page.flows) == 2 and page.matched == 6
    assert "2 of 6 matching flows" in (page.provenance.limits or "")


async def test_list_flows_is_cached_and_french_is_separate(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    await client.list_flows("ccei")
    await client.list_flows("ccei", query="energy")  # served from cache: one request only
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    await client.list_flows("ccei", lang="fr")
    assert len(httpx_mock.get_requests()) == 2
    assert httpx_mock.get_requests()[1].headers["accept-language"] == "fr"


@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 251}, {"offset": -1}], ids=["zero", "too-big", "negative"]
)
async def test_list_flows_rejects_bad_paging(kwargs):
    with pytest.raises(InvalidInput):
        await client.list_flows("ccei", **kwargs)


async def test_list_flows_unknown_space_is_invalid():
    with pytest.raises(InvalidInput, match="space"):
        await client.list_flows("nope")


@pytest.mark.parametrize(
    "body",
    [b"", b'{"data": {"dataflows": [{"id": "X"', b"<html>maintenance</html>"],
    ids=["empty-200", "truncated-json", "html"],
)
async def test_list_flows_unusable_bodies_are_upstream_errors(httpx_mock, body):
    httpx_mock.add_response(url=LIST_URL, content=body)
    with pytest.raises(UpstreamError):
        await client.list_flows("ccei")


async def test_list_flows_wrong_shape_and_empty_list_are_upstream_errors(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json={"data": {"dataflows": [{"id": "X"}]}})
    with pytest.raises(UpstreamError, match="SDMX-JSON"):
        await client.list_flows("ccei")
    cache_module._caches.clear()
    httpx_mock.add_response(url=LIST_URL, json={"data": {"dataflows": []}})
    with pytest.raises(UpstreamError, match="empty"):
        await client.list_flows("ccei")


async def test_list_flows_504_is_unavailable(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, status_code=504, is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="504"):
        await client.list_flows("ccei")


async def test_list_flows_406_is_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=LIST_URL, status_code=406, text="acceptable: application/vnd.sdmx.structure+json"
    )
    with pytest.raises(InvalidInput, match="406"):
        await client.list_flows("ccei")


# ------------------------------------------------------------- structure


async def test_structure_lists_dimensions_in_key_order_with_available_codes(httpx_mock):
    _mock_structure(httpx_mock)
    result = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")
    assert result.flow == "CCEI,GHG_IPCC_TABLE,2.0"
    assert result.key_order == ["FREQ", "REF_AREA", "IPCC_CATEGORY"]
    assert result.time_dimension == "TIME_PERIOD"
    assert result.attributes == ["UNIT_MEASURE", "OBS_STATUS"]
    assert (result.start_period, result.end_period) == ("1990-01-01", "2024-12-31")
    assert result.observation_count == 451360
    assert result.non_production is True
    area = result.dimensions[1]
    assert area.name == "Geography"
    # Yukon is in the codelist but has no data: not offered.
    assert [c.id for c in area.codes] == ["CA", "CA_AB", "CA_BC"]
    assert (area.code_count, area.codelist_size) == (3, 4)
    assert area.codes[1].parent_id == "CA"
    assert result.provenance.as_of is not None
    assert "STC" not in (result.provenance.licence or "")
    assert "Open Government Licence" in (result.provenance.licence or "")


async def test_structure_pages_filters_and_selects_a_dimension(httpx_mock):
    _mock_structure(httpx_mock)
    one = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE", dimension="ref_area", limit=1)
    assert len(one.dimensions) == 1 and len(one.dimensions[0].codes) == 1
    assert "REF_AREA: 1 of 3 codes" in (one.provenance.limits or "")
    named = await client.get_structure(
        "ccei", "CCEI,GHG_IPCC_TABLE", dimension="REF_AREA", code_query="alberta"
    )
    assert [c.id for c in named.dimensions[0].codes] == ["CA_AB"]
    with pytest.raises(NotFound, match="FREQ, REF_AREA, IPCC_CATEGORY"):
        await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE", dimension="NOPE")


async def test_structure_ignores_a_partial_allowed_constraint(httpx_mock):
    """Live: DF_25100014 has an Allowed constraint on PRODUCT alone beside the Actual one."""
    actual = STRUCTURE_PAYLOAD["data"]["contentConstraints"][0]
    allowed = {
        "id": "CC_GHG_IPCC_TABLE",
        "type": "Allowed",
        "constraintAttachment": actual["constraintAttachment"],
        "cubeRegions": [
            {"isIncluded": True, "keyValues": [{"id": "IPCC_CATEGORY", "values": ["100"]}]}
        ],
    }
    payload = {"data": {**STRUCTURE_PAYLOAD["data"], "contentConstraints": [allowed, actual]}}
    _mock_structure(httpx_mock, payload)
    result = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")
    assert [c.id for c in result.dimensions[2].codes] == ["0", "100"]
    assert [c.id for c in result.dimensions[0].codes] == ["A"]
    assert result.observation_count == 451360


async def test_structure_without_constraint_lists_the_whole_codelist(httpx_mock):
    payload = {"data": {**STRUCTURE_PAYLOAD["data"], "contentConstraints": []}}
    _mock_structure(httpx_mock, payload)
    result = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")
    assert result.dimensions[1].code_count == 4
    assert result.observation_count is None
    assert "no availability constraint" in (result.provenance.coverage or "")


async def test_structure_explicit_version_and_french_header(httpx_mock):
    httpx_mock.add_response(
        url=f"{CCEI}/dataflow/CCEI/GHG_IPCC_TABLE/2.0?references=all", json=STRUCTURE_PAYLOAD
    )
    result = await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE,2.0", lang="fr")
    assert result.flow.endswith(",2.0")
    assert httpx_mock.get_requests()[0].headers["accept-language"] == "fr"


async def test_structure_unknown_flow_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{CCEI}/dataflow/CCEI/NOPE/latest?references=all",
        status_code=404,
        text="Could not find requested structures",
    )
    with pytest.raises(NotFound, match="Could not find requested structures"):
        await client.get_structure("ccei", "CCEI,NOPE")


@pytest.mark.parametrize(
    "body",
    [b"", b'{"data":{"dataflows":[{"id":"GHG_IP', b"[]"],
    ids=["empty", "truncated", "not-an-object"],
)
async def test_structure_bad_bodies_are_upstream_errors(httpx_mock, body):
    httpx_mock.add_response(url=STRUCT_URL, content=body)
    with pytest.raises(UpstreamError):
        await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")


async def test_structure_missing_dsd_is_upstream_error(httpx_mock):
    payload = {"data": {**STRUCTURE_PAYLOAD["data"], "dataStructures": []}}
    _mock_structure(httpx_mock, payload)
    with pytest.raises(UpstreamError, match="SDMX-JSON"):
        await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")


async def test_structure_is_cached(httpx_mock):
    _mock_structure(httpx_mock)
    await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE")
    await client.get_structure("ccei", "CCEI,GHG_IPCC_TABLE", dimension="FREQ")
    assert len(httpx_mock.get_requests()) == 1


# ------------------------------------------------------------ flow reference


async def test_bare_flow_id_resolves_through_the_list(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    # The list already names version 2.0, so the structure is fetched for it.
    httpx_mock.add_response(
        url=f"{CCEI}/dataflow/CCEI/GHG_IPCC_TABLE/2.0?references=all", json=STRUCTURE_PAYLOAD
    )
    result = await client.get_structure("ccei", "GHG_IPCC_TABLE")
    assert result.flow == "CCEI,GHG_IPCC_TABLE,2.0"


async def test_unknown_bare_id_suggests_close_ids(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    with pytest.raises(NotFound, match="GHG_IPCC_TABLE"):
        await client.get_structure("ccei", "GHG_IPCC_TABEL")


async def test_bare_id_under_two_agencies_is_ambiguous(httpx_mock):
    payload = {
        "data": {
            "dataflows": [
                _flow("CA1", "DF_RURAL_12100138", "1.0", "Trade (switch)"),
                _flow("CA1.RURAL", "DF_RURAL_12100138", "1.0", "Trade"),
            ]
        }
    }
    httpx_mock.add_response(url=LIST_URL, json=payload)
    with pytest.raises(InvalidInput, match="CA1,DF_RURAL_12100138,1.0; CA1.RURAL"):
        await client.get_structure("ccei", "DF_RURAL_12100138")


@pytest.mark.parametrize("flow", ["", "A,B,C,D", "a b", "CCEI,,X", "x/../y"])
async def test_bad_flow_reference_is_invalid(flow):
    with pytest.raises(InvalidInput, match="flow"):
        await client.get_structure("ccei", flow)


# ------------------------------------------------------------------ data


async def test_data_resolves_version_defaults_to_latest_n_and_sorts_oldest_first(httpx_mock):
    _mock_structure(httpx_mock)
    # lastNObservations answers newest-first.
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA_AB.0?lastNObservations=12",
        text=_csv(_row("CA_AB", "2024", "260143.5"), _row("CA_AB", "2023", "260081.1")),
    )
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA_AB.0")
    assert result.flow == "CCEI,GHG_IPCC_TABLE,2.0"
    assert result.series_total == 1 and result.row_count == 2
    series = result.series[0]
    assert series.series_key == {"FREQ": "A", "REF_AREA": "CA_AB", "IPCC_CATEGORY": "0"}
    assert series.attributes == {"UNIT_MEASURE": "KT", "OBS_STATUS": "A"}
    assert [(o.period, o.value) for o in series.observations] == [
        ("2023", 260081.1),
        ("2024", 260143.5),
    ]
    assert "latest 12 observations per series" in (result.provenance.limits or "")
    assert result.non_production is True
    assert "NonProductionDataflow" in (result.provenance.coverage or "")
    assert "Statistics Canada Open Licence" in (result.provenance.licence or "")
    assert "lastNObservations=12" in result.provenance.url


async def test_data_period_range_sends_no_default_last_n(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA.0?startPeriod=2020&endPeriod=2021",
        text=_csv(_row("CA", "2020", "1"), _row("CA", "2021", "2")),
    )
    result = await client.get_data(
        "ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", start_period="2020", end_period="2021"
    )
    assert result.row_count == 2
    assert result.provenance.limits is None


async def test_data_groups_series_and_keeps_varying_attributes_per_observation(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA+CA_AB.0?lastNObservations=2",
        text=_csv(
            _row("CA", "2023", "5", status="A"),
            _row("CA_AB", "2023", "3", status="A"),
            _row("CA", "2024", "", status="E"),
            _row("CA_AB", "2024", "4", status="A"),
        ),
    )
    result = await client.get_data(
        "ccei", "CCEI,GHG_IPCC_TABLE", "A.CA+CA_AB.0", last_n_observations=2
    )
    canada, alberta = result.series
    assert alberta.attributes["OBS_STATUS"] == "A"
    assert "OBS_STATUS" not in canada.attributes
    assert canada.observations[0].attributes == {"OBS_STATUS": "A"}
    assert canada.observations[1].value is None
    assert canada.observations[1].attributes == {"OBS_STATUS": "E"}


async def test_data_non_numeric_value_is_kept_as_text(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA.0?lastNObservations=12",
        text=_csv(_row("CA", "2024", "x"), _row("CA", "2023", "NaN")),
    )
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")
    values = [(o.value, o.value_text) for o in result.series[0].observations]
    assert values == [(None, "NaN"), (None, "x")]


async def test_data_semicolon_delimited_body_is_parsed(httpx_mock):
    """Accept-Language: fr made the live service answer with ';' delimiters."""
    _mock_structure(httpx_mock)
    body = _csv(_row("CA", "2024", "1.5"), header=CSV_HEADER).replace(",", ";")
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text=body)
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", lang="fr")
    assert result.series[0].observations[0].value == 1.5
    assert "accept-language" not in httpx_mock.get_requests()[-1].headers


async def test_data_key_segment_count_is_checked_before_any_data_request(httpx_mock):
    """Live: extra key segments were silently ignored (HTTP 200)."""
    _mock_structure(httpx_mock)
    with pytest.raises(InvalidInput, match="4 segments but CCEI,GHG_IPCC_TABLE,2.0 has 3"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0.CO2EQ")
    with pytest.raises(InvalidInput, match="FREQ.REF_AREA.IPCC_CATEGORY"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA")
    assert len(httpx_mock.get_requests()) == 1  # the structure only


@pytest.mark.parametrize("key", ["all", "", ".."])
async def test_data_whole_large_flow_is_refused(httpx_mock, key):
    """451,360 observations: the live service timed out (HTTP 504) on `all`."""
    _mock_structure(httpx_mock)
    with pytest.raises(InvalidInput, match="451,360 observations"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", key)


async def test_data_whole_small_flow_is_allowed(httpx_mock):
    payload = {
        "data": {
            **STRUCTURE_PAYLOAD["data"],
            "contentConstraints": [
                {
                    **STRUCTURE_PAYLOAD["data"]["contentConstraints"][0],
                    "annotations": [{"id": "obs_count", "title": "300", "type": "sdmx_metrics"}],
                }
            ],
        }
    }
    _mock_structure(httpx_mock, payload)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/all?lastNObservations=12", text=_csv(_row("CA", "2024", "1"))
    )
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "all")
    assert result.row_count == 1


async def test_data_no_records_names_the_codes_without_data(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA_YT.0?lastNObservations=12", status_code=404, text="NoRecordsFound"
    )
    with pytest.raises(NotFound, match="REF_AREA=CA_YT"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA_YT.0")


async def test_data_empty_and_header_only_bodies_are_not_found(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", content=b"")
    with pytest.raises(NotFound, match="matched no series"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=5", text=_csv())
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", last_n_observations=5)
    assert result.series == [] and result.row_count == 0


async def test_data_truncated_body_drops_the_partial_last_row(httpx_mock):
    _mock_structure(httpx_mock)
    body = _csv(_row("CA", "2024", "1"), _row("CA", "2023", "2.5"), newline=False)[:-6]
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text=body)
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")
    assert result.row_count == 1
    assert "ended mid-row" in (result.provenance.limits or "")


@pytest.mark.parametrize(
    "body",
    ["<html><body>Gateway</body></html>", "a,b,c\n1,2,3\n"],
    ids=["html", "not-sdmx-csv"],
)
async def test_data_non_csv_body_is_upstream_error(httpx_mock, body):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text=body)
    with pytest.raises(UpstreamError, match="SDMX-CSV"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")


async def test_data_row_with_extra_fields_is_upstream_error(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA.0?lastNObservations=12",
        text=_csv(_row("CA", "2024", "1") + ",surplus,fields"),
    )
    with pytest.raises(UpstreamError, match="row 2"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")


async def test_data_short_row_is_padded_with_empty_attributes(httpx_mock):
    _mock_structure(httpx_mock)
    short = "DATAFLOW,CCEI:GHG_IPCC_TABLE(2.0),I,A,CA,0,2024,7"
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text=_csv(short))
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0")
    assert result.series[0].observations[0].value == 7
    assert result.series[0].attributes == {}


async def test_data_bad_period_422_is_invalid_input(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A.CA.0?startPeriod=2020-99",
        status_code=422,
        text="Semantic Error - Invalid Date Format `2020-99`",
    )
    with pytest.raises(InvalidInput, match="Invalid Date Format"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", start_period="2020-99")


@pytest.mark.parametrize("period", ["2020/01", "Jan 2020", "20"])
async def test_data_period_syntax_is_checked_locally(period):
    with pytest.raises(InvalidInput, match="not an SDMX period"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE,2.0", "A.CA.0", start_period=period)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"last_n_observations": 0},
        {"last_n_observations": 99999},
        {"max_rows": 0},
        {"max_rows": 5001},
    ],
)
async def test_data_numeric_arguments_are_bounded(kwargs):
    with pytest.raises(InvalidInput):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE,2.0", "A.CA.0", **kwargs)


async def test_data_bad_key_characters_are_invalid():
    with pytest.raises(InvalidInput, match="key"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE,2.0", "A.CA/../0")


async def test_data_504_and_timeout_advise_narrowing(httpx_mock):
    _mock_structure(httpx_mock)
    httpx_mock.add_response(
        url=f"{DATA_BASE}/A..0?lastNObservations=12", status_code=504, is_reusable=True
    )
    with pytest.raises(UpstreamUnavailable, match="filter more dimensions"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A..0")
    cache_module._caches.clear()
    httpx_mock.reset()
    _mock_structure(httpx_mock)
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamUnavailable, match="did not answer"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A..0")


async def test_data_unknown_flow_is_not_found(httpx_mock):
    httpx_mock.add_response(
        url=f"{CCEI}/dataflow/CCEI/NOPE/latest?references=all",
        status_code=404,
        text="Could not find requested structures",
    )
    with pytest.raises(NotFound):
        await client.get_data("ccei", "CCEI,NOPE", "A.CA.0")


async def test_data_caps_series_rows_and_total(httpx_mock):
    _mock_structure(httpx_mock)
    rows = [
        _row("CA", f"{1000 + n}", str(n), category=str(cat))
        for cat in range(constants.MAX_SERIES + 5)
        for n in range(3)
    ]
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.?lastNObservations=12", text=_csv(*rows))
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.", max_rows=100)
    assert result.series_total == constants.MAX_SERIES + 5
    assert result.row_count == 100
    limits = result.provenance.limits or ""
    assert "first 200 of 205 series" in limits
    assert "100 of 600 rows" in limits


async def test_data_keeps_newest_rows_per_series(httpx_mock):
    _mock_structure(httpx_mock)
    rows = [_row("CA", f"{3000 - n}", str(n)) for n in range(constants.MAX_ROWS + 20)]
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?startPeriod=1000", text=_csv(*rows))
    result = await client.get_data(
        "ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", start_period="1000", max_rows=5000
    )
    periods = [o.period for o in result.series[0].observations]
    assert len(periods) == constants.MAX_ROWS
    assert periods[-1] == "3000"
    assert f"newest {constants.MAX_ROWS} rows kept per series" in (result.provenance.limits or "")


async def test_partner_licence_only_for_partner_agencies():
    assert "Open Government Licence" in client.licence_for("CCEI")
    assert "Open Government Licence" in client.licence_for("CA1.QOL.ECCC")
    assert "Open Government Licence" in client.licence_for("CA1.QOL.ISC")
    assert "Open Government Licence" in client.licence_for(None)
    assert "Open Government Licence" not in client.licence_for("STC")
    assert "Open Government Licence" not in client.licence_for("CITH")
    assert "Statistics Canada Open Licence" in client.licence_for("CITH")


async def test_shared_space_uses_its_own_base_url(httpx_mock):
    httpx_mock.add_response(url=f"{SHARED}/dataflow/all/all/latest", json=LIST_PAYLOAD)
    result = await client.list_flows("stcshared")
    assert result.provenance.url.startswith(SHARED)


# ---------------------------------------------------------------- search

SEARCH_URL = re.compile(r"https://sdmx-sfs\.statcan\.gc\.ca/api/search\?tenant=.*")


def _hit(agency: str, flow_id: str, score: float, **extra: Any) -> dict:
    return {
        "dimensions": ["Geography", "Time"],
        "name": f"Flow {flow_id}",
        "description": "<p>Greenhouse gas <strong>emissions</strong></p>",
        "dataflowId": flow_id,
        "version": "1.0",
        "agencyId": agency,
        "lastUpdated": "2025-12-11T13:39:32.000Z",
        "score": score,
        **extra,
    }


def _search_payload(found: int, hits: list[dict]) -> dict:
    return {
        "numFound": found,
        "start": 0,
        "dataflows": hits,
        "facets": {
            "datasourceId": {"buckets": [{"val": "ds-release-ccei", "count": found}]},
            "Frequency": {"buckets": [{"val": "0|Annual#A#", "count": 25}]},
            "Geography": {
                "buckets": [
                    {"val": "0|Canada#1#", "count": 19},
                    {"val": "1|Canada#1#|Alberta#10#", "count": 6},
                ]
            },
        },
        "highlighting": {"x": {"name": ["<mark>x</mark>"]}},
    }


async def test_search_parses_hits_and_facets(httpx_mock):
    httpx_mock.add_response(
        url=SEARCH_URL,
        method="POST",
        json=_search_payload(27, [_hit("STC", "DF_38100097", 48.4), _hit("CCEI", "GHG", 30.0)]),
    )
    result = await client.search_flows("ccei", "greenhouse gas", limit=2)
    request = httpx_mock.get_requests()[0]
    assert request.url.params["tenant"] == "statcan-ccei-public"
    assert json.loads(request.read()) == {
        "lang": "en",
        "search": "greenhouse gas",
        "rows": 2,
        "start": 0,
    }
    assert result.found == 27 and result.tenants == ["ccei"]
    assert [h.flow for h in result.flows] == ["STC,DF_38100097,1.0", "CCEI,GHG,1.0"]
    assert result.flows[0].description == "Greenhouse gas emissions"
    assert result.flows[0].dimensions == ["Geography", "Time"]
    names = [f.name for f in result.facets]
    assert names == ["Frequency", "Geography"]
    alberta = result.facets[1].values[1]
    assert (alberta.label, alberta.count) == ("Alberta", 6)
    assert alberta.filter_value == "1|Canada#1#|Alberta#10#"
    assert "122 of 245" in (result.provenance.coverage or "")
    assert "28 of" not in (result.provenance.limits or "")


async def test_search_filters_are_passed_through(httpx_mock):
    httpx_mock.add_response(url=SEARCH_URL, method="POST", json=_search_payload(0, []))
    result = await client.search_flows(
        "ccei", "ghg", filters={"Frequency": ["0|Annual#A#"]}, lang="fr"
    )
    body = json.loads(httpx_mock.get_requests()[0].read())
    assert body["facets"] == {"Frequency": ["0|Annual#A#"]} and body["lang"] == "fr"
    assert result.found == 0 and result.flows == []


async def test_search_shared_space_merges_three_tenants_by_score(httpx_mock):
    for hit in (
        _hit("CA1.RURAL", "R", 5.0),
        _hit("CITH", "C", 9.0),
        _hit("CA1.PCEIP", "P", 7.0),
    ):
        httpx_mock.add_response(url=SEARCH_URL, method="POST", json=_search_payload(1, [hit]))
    result = await client.search_flows("stcshared", "trade", limit=2)
    assert result.found == 3
    assert sorted(result.tenants) == ["cith", "pceip", "rural"]
    assert [h.id for h in result.flows] == ["C", "P"]
    assert "1 more" not in (result.provenance.limits or "")
    assert "2 of 3 matching flows" in (result.provenance.limits or "")
    frequency = next(f for f in result.facets if f.name == "Frequency")
    assert frequency.values[0].count == 75  # 25 per tenant, summed


async def test_search_single_tenant_of_shared_space(httpx_mock):
    httpx_mock.add_response(url=SEARCH_URL, method="POST", json=_search_payload(0, []))
    await client.search_flows("stcshared", "x", tenant="cith")
    assert len(httpx_mock.get_requests()) == 1
    assert httpx_mock.get_requests()[0].url.params["tenant"] == "statcan-stcshared-cith-public"


async def test_search_rejects_wrong_tenant_and_paging():
    with pytest.raises(InvalidInput, match="tenant"):
        await client.search_flows("ccei", "x", tenant="cith")
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_flows("ccei", "x", limit=40, offset=20)
    with pytest.raises(InvalidInput, match="limit"):
        await client.search_flows("ccei", "x", limit=0)


async def test_search_failures_are_typed(httpx_mock):
    httpx_mock.add_response(url=SEARCH_URL, method="POST", status_code=504, is_reusable=True)
    with pytest.raises(UpstreamUnavailable, match="504"):
        await client.search_flows("ccei", "x")
    httpx_mock.reset()
    httpx_mock.add_response(
        url=SEARCH_URL, method="POST", content=b'{"numFound": 3, "dataflows": ['
    )
    with pytest.raises(UpstreamError, match="invalid JSON"):
        await client.search_flows("ccei", "x")
    httpx_mock.reset()
    httpx_mock.add_response(url=SEARCH_URL, method="POST", json={"unexpected": True})
    with pytest.raises(UpstreamError, match="not shaped as expected"):
        await client.search_flows("ccei", "x")
    httpx_mock.reset()
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("slow"))
    with pytest.raises(UpstreamUnavailable, match="did not answer"):
        await client.search_flows("ccei", "x")


async def test_search_400_is_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=SEARCH_URL, method="POST", status_code=400, json={"message": "bad filter"}
    )
    with pytest.raises(InvalidInput, match="bad filter"):
        await client.search_flows("ccei", "x", filters={"Nope": ["x"]})


# ----------------------------------------------------------------- French

NBSP = "\N{NO-BREAK SPACE}"


async def test_french_list_flows_notes_and_licence(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    page = await client.list_flows("ccei", limit=2, offset=2, lang="fr")
    assert page.provenance.limits == f"2 des 6 flux correspondants{NBSP}; utilisez limit/offset"
    assert "Statistique Canada n'a pas déclaré" in (page.provenance.coverage or "")
    assert "Licence du gouvernement ouvert – Canada" in (page.provenance.licence or "")
    assert "Licence ouverte de Statistique Canada" in (page.provenance.licence or "")


async def test_english_list_flows_wording_is_unchanged(httpx_mock):
    httpx_mock.add_response(url=LIST_URL, json=LIST_PAYLOAD)
    page = await client.list_flows("ccei", limit=2, offset=2)
    assert page.provenance.limits == "2 of 6 matching flows; use limit/offset"
    assert (page.provenance.coverage or "").startswith("Every dataflow in this space")
    assert "Open Government Licence - Canada" in (page.provenance.licence or "")


async def test_french_errors(httpx_mock):
    with pytest.raises(InvalidInput, match="space doit être"):
        await client.list_flows("nope", lang="fr")
    httpx_mock.add_response(url=LIST_URL, json={"data": {"dataflows": []}})
    with pytest.raises(UpstreamError, match="La liste de flux de données est vide"):
        await client.list_flows("ccei", lang="fr")


async def test_french_data_notes_and_csv_errors(httpx_mock):
    _mock_structure(httpx_mock)
    body = _csv(_row("CA", "2024", "1"), _row("CA", "2023", "2.5"), newline=False)[:-6]
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text=body)
    result = await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", lang="fr")
    assert "aucun filtre de période" in (result.provenance.limits or "")
    assert f"(tronquée){NBSP};" in (result.provenance.limits or "")
    httpx_mock.add_response(url=f"{DATA_BASE}/A.CA.0?lastNObservations=12", text="a,b\n1,2\n")
    with pytest.raises(UpstreamError, match=f"en-tête{NBSP}:"):
        await client.get_data("ccei", "CCEI,GHG_IPCC_TABLE", "A.CA.0", lang="fr")


async def test_french_search_error(httpx_mock):
    httpx_mock.add_response(url=SEARCH_URL, method="POST", json={"unexpected": True})
    with pytest.raises(UpstreamError, match="n'a pas la forme attendue"):
        await client.search_flows("ccei", "x", lang="fr")

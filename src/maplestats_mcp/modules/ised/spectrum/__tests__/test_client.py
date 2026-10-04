from __future__ import annotations

import pytest

from maplestats_mcp.modules.ised.spectrum import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_LAYER_URL = f"{constants.SERVICE_URL}/{constants.LAYER_INDEX}"

_SAMPLE_ATTRIBUTES = {
    "OBJECTID": 1,
    "NEW_LICNO": "010287465-001",
    "LICENSEE": "TBayTel",
    "SERVICE": "CELL",
    "TRANSMIT_FREQ": 887.5,
    "PROV": "ON",
    "LATITUDE": 48.474652778,
    "LONGITUDE": -89.186441667,
}


async def test_query_licences_returns_attributes(httpx_mock, layer_info):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [{"attributes": _SAMPLE_ATTRIBUTES}], "exceededTransferLimit": False},
    )
    result = await client.query_licences()
    assert result.returned_count == 1
    assert result.rows[0]["LICENSEE"] == "TBayTel"
    assert result.exceeded_transfer_limit is False


async def test_query_licences_where_clause_passed_through(httpx_mock, layer_info):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=LICENSEE+%3D+%27TBayTel%27&outFields=%2A&f=json"
            "&resultRecordCount=5&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [], "exceededTransferLimit": False},
    )
    result = await client.query_licences(where="LICENSEE = 'TBayTel'", limit=5)
    assert result.returned_count == 0


async def test_invalid_input_rejects_bad_limit_and_offset():
    with pytest.raises(InvalidInput):
        await client.query_licences(limit=0)
    with pytest.raises(InvalidInput):
        await client.query_licences(offset=-1)


async def test_upstream_5xx_becomes_upstream_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            url=(
                f"{_LAYER_URL}/query?where=1%3D1&outFields=%2A&f=json"
                "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
            ),
            status_code=500,
        )
    with pytest.raises(UpstreamError):
        await client.query_licences()


# Shaped like the live layer document (2026-10-03): date fields are typed
# esriFieldTypeDate and editingInfo carries the last data edit.
_LAYER_INFO = {
    "name": "Site_Data_Extract_XYTableToPoint",
    "editingInfo": {
        "lastEditDate": 1707507567952,
        "schemaLastEditDate": 1707507567952,
        "dataLastEditDate": 1707410524029,
    },
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "SERVICE", "type": "esriFieldTypeString"},
        {"name": "LAST_MOD_DATE", "type": "esriFieldTypeDate"},
        {"name": "LAST_UPLOAD_DATE", "type": "esriFieldTypeDate"},
    ],
}


@pytest.fixture
def layer_info(httpx_mock):
    httpx_mock.add_response(url=f"{_LAYER_URL}?f=json", json=_LAYER_INFO, is_reusable=True)


async def test_date_fields_become_iso_dates_and_as_of_is_the_last_edit(httpx_mock, layer_info):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=PROV%3D%27AB%27&outFields=%2A&f=json"
            "&resultRecordCount=1&resultOffset=0&returnGeometry=false"
        ),
        json={
            "features": [
                {
                    "attributes": {
                        **_SAMPLE_ATTRIBUTES,
                        "SERVICE": "BWA24",
                        "LAST_MOD_DATE": 1431648000000,
                        "LAST_UPLOAD_DATE": 1557273600000,
                    }
                }
            ],
            "exceededTransferLimit": True,
        },
    )
    result = await client.query_licences(where="PROV='AB'", limit=1)
    row = result.rows[0]
    assert row["LAST_MOD_DATE"] == "2015-05-15"
    assert row["LAST_UPLOAD_DATE"] == "2019-05-08"
    assert row["TRANSMIT_FREQ"] == 887.5
    assert result.provenance.as_of is not None
    assert result.provenance.as_of.date().isoformat() == "2024-02-08"
    assert "no refresh has followed" in (result.provenance.freshness or "")


async def test_french_bad_limit_is_french():
    with pytest.raises(InvalidInput) as excinfo:
        await client.query_licences(limit=0, lang="fr")
    assert str(excinfo.value).startswith("Entrée invalide : limit doit être compris")


async def test_french_provenance_text_is_french(httpx_mock, layer_info):
    httpx_mock.add_response(
        url=(
            f"{_LAYER_URL}/query?where=1%3D1&outFields=%2A&f=json"
            "&resultRecordCount=10&resultOffset=0&returnGeometry=false"
        ),
        json={"features": [{"attributes": _SAMPLE_ATTRIBUTES}], "exceededTransferLimit": False},
    )
    result = await client.query_licences(lang="fr")
    assert (result.provenance.coverage or "").startswith("environ 840 000 fiches")
    limits = result.provenance.limits or ""
    assert limits.startswith("lignes plafonnées")
    assert "qu'en anglais ;" in limits

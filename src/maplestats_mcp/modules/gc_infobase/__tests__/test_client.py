"""Tests for modules/gc_infobase/client.py, shaped on live 2026-09-23 files."""

from __future__ import annotations

import re

import pytest

from maplestats_mcp.modules.gc_infobase import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


_DOWNLOAD = f"https://open.canada.ca/data/dataset/{constants.PACKAGE_ID}/resource/r-en/download/eav_eac_en.csv"
_BLOB = "https://opencanada.blob.core.windows.net/opengovprod/resources/r-en/eav_eac_en.csv?sig=x"
_PACKAGE = {
    "success": True,
    "result": {
        "id": constants.PACKAGE_ID,
        "title": "GC InfoBase - Open Datasets",
        "resources": [
            {
                "id": "r-en",
                "name": "Public Accounts of Canada – Authorities and Expenditures by Vote",
                "format": "CSV",
                "url": _DOWNLOAD,
                "language": ["en"],
            },
            {
                "id": "r-fr",
                "name": "Comptes publics du Canada – Autorisations et dépenses par crédit",
                "format": "CSV",
                "url": _DOWNLOAD.replace("_en", "_fr"),
                "language": ["fr"],
            },
        ],
    },
}
_CSV = (
    b"\xef\xbb\xbf"
    b'"fy_ef","org_id","org_name","voted_or_statutory","description","authorities","expenditures"\n'
    b'"2023-24",46,"Canada Revenue Agency",1,"Operating/Program",5957785807.00,5359496028.00\n'
    b'"2022-23",46,"Canada Revenue Agency",1,"Operating/Program",5000000000.00,4900000000.00\n'
    b'"2023-24",1,"Department of Agriculture and Agri-Food",1,"Operating/Program",1.00,1.00\n'
)
_PACKAGE_SHOW = re.compile(r".*/package_show.*")


async def test_list_files_filters_language_and_query(httpx_mock):
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_PACKAGE)
    english = await client.list_files("public accounts")
    assert [f.resource_id for f in english.files] == ["r-en"]
    french = await client.list_files(lang="fr")
    assert [f.resource_id for f in french.files] == ["r-fr"]


async def test_query_follows_blob_redirect_and_filters(httpx_mock):
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_PACKAGE)
    httpx_mock.add_response(url=_DOWNLOAD, status_code=302, headers={"location": _BLOB})
    httpx_mock.add_response(url=_BLOB, content=_CSV)
    result = await client.query(
        "r-en", organization="revenue agency", fiscal_year="2023-2024", columns=["expenditures"]
    )
    assert result.matching_rows == 1
    assert result.rows == [{"expenditures": 5359496028.0}]
    assert result.numeric_columns == ["expenditures"]
    assert result.fiscal_year_column == "fy_ef"
    assert result.organization_column == "org_name"


async def test_list_files_provenance_reproduces_and_reports_cache(httpx_mock):
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_PACKAGE)
    first = await client.list_files()
    assert first.provenance.url.endswith(f"package_show?id={constants.PACKAGE_ID}")
    assert first.provenance.cached is False
    second = await client.list_files()
    assert second.provenance.cached is True


async def test_numbers_are_numbers_but_ids_stay_text(httpx_mock):
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_PACKAGE)
    httpx_mock.add_response(url=_DOWNLOAD, content=_CSV)
    result = await client.query("r-en", fiscal_year="2023")
    assert {"authorities", "expenditures"} <= set(result.numeric_columns)
    assert "org_id" not in result.numeric_columns
    first = result.rows[0]
    assert first["expenditures"] == 5359496028.0
    assert first["org_id"] == "46"  # an identifier, not a quantity
    assert first["fy_ef"] == "2023-24"


# Shaped like the live package (2026-10-03): resource names carry both
# languages in name_translated, and tp_pt_en.csv is English only.
_TP_EN = f"https://open.canada.ca/data/dataset/{constants.PACKAGE_ID}/resource/tp-en/download/tp_pt_en.csv"
_TP_FR = f"https://open.canada.ca/data/dataset/{constants.PACKAGE_ID}/resource/tp-fr/download/tp_pt_fr.csv"
_BILINGUAL_PACKAGE = {
    "success": True,
    "result": {
        "id": constants.PACKAGE_ID,
        "title": "GC InfoBase - Open Datasets",
        "resources": [
            {
                "id": "tp-en",
                "name": "Public Accounts of Canada – Transfer Payments",
                "name_translated": {
                    "en": "Public Accounts of Canada – Transfer Payments",
                    "fr": "Comptes publics du Canada – Paiements de transfert",
                },
                "format": "CSV",
                "url": _TP_EN,
                "language": ["en"],
            },
            {
                "id": "tp-fr",
                "name": "Comptes publics du Canada – Paiements de transfert",
                "name_translated": {
                    "en": "Public Accounts of Canada – Transfer Payments (French)",
                    "fr": "Comptes publics du Canada – Paiements de transfert",
                },
                "format": "CSV",
                "url": _TP_FR,
                "language": ["fr"],
            },
        ],
    },
}
_TP_CSV = (
    b"\xef\xbb\xbf"
    b'"fy_ef","org_id","org_name","type","description","expenditures","authorities"\n'
    b'"2023-24",2,"Atlantic Canada Opportunities Agency","Grant","Atlantic Innovation",'
    b"390060074.49,400000000.00\n"
)


async def test_english_file_with_lang_fr_keeps_its_english_name(httpx_mock):
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_BILINGUAL_PACKAGE, is_reusable=True)
    httpx_mock.add_response(url=_TP_EN, content=_TP_CSV)
    result = await client.query("tp-en", lang="fr")
    # Before: the French CKAN name over English rows.
    assert result.name == "Public Accounts of Canada – Transfer Payments"
    assert result.rows[0]["org_name"] == "Atlantic Canada Opportunities Agency"
    assert result.rows[0]["expenditures"] == 390060074.49
    limits = result.provenance.limits or ""
    assert "n'existe qu'en anglais ;" in limits and "'tp-fr'" in limits
    assert (result.provenance.coverage or "").endswith("lignes correspondantes sur 1")
    with pytest.raises(InvalidInput, match="fiscal_year doit contenir une année"):
        await client.query("tp-en", fiscal_year="l'an dernier", lang="fr")


async def test_query_validates_inputs(httpx_mock):
    with pytest.raises(InvalidInput):
        await client.query("r-en", fiscal_year="last year")
    httpx_mock.add_response(url=_PACKAGE_SHOW, json=_PACKAGE)
    with pytest.raises(NotFound):
        await client.query("missing")

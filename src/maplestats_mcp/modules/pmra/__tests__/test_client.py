"""Tests on rows trimmed from the PMRA extracts (2026-10-03), Windows-1252 like the source."""

from __future__ import annotations

import pytest

from maplestats_mcp.modules.pmra import client, constants
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_BASE = constants.EXTRACT_URL

_PRODUCT_HEADER = (
    "Registration number,Product name - English,Product name - French,Registration Status,"
    "Expiry date,Marketing type,Date first registered,Exclusive period start date,"
    "Active ingredients - English,Active ingredients - French,Product Type,Registrant name,"
    "Use Site Category,Sites of Use,Pests,Current / Historical\r\n"
)
# A quoted French ingredient with a line break inside, as in the real file.
_ROUNDUP = (
    "31153,REFILL FOR ROUNDUP READY-TO-USE WITH WAND APPLICATOR,"
    "RECHARGE POUR ROUNDUP PRÊT-À-L'EMPLOI AVEC TUBE APPLICATEUR,Full Registration,"
    "2030-12-31,DOMESTIC,2013-10-15,1976-07-01,"
    "GLYPHOSATE (PRESENT AS ISOPROPYLAMINE SALT OR ETHANOLAMINE SALT),"
    '"GLYPHOSATE (N.M.) (PRÉSENT SOUS FORME DE\nSEL D\'ISOPROPYLAMINE)",HERBICIDE,'
    'BAYER CROPSCIENCE INC.*,"16-INDUSTRIAL & DOMESTIC VEGETATION CONTROL, 30-TURF",'
    "AROUND BUILDINGS;DRIVEWAYS;PATIO,ANNUAL GRASSES;CANADA THISTLE;POISON IVY,Current\r\n"
)
_SIESTA = (
    '2837,"""103"" SIESTA",,,,NOT AVAILABLE,1948-07-01,1927-07-01,NOT AVAILABLE,'
    "NOT AVAILABLE,,,,,,Historical\r\n"
)
# Pests cut at exactly 2,000 characters, as in 262 products of the real extract.
_POLECI = (
    '32446,POLECI 2.5 EC INSECTICIDE,"POLECI 2,5 EC INSECTICIDE",Full Registration,'
    "2026-12-31,COMMERCIAL,2016-09-28,1982-06-14,DELTAMETHRIN;PIPERONYL BUTOXIDE,"
    "DELTAMÉTHRINE (N.F.),INSECTICIDE,SHARDA CROPCHEM LIMITED*,5-GREENHOUSE FOOD CROPS,"
    "TOMATOES," + ("APHIDS;" * 286)[:2000] + ",Current\r\n"
)
_PRODUCTS_FR_ROW = (
    '24075,SCORE ADJUVANT,"\nSCORE ADJUVANT (UNE COMPOSANTE)",Annulé,2020-04-04,'
    "COMMERCIAL,1995-04-26,1973-07-01,PETROLEUM HYDROCARBON BLEND,MÉLANGE (N.M.),"
    "ADJUVANT,SYNGENTA CANADA INC.*,13-CULTURES,BLÉ DUR,FOLLE AVOINE,Historique\r\n"
)

_INGREDIENTS = (
    "Active ingredient name - English,Active ingredient name - French,Reevaluation status,"
    "CAS number\r\n"
    "DELTAMETHRIN,DELTAMÉTHRINE (N.F.),NO,52918-63-5\r\n"
    "GLYPHOSATE (PRESENT AS ISOPROPYLAMINE SALT OR ETHANOLAMINE SALT),"
    '"GLYPHOSATE (N.M.) (PRÉSENT SOUS FORME DE\nSEL D\'ISOPROPYLAMINE)",YES,\r\n'
).encode("cp1252")

_FILLER_MRL = [f"Captan,Commodity {i},0.1,,EMRL2010-01" for i in range(1000)]
_MRL = (
    "Chemical Common Name,Food Commodity,MRL Value (ppm),Comments,Established Via\r\n"
    + "\r\n".join(
        [
            "Glyphosate,Wheat,5.0,,Canada Gazette II Prior to 16 June 2008",
            "Glyphosate,Barley,10,,Canada Gazette II Prior to 16 June 2008",
            "Glyphosate-trimesium,Wheat,1,,EMRL2008-02 (9 July 2008)",
            "Deltamethrin,Lettuce,0.2,except head lettuce,EMRL2011-13 (18 March 2011)",
            *_FILLER_MRL,
        ]
    )
    + "\r\n"
).encode("cp1252")
_MRL_FR = (
    "Produit chimique,Denrée alimentaire,Valeur de LMR (ppm),Commentaires,Réglementé selon\r\n"
    + "\r\n".join(
        [
            'Glyphosate,Blé,"5,0",,Gazette du Canada II Avant le 16 juin 2008',
            '"1,3-Dichloropropène",Raisins,"0,018",,PMRL2013-36',
            *[f'Captane,Denrée {i},"0,1",,EMRL2010-01' for i in range(1000)],
        ]
    )
    + "\r\n"
).encode("cp1252")


def _csv(*rows: str, header: str = _PRODUCT_HEADER, pad: bool = False) -> bytes:
    """An extract; the client refuses a full extract under 1,000 rows, so pad those."""
    filler = (
        "".join(f"9{i:05d},FILLER {i},,,,,,,X,X,,,,,,Historical\r\n" for i in range(1000))
        if pad
        else ""
    )
    return (header + "".join(rows) + filler).encode("cp1252")


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def test_extract_parsing_and_layout_check():
    rows = client.parse_extract(_csv(_ROUNDUP), constants.PRODUCT_COLUMNS, "product")
    assert rows[0][2] == "RECHARGE POUR ROUNDUP PRÊT-À-L'EMPLOI AVEC TUBE APPLICATEUR"
    assert rows[0][9] == "GLYPHOSATE (N.M.) (PRÉSENT SOUS FORME DE SEL D'ISOPROPYLAMINE)"
    with pytest.raises(UpstreamError):
        client.parse_extract(_INGREDIENTS, constants.PRODUCT_COLUMNS, "product")
    assert client.base_chemical("GLYPHOSATE (PRESENT AS POTASSIUM SALT)") == "glyphosate"


async def test_search_products(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}product", content=_csv(_ROUNDUP, _SIESTA, _POLECI, pad=True)
    )
    roundup = await client.search_products("roundup")
    assert roundup.total_matched == 1
    product = roundup.products[0]
    assert product.current and product.active_ingredients == [
        "GLYPHOSATE (PRESENT AS ISOPROPYLAMINE SALT OR ETHANOLAMINE SALT)"
    ]
    assert product.product_name_fr is not None and "PRÊT" in product.product_name_fr
    by_ingredient = await client.search_products(active_ingredient="piperonyl")
    assert [p.registration_number for p in by_ingredient.products] == ["32446"]
    historical = await client.search_products("siesta", status="historical")
    assert historical.products[0].product_name == '"103" SIESTA'
    # A registration number finds the product whatever its status.
    assert (await client.search_products(registration_number="2837")).total_matched == 1
    insecticides = await client.search_products(product_type="insecticide")
    assert insecticides.by_product_type == {"INSECTICIDE": 1}
    with pytest.raises(InvalidInput):
        await client.search_products()
    with pytest.raises(InvalidInput):
        await client.search_products(registration_number="PCP 123")


async def test_search_products_in_french(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}product?lang=fr", content=_csv(_PRODUCTS_FR_ROW, pad=True))
    result = await client.search_products("score", status="all", lang="fr")
    product = result.products[0]
    assert product.product_name == "SCORE ADJUVANT (UNE COMPOSANTE)"
    assert product.registration_status == "Annulé" and not product.current


async def test_get_product_joins_ingredients_and_mrls(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}product/31153", content=_csv(_ROUNDUP))
    httpx_mock.add_response(url=f"{_BASE}ingredient", content=_INGREDIENTS)
    httpx_mock.add_response(url=f"{_BASE}mrl", content=_MRL)
    detail = await client.get_product("31153")
    ingredient = detail.ingredients[0]
    assert ingredient.under_reevaluation is True and ingredient.cas_number is None
    assert (ingredient.mrl_chemical, ingredient.mrl_count) == ("Glyphosate", 2)
    assert detail.pests == ["ANNUAL GRASSES", "CANADA THISTLE", "POISON IVY"]
    assert not detail.lists_truncated


async def test_get_product_truncated_lists_and_not_found(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}product/32446?lang=fr", content=_csv(_POLECI))
    httpx_mock.add_response(url=f"{_BASE}ingredient", content=_INGREDIENTS)
    httpx_mock.add_response(url=f"{_BASE}mrl", content=_MRL)
    httpx_mock.add_response(
        url=f"{_BASE}product/9999999",
        status_code=404,
        json={"clientMessage": "Record not found", "errorID": 0},
    )
    detail = await client.get_product("32446", lang="fr")
    assert detail.lists_truncated and detail.product.product_name == "POLECI 2,5 EC INSECTICIDE"
    assert [i.cas_number for i in detail.ingredients] == ["52918-63-5", None]
    assert detail.ingredients[0].mrl_count == 1
    with pytest.raises(NotFound):
        await client.get_product("9999999")


async def test_residue_limits(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}mrl", content=_MRL)
    exact = await client.get_residue_limits("glyphosate")
    # An exact name keeps Glyphosate-trimesium out.
    assert exact.chemicals == ["Glyphosate"] and exact.total_matched == 2
    wheat = await client.get_residue_limits(commodity="wheat")
    assert wheat.chemicals == ["Glyphosate", "Glyphosate-trimesium"]
    assert wheat.limits[0].mrl_ppm == 5.0
    lettuce = await client.get_residue_limits("deltameth")
    assert lettuce.limits[0].comments == "except head lettuce"
    with pytest.raises(InvalidInput):
        await client.get_residue_limits()


async def test_residue_limits_in_french(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}mrl?lang=fr", content=_MRL_FR)
    result = await client.get_residue_limits(commodity="ble", lang="fr")
    assert result.limits[0].mrl_ppm == 5.0
    grapes = await client.get_residue_limits("dichloropropene", lang="fr")
    assert grapes.limits[0].chemical == "1,3-Dichloropropène"
    assert grapes.limits[0].mrl_ppm == 0.018
    assert (result.provenance.coverage or "").endswith(" LMR")
    assert (result.provenance.freshness or "").startswith("quotidienne")
    assert "Agence de réglementation de la lutte antiparasitaire (ARLA)" in (
        result.provenance.licence or ""
    )


async def test_french_errors():
    with pytest.raises(InvalidInput, match="^Entrée invalide : pmra : donnez une"):
        await client.get_residue_limits(lang="fr")
    with pytest.raises(InvalidInput, match="ne contient que des chiffres"):
        await client.get_product("abc", lang="fr")

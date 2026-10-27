"""Drug Product Database client and shared API helpers, on live-shaped payloads (2026-10-03)."""

from __future__ import annotations

import re

import httpx
import pytest

from maplestats_mcp.modules.health_products import api
from maplestats_mcp.modules.health_products.dpd import client
from maplestats_mcp.shared.errors import (
    CloudflareChallenge,
    InvalidInput,
    NotFound,
    UpstreamError,
    UpstreamUnavailable,
)

BASE = "https://health-products.canada.ca/api/drug/"


def _url(endpoint: str, query: str = "") -> re.Pattern[str]:
    return re.compile(re.escape(f"{BASE}{endpoint}/?") + query)


def _product(code, din, brand, company, klass="Human", n="1", descriptor=""):
    return {
        "drug_code": code,
        "class_name": klass,
        "drug_identification_number": din,
        "brand_name": brand,
        "descriptor": descriptor,
        "number_of_ais": n,
        "ai_group_no": "0141702001",
        "company_name": company,
        "last_update_date": "2025-03-22",
    }


PRODUCTS = [
    _product(66502, "02242705", "AROMASIN", "PFIZER CANADA ULC"),
    _product(5254, "00559393", "TYLENOL REGULAR STRENGTH", "KENVUE CANADA INC."),
    _product(3029, "00396516", "TYLENOL W CODEINE NO4 TAB", "MCNEIL PHARMACEUTICAL", n="2"),
    _product(1017, "00002631", "MYSOLINE PRIMIDONE TABLETS 250MG", "AYERST", klass="Veterinary"),
]
STATUSES = [
    {"drug_code": 66502, "status": "Marketed", "history_date": "2004-11-16",
     "original_market_date": "2000-08-17", "external_status_code": 2,
     "expiration_date": None, "lot_number": ""},
    {"drug_code": 5254, "status": "Marketed", "history_date": "2025-05-16",
     "original_market_date": "1980-12-31", "external_status_code": 2,
     "expiration_date": None, "lot_number": ""},
    {"drug_code": 3029, "status": "Cancelled Post Market", "history_date": "1999-08-12",
     "original_market_date": "1976-12-31", "external_status_code": 4,
     "expiration_date": None, "lot_number": ""},
    {"drug_code": 1017, "status": "Cancelled Post Market", "history_date": "2001-08-14",
     "original_market_date": "1976-12-31", "external_status_code": 4,
     "expiration_date": None, "lot_number": ""},
]  # fmt: skip


def _tables(httpx_mock):
    httpx_mock.add_response(url=_url("drugproduct", r"type=json&lang=en$"), json=PRODUCTS)
    httpx_mock.add_response(url=_url("status", r"type=json&lang=en$"), json=STATUSES)


async def test_search_by_brand_puts_marketed_first_and_counts_statuses(httpx_mock):
    _tables(httpx_mock)
    result = await client.search_products(brand="tylenol")
    assert [p.drug_code for p in result.products] == [5254, 3029]
    assert result.by_status == {"Marketed": 1, "Cancelled Post Market": 1}
    assert result.products[1].number_of_active_ingredients == 2


async def test_search_in_french_maps_class_and_status_labels(httpx_mock):
    _tables(httpx_mock)
    result = await client.search_products(product_class="veterinary", lang="fr", brand="myso")
    assert result.products[0].product_class == "Vétérinaire"
    assert result.products[0].status == "Annulé après commercialisation"
    assert (result.provenance.coverage or "").startswith("1 produits sur 1 correspondant à")
    assert "brand contient 'myso'" in (result.provenance.coverage or "")
    assert (result.provenance.freshness or "").startswith("données en ligne de la BDPP")
    assert (result.provenance.licence or "").startswith("Source : Santé Canada.")


async def test_french_errors(httpx_mock):
    with pytest.raises(InvalidInput, match="^Entrée invalide : donnez au moins l'un de"):
        await client.search_products(lang="fr")
    with pytest.raises(InvalidInput, match="n'est pas un DIN"):
        await client.get_product(din="ABC123", lang="fr")
    httpx_mock.add_response(url=_url("drugproduct", r"din=00000001"), status_code=400, json={})
    with pytest.raises(InvalidInput, match="la requête a échoué \\(détail\\s: "):
        await client.get_product(din="1", lang="fr")


async def test_ingredient_search_joins_the_api_filter_to_the_product_table(httpx_mock):
    _tables(httpx_mock)
    httpx_mock.add_response(
        url=_url("activeingredient", r"ingredientname=exemestane&type=json&lang=en$"),
        json=[{"dosage_unit": "", "dosage_value": "", "drug_code": 66502,
               "ingredient_name": "EXEMESTANE", "strength": "25", "strength_unit": "MG"}],
    )  # fmt: skip
    result = await client.search_products(ingredient="exemestane", status="marketed")
    assert [p.din for p in result.products] == ["02242705"]


async def test_din_is_zero_padded_and_validated(httpx_mock):
    _tables(httpx_mock)
    result = await client.search_products(din="2242705")
    assert result.products[0].brand_name == "AROMASIN"
    with pytest.raises(InvalidInput):
        await client.search_products(din="ABC123")


async def test_search_needs_a_filter():
    with pytest.raises(InvalidInput):
        await client.search_products()


async def test_get_product_folds_single_objects_and_404_sub_tables(httpx_mock):
    # Live: drugproduct, status, packaging and pharmaceuticalstd answer one
    # object for ?id=; veterinaryspecies and an empty therapeuticclass 404.
    httpx_mock.add_response(url=_url("drugproduct", r"din=02242705"), json=[PRODUCTS[0]])
    httpx_mock.add_response(url=_url("drugproduct", r"id=66502"), json=PRODUCTS[0])
    httpx_mock.add_response(
        url=_url("activeingredient", r"id=66502"),
        json=[{"dosage_unit": "", "dosage_value": "", "drug_code": 66502,
               "ingredient_name": "EXEMESTANE", "strength": "25", "strength_unit": "MG"}],
    )  # fmt: skip
    httpx_mock.add_response(url=_url("status", r"id=66502"), json=STATUSES[0])
    httpx_mock.add_response(
        url=_url("schedule", r"id=66502"),
        json=[{"drug_code": 66502, "schedule_name": "PRESCRIPTION"}],
    )
    httpx_mock.add_response(
        url=_url("form", r"id=66502"),
        json=[
            {
                "drug_code": 66502,
                "pharmaceutical_form_code": 81,
                "pharmaceutical_form_name": "Tablet",
            }
        ],
    )
    httpx_mock.add_response(
        url=_url("route", r"id=66502"),
        json=[
            {
                "drug_code": 66502,
                "route_of_administration_code": 56,
                "route_of_administration_name": "Oral",
            }
        ],
    )
    httpx_mock.add_response(url=_url("therapeuticclass", r"id=66502"), status_code=404)
    httpx_mock.add_response(
        url=_url("packaging", r"id=66502"),
        json={"drug_code": 66502, "upc": "", "package_size_unit": "", "package_type": "",
              "package_size": "", "product_information": "Pharmachoice [100 Capsule Bottle]"},
    )  # fmt: skip
    httpx_mock.add_response(
        url=_url("pharmaceuticalstd", r"id=66502"),
        json={"drug_code": 66502, "pharmaceutical_std": "MFR"},
    )
    httpx_mock.add_response(url=_url("veterinaryspecies", r"id=66502"), status_code=404)
    httpx_mock.add_response(
        url=_url("company", r"type=json&lang=en$"),
        json=[{"city_name": "Kirkland", "company_code": 4908, "company_name": "PFIZER CANADA ULC",
               "company_type": "DIN OWNER", "country_name": "Canada", "post_office_box": "",
               "postal_code": "H9J 2M5", "province_name": "Quebec",
               "street_name": "17300 Trans-Canada Highway", "suite_number": ""}],
    )  # fmt: skip
    detail = await client.get_product("02242705")
    assert detail.product.status == "Marketed"
    assert detail.original_market_date == "2000-08-17"
    assert detail.active_ingredients[0].strength == "25"
    assert detail.therapeutic_classes == [] and detail.veterinary_species == []
    assert detail.packaging == ["Pharmachoice [100 Capsule Bottle]"]
    assert detail.company is not None and detail.company.city == "Kirkland"


async def test_missing_ok_404_with_a_routing_message_is_an_error(httpx_mock):
    # An empty-body 404 is "no rows"; a 404 naming no matching resource is an
    # endpoint the API no longer has, and must not read as "no rows".
    httpx_mock.add_response(url=_url("veterinaryspecies", r"id=1"), status_code=404)
    assert await api.get_json("drug/veterinaryspecies", {"id": 1}, missing_ok=True) == []
    httpx_mock.add_response(
        url=_url("veterinaryspecies", r"id=2"),
        status_code=404,
        json={"Message": "No HTTP resource was found that matches the request URI"},
    )
    with pytest.raises(UpstreamError, match="HTTP 404"):
        await api.get_json("drug/veterinaryspecies", {"id": 2}, missing_ok=True)


async def test_unknown_din_and_code_raise_not_found(httpx_mock):
    httpx_mock.add_response(url=_url("drugproduct", r"din=09999999"), json=[])
    with pytest.raises(NotFound):
        await client.get_product("9999999")


async def test_shared_din_asks_for_a_drug_code(httpx_mock):
    httpx_mock.add_response(
        url=_url("drugproduct", r"din=00000019"),
        json=[_product(225, "00000019", "A", "X"), _product(226, "00000019", "B", "X")],
    )
    with pytest.raises(InvalidInput, match="225, 226"):
        await client.get_product("00000019")


async def test_ingredient_names_are_grouped_with_strengths(httpx_mock):
    rows = [
        {"dosage_unit": "", "dosage_value": "", "drug_code": i, "ingredient_name": "ACETAMINOPHEN",
         "strength": "500", "strength_unit": "MG"}
        for i in range(1, 4)
    ] + [{"dosage_unit": "ML", "dosage_value": "5", "drug_code": 9,
          "ingredient_name": "ACETAMINOPHEN", "strength": "160", "strength_unit": "MG"}]  # fmt: skip
    httpx_mock.add_response(
        url=_url("activeingredient", r"ingredientname=acetaminophen"), json=rows
    )
    result = await client.search_ingredients("acetaminophen")
    assert result.ingredients[0].product_count == 4
    assert result.ingredients[0].strengths == ["500 MG", "160 MG / 5 ML"]
    assert result.ingredients[0].strength_count == 2
    assert result.provenance.limits is None


async def test_ingredient_strengths_cut_at_eight_is_reported(httpx_mock):
    rows = [
        {"dosage_unit": "", "dosage_value": "", "drug_code": i, "ingredient_name": "IBUPROFEN",
         "strength": str(100 + i), "strength_unit": "MG"}
        for i in range(1, 11)
    ]  # fmt: skip
    httpx_mock.add_response(url=_url("activeingredient", r"ingredientname=ibuprofen"), json=rows)
    result = await client.search_ingredients("ibuprofen")
    assert len(result.ingredients[0].strengths) == 8
    assert result.ingredients[0].strength_count == 10
    assert "ingredients cut: 1" in (result.provenance.limits or "")


def test_as_list_folds_every_answer_shape():
    assert api.as_list({"metadata": {"pagination": None}, "data": [{"a": 1}]}) == [{"a": 1}]
    assert api.as_list({"a": 1}) == [{"a": 1}]
    assert api.as_list(None) == []
    assert api.is_blank({"drug_code": 0, "brand_name": None}, "drug_code")
    with pytest.raises(UpstreamError):
        api.as_list("oops")


async def test_bad_request_becomes_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=_url("drugproduct", r"id=abc"),
        status_code=400,
        json={"Message": "The request is invalid."},
    )
    with pytest.raises(InvalidInput):
        await api.get_json("drug/drugproduct", {"id": "abc"})


async def test_stream_objects_handles_braces_in_strings_and_split_chunks(httpx_mock):
    body = '[{"name": "A {curly} name", "n": 1},\n{"name": "B", "n": 2}]'
    httpx_mock.add_response(url=_url("drugproduct", r"type=json$"), text=body)
    rows = [r async for r in api.stream_objects("drug/drugproduct", lang=None)]
    assert rows == [{"name": "A {curly} name", "n": 1}, {"name": "B", "n": 2}]


async def test_stream_objects_rejects_a_cut_short_answer(httpx_mock):
    httpx_mock.add_response(url=_url("drugproduct", r"type=json$"), text='[{"name": "A"}, {"na')
    with pytest.raises(UpstreamError, match="cut short"):
        _ = [r async for r in api.stream_objects("drug/drugproduct", lang=None)]


async def test_html_200_body_is_an_upstream_error_not_unavailable(httpx_mock):
    # A 200 answer that is an HTML page (a maintenance or error page) is not
    # JSON: the server answered, so this is UpstreamError, not "unreachable".
    httpx_mock.add_response(
        url=_url("drugproduct", r"id=1"),
        status_code=200,
        headers={"content-type": "text/html"},
        text="<html><body>Service temporarily unavailable</body></html>",
    )
    with pytest.raises(UpstreamError, match="did not return JSON") as caught:
        await api.get_json("drug/drugproduct", {"id": "1"})
    assert not isinstance(caught.value, UpstreamUnavailable)


async def test_cloudflare_challenge_passes_through_get_json_unchanged(httpx_mock):
    httpx_mock.add_response(
        url=_url("drugproduct", r"id=1"),
        status_code=403,
        headers={"cf-mitigated": "challenge"},
        text="<html>Just a moment...</html>",
    )
    with pytest.raises(CloudflareChallenge, match="Cloudflare bot challenge"):
        await api.get_json("drug/drugproduct", {"id": "1"})


async def test_network_failure_is_still_upstream_unavailable(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectError("refused"))
    with pytest.raises(UpstreamUnavailable, match="could not be reached"):
        await api.get_json("drug/drugproduct", {"id": "1"})


async def test_stream_objects_undecodable_body_is_an_upstream_error(httpx_mock):
    # A body declared gzip that is not gzip fails to decode inside httpx.
    httpx_mock.add_response(
        url=_url("drugproduct", r"type=json$"),
        headers={"content-encoding": "gzip"},
        content=b"this is not a gzip stream",
    )
    with pytest.raises(UpstreamError, match="could not be decoded") as caught:
        _ = [r async for r in api.stream_objects("drug/drugproduct", lang=None)]
    assert not isinstance(caught.value, UpstreamUnavailable)

"""LNHPD and MDALL clients, on live-shaped payloads (2026-10-03)."""

from __future__ import annotations

import json
import re

import pytest

from maplestats_mcp.modules.health_products.lnhpd import client as lnhpd
from maplestats_mcp.modules.health_products.mdall import client as mdall
from maplestats_mcp.shared.errors import InvalidInput, NotFound

BASE = "https://health-products.canada.ca/api/"


def _url(endpoint: str, query: str = "") -> re.Pattern[str]:
    return re.compile(re.escape(f"{BASE}{endpoint}/?") + query)


def _licence(npn, lnhpd_id, name, company, *, primary=1, status=1):
    return {
        "lnhpd_id": lnhpd_id, "licence_number": npn, "licence_date": "2004-07-21",
        "revised_date": None, "time_receipt": "2004-02-19", "date_start": "2004-02-20",
        "product_name_id": 15709, "product_name": name, "dosage_form": "Capsule",
        "company_id": 10509, "company_name_id": 15689, "company_name": company,
        "sub_submission_type_code": 7, "sub_submission_type_desc": "Non-Traditional (M)",
        "flag_primary_name": primary, "flag_product_status": status,
        "flag_attested_monograph": 0,
    }  # fmt: skip


LICENCES = [
    _licence("80000035", 3904641, "Easy-Mind", "Phytos Inc."),
    _licence("80000035", 3904641, "Night-Cap", "Phytos Inc.", primary=0),
    _licence("80015238", 5947890, '"Melatonin 3 mg"\tSublingual', "HLC-Healing Line Corp."),
    _licence("80000012", 3892000, "Red Bull Melatonin", "Red Bull GmbH", status=0),
]


async def test_nhp_search_streams_the_table_into_an_index(httpx_mock):
    # The live table is one array with no pagination; a tab inside a name
    # must not break the index's columns.
    httpx_mock.add_response(
        url=_url("natural-licences/productlicence", r"type=json&lang=en$"),
        text=json.dumps(LICENCES),
    )
    result = await lnhpd.search_products("MELATONIN")
    assert [p.npn for p in result.products] == ["80015238"]
    assert result.products[0].product_name == '"Melatonin 3 mg" Sublingual'
    everything = await lnhpd.search_products("melatonin", active_only=False)
    assert everything.total_matched == 2 and not everything.products[1].active
    by_company = await lnhpd.search_products(company="phytos")
    assert [p.primary_name for p in by_company.products] == [True, False]
    assert by_company.licences_matched == 1


async def test_nhp_search_needs_three_characters():
    with pytest.raises(InvalidInput):
        await lnhpd.search_products("ab")


async def test_nhp_product_reads_wrapped_and_bare_answers(httpx_mock):
    httpx_mock.add_response(
        url=_url("natural-licences/productlicence", r"id=80000035"), json=LICENCES[:2]
    )
    wrapped = {"metadata": {"pagination": None, "dateReceived": "2026-10-04T01:37:00Z"}}
    httpx_mock.add_response(
        url=_url("natural-licences/medicinalingredient", r"id=3904641"),
        json={**wrapped, "data": [{
            "lnhpd_id": 3904641, "ingredient_name": "Scutellaria lateriflora",
            "potency_amount": 0.0, "potency_constituent": "", "potency_unit_of_measure": "",
            "quantity": 100.0, "quantity_minimum": 0.0, "quantity_maximum": 0.0,
            "quantity_unit_of_measure": "milligrams", "ratio_numerator": "4",
            "ratio_denominator": "1", "dried_herb_equivalent": "400",
            "dhe_unit_of_measure": "milligrams", "extract_type_desc": "solid",
            "source_material": ""}]},
    )  # fmt: skip
    httpx_mock.add_response(
        url=_url("natural-licences/nonmedicinalingredient", r"id=3904641"),
        json=[{"lnhpd_id": 3904641, "ingredient_name": "Hypromellose"}],
    )
    httpx_mock.add_response(
        url=_url("natural-licences/productpurpose", r"id=3904641"),
        json={
            **wrapped,
            "data": [{"text_id": 1, "lnhpd_id": 3904641, "purpose": "Mild sedative."}],
        },
    )
    httpx_mock.add_response(
        url=_url("natural-licences/productrisk", r"id=3904641"),
        json={**wrapped, "data": [{"lnhpd_id": 3904641, "risk_id": 2,
              "risk_type_desc": "Contra-Indications", "sub_risk_type_desc": "",
              "risk_text": "Do not use if pregnant."}]},
    )  # fmt: skip
    httpx_mock.add_response(
        url=_url("natural-licences/productroute", r"id=3904641"),
        json=[{"lnhpd_id": 3904641, "route_id": 1, "route_type_desc": "Oral"}],
    )
    httpx_mock.add_response(
        url=_url("natural-licences/productdose", r"id=3904641"),
        json=[{"lnhpd_id": 3904641, "dose_id": 1, "population_type_desc": "Adults", "age": 0,
               "age_minimum": 18.0, "age_maximum": 0.0, "uom_type_desc_age": "",
               "quantity_dose": 1.0, "quantity_dose_minimum": 1.0, "quantity_dose_maximum": 2.0,
               "uom_type_desc_quantity_dose": "Capsule", "frequency": 3.0,
               "frequency_minimum": 0.0, "frequency_maximum": 0.0,
               "uom_type_desc_frequency": "daily"}],
    )  # fmt: skip
    detail = await lnhpd.get_product("NPN 80000035")
    assert [n.product_name for n in detail.names] == ["Easy-Mind", "Night-Cap"]
    ingredient = detail.medicinal_ingredients[0]
    assert (
        ingredient.extract_ratio == "4:1" and ingredient.dried_herb_equivalent == "400 milligrams"
    )
    assert detail.doses[0].dose == "1-2 Capsule" and detail.doses[0].frequency == "3 daily"
    assert detail.risks[0].text == "Do not use if pregnant."


async def test_unknown_npn_is_not_found(httpx_mock):
    httpx_mock.add_response(url=_url("natural-licences/productlicence", r"id=99999999"), json=[])
    with pytest.raises(NotFound):
        await lnhpd.get_product("99999999")
    with pytest.raises(InvalidInput):
        await lnhpd.get_product("abc")
    with pytest.raises(InvalidInput, match="n'est pas un NPN : donnez le numéro"):
        await lnhpd.get_product("abc", lang="fr")
    with pytest.raises(InvalidInput, match="au moins 3 caractères"):
        await lnhpd.search_products("ab", lang="fr")


def _device_licence(number, name, company_id, end=None, status="I", risk=3):
    return {
        "original_licence_no": number, "licence_status": status, "appl_risk_class": risk,
        "licence_name": name, "first_licence_status_dt": "2019-02-21",
        "last_refresh_dt": "2026-10-02", "end_date": end, "licence_type_cd": "S",
        "company_id": company_id, "licence_type_desc": "System",
    }  # fmt: skip


DEVICE_LICENCES = [
    _device_licence(102449, "DEXCOM G6 CONTINUOUS GLUCOSE MONITORING SYSTEM", 128860),
    _device_licence(1561, "FLOOD PHANTOM", 101500, end="2022-10-14", status="O", risk=2),
    _device_licence(103869, "T:SLIM X2 INSULIN PUMP", 146459),
]
COMPANIES = [
    {"company_id": 128860, "company_name": "DEXCOM, INC.", "addr_line_1": "6340 Sequence Drive",
     "addr_line_2": "", "addr_line_3": "", "postal_code": "92121-4356", "city": "San Diego",
     "country_cd": "US", "region_cd": "CA", "company_status": "A"},
    {"company_id": 101500, "company_name": "BIODEX MEDICAL SYSTEMS INC.", "addr_line_1": "20 Ramsey Road",
     "addr_line_2": "", "addr_line_3": "", "postal_code": "11967", "city": "Shirley",
     "country_cd": "US", "region_cd": "NY", "company_status": "A"},
]  # fmt: skip


def _tables(httpx_mock):
    httpx_mock.add_response(
        url=_url("medical-devices/licence", r"type=json&lang=en$"), json=DEVICE_LICENCES
    )
    httpx_mock.add_response(url=_url("medical-devices/company", r"type=json$"), json=COMPANIES)


async def test_licence_search_by_company_and_state(httpx_mock):
    _tables(httpx_mock)
    result = await mdall.search_licences(company="biodex", active_only=False, lang="fr")
    assert [lic.licence_number for lic in result.licences] == [1561]
    assert result.licences[0].status == "Abandonnée au renouvellement"
    assert result.licences[0].licence_type == "Système"
    assert "l'entreprise contient 'biodex'" in (result.provenance.coverage or "")
    assert (result.provenance.freshness or "") == "LIMH, mise à jour chaque jour par Santé Canada"
    with pytest.raises(InvalidInput, match="les instruments de classe I"):
        await mdall.search_licences(company="biodex", risk_class=1, lang="fr")
    active = await mdall.search_licences(company="biodex")
    assert active.total_matched == 0


async def test_licence_detail_keeps_identifiers_per_licence(httpx_mock):
    # Live: device 1048489 sits on two licences and deviceidentifier?id=
    # answers the rows of both; device?licence_number= is ignored.
    _tables(httpx_mock)
    devices = [
        {"original_licence_no": 102449, "device_id": 1003095, "first_licence_dt": "2019-02-21",
         "end_date": None, "trade_name": "DEXCOM G6 RECEIVER"},
        {"original_licence_no": 109685, "device_id": 1048489, "first_licence_dt": "2023-06-29",
         "end_date": None, "trade_name": "DEXCOM G7 APP"},
        {"original_licence_no": 102449, "device_id": 1048489, "first_licence_dt": "2020-01-01",
         "end_date": "2021-01-01", "trade_name": "DEXCOM G7 APP"},
    ]  # fmt: skip
    httpx_mock.add_response(
        url=_url("medical-devices/device", r"type=json$"), text=json.dumps(devices)
    )
    httpx_mock.add_response(
        url=_url("medical-devices/deviceidentifier", r"id=1003095"),
        json=[{"original_licence_no": 102449, "device_id": 1003095, "first_licence_dt": "2019-02-21",
               "end_date": None, "device_identifier": "STK-GS-113"}],
    )  # fmt: skip
    httpx_mock.add_response(
        url=_url("medical-devices/deviceidentifier", r"id=1048489"),
        json=[
            {"original_licence_no": 109685, "device_id": 1048489, "first_licence_dt": "2023-06-29",
             "end_date": None, "device_identifier": "SW12299"},
            {"original_licence_no": 102449, "device_id": 1048489, "first_licence_dt": "2020-01-01",
             "end_date": "2021-01-01", "device_identifier": "OLD-1"},
        ],
    )  # fmt: skip
    detail = await mdall.get_licence(102449)
    assert detail.device_count == 2
    assert [d.identifiers for d in detail.devices] == [["STK-GS-113"], ["OLD-1"]]
    assert detail.company is not None and detail.company.city == "San Diego"
    with pytest.raises(NotFound):
        await mdall.get_licence(99999999)


async def test_device_search_by_identifier_groups_rows(httpx_mock):
    httpx_mock.add_response(
        url=_url("medical-devices/deviceidentifier", r"device_identifier=STE-FT"),
        json=[{"original_licence_no": 115760, "device_id": 1087746, "first_licence_dt": "2026-07-10",
               "end_date": None, "device_identifier": "STE-FT-008"}],
    )  # fmt: skip
    httpx_mock.add_response(
        url=_url("medical-devices/device", r"id=1087746"),
        json={"original_licence_no": 115760, "device_id": 1087746, "first_licence_dt": "2026-07-10",
              "end_date": None, "trade_name": "DEXCOM G7 15 DAY SENSOR"},
    )  # fmt: skip
    result = await mdall.search_devices(identifier="STE-FT")
    assert result.devices[0].trade_name == "DEXCOM G7 15 DAY SENSOR"
    assert result.devices[0].identifiers == ["STE-FT-008"]
    with pytest.raises(InvalidInput):
        await mdall.search_devices(name="dexcom", identifier="STE")

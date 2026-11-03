"""Tests for modules/proactive_disclosure/client.py.

A small fake of open.canada.ca's datastore_search answers the POSTs, so the
tests see the request bodies the client really sends. Row shapes are the
live ones of 2026-11-03: every column is text (amounts too), dates are
ISO, owner_org_title is "English | French", an amendment restates the
agreement's total, and a page holds at most the server's own cap
(1,000 live; smaller here so paging is exercised).
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx
import pytest

from maplestats_mcp.modules.proactive_disclosure import client, constants
from maplestats_mcp.modules.proactive_disclosure.tools import (
    disclosure_search_contracts,
    disclosure_summarize,
)
from maplestats_mcp.shared.errors import InvalidInput, UpstreamError

SEARCH_URL = re.compile(r"https://open\.canada\.ca/data/api/3/action/datastore_search$")
PACKAGE_URL = re.compile(r"https://open\.canada\.ca/data/api/3/action/package_show\?.*")

DND = "National Defence | Défense nationale"
PCO = "Privy Council Office | Bureau du Conseil privé"


def _contract(_id: int, **values: Any) -> dict[str, Any]:
    row = {
        "_id": _id,
        "reference_number": f"C-2024-2025-Q1-{_id}",
        "procurement_id": f"P{_id}",
        "vendor_name": "ACME INC.",
        "vendor_postal_code": None,
        "buyer_name": None,
        "contract_date": "2024-05-01",
        "economic_object_code": "0491",
        "description_en": "Management consulting",
        "description_fr": "Conseils en gestion",
        "contract_period_start": "2024-05-01",
        "delivery_date": "2025-03-31",
        "contract_value": "100000.0",
        "original_value": "100000.0",
        "amendment_value": None,
        "comments_en": None,
        "comments_fr": None,
        "additional_comments_en": None,
        "additional_comments_fr": None,
        "commodity_type": "S",
        "commodity_code": "D302A",
        "country_of_vendor": "CA",
        "solicitation_procedure": "TN",
        "instrument_type": "C",
        "ministers_office": "N",
        "former_public_servant": "N",
        "number_of_bids": "1",
        "reporting_period": "2024-2025-Q1",
        "owner_org": "dnd-mdn",
        "owner_org_title": DND,
    }
    row.update(values)
    return row


class FakeDatastore:
    """Answers datastore_search like the portal: exact filters (lists are IN),
    per-column word matches for q, sort by one column, offset and a page cap."""

    def __init__(self, rows: list[dict[str, Any]], page_cap: int = 1000) -> None:
        self.rows = rows
        self.page_cap = page_cap
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        rows = list(self.rows)
        for column, wanted in (body.get("filters") or {}).items():
            allowed = wanted if isinstance(wanted, list) else [wanted]
            rows = [row for row in rows if row.get(column) in allowed]
        for column, words in (body.get("q") or {}).items():
            needed = words.lower().split()
            rows = [
                row
                for row in rows
                if all(word in str(row.get(column) or "").lower() for word in needed)
            ]
        sort = (body.get("sort") or "_id").split(",")[0].split()
        column, reverse = sort[0], len(sort) > 1 and sort[1] == "desc"
        # "nulls last" as the client asks: blank values after the others either way.
        present = sorted(
            (row for row in rows if row.get(column) is not None),
            key=lambda row: row[column],
            reverse=reverse,
        )
        rows = present + [row for row in rows if row.get(column) is None]
        total = len(rows)
        offset = int(body.get("offset", 0))
        limit = min(int(body.get("limit", 100)), self.page_cap)
        page = rows[offset : offset + limit]
        if body.get("fields"):
            page = [{k: row.get(k) for k in body["fields"]} for row in page]
        result: dict[str, Any] = {"records": page, "fields": [{"id": "_id", "type": "int"}]}
        if body.get("include_total", True):
            result["total"] = total
        return httpx.Response(200, json={"help": "h", "success": True, "result": result})


def _serve(httpx_mock, rows: list[dict[str, Any]], page_cap: int = 1000) -> FakeDatastore:
    fake = FakeDatastore(rows, page_cap)
    httpx_mock.add_callback(fake, url=SEARCH_URL, method="POST", is_reusable=True)
    return fake


# --------------------------------------------------------------------------
# Parsers and arguments


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("38900.25", 38900.25),
        ("464000", 464000.0),
        ("$1,200.50", 1200.5),
        ("-5000", -5000.0),
        ("", None),
        (None, None),
        ("null", None),
        ("n/a", None),
    ],
)
def test_money_reads_text_amounts(raw, expected):
    assert client.money(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2024-2025", 2024), ("2024-25", 2024), (2024, 2024), ("2024", 2024), (None, None)],
)
def test_fiscal_year_spellings(raw, expected):
    assert client.parse_fiscal_year(raw, "en") == expected


@pytest.mark.parametrize("raw", ["2024-2026", "FY24", "24-25", "1850"])
def test_bad_fiscal_year_is_invalid_input_with_a_fix(raw):
    with pytest.raises(InvalidInput, match="Fix: write it as 2024-2025"):
        client.parse_fiscal_year(raw, "en")


def test_contracts_fiscal_year_is_its_four_reporting_quarters():
    crit = client.build_criteria(constants.CONTRACTS, fiscal_year="2024-25")
    assert crit.filters["reporting_period"] == [f"2024-2025-Q{n}" for n in range(1, 5)]
    assert crit.shown["fiscal_year"] == "2024-2025"


def test_other_datasets_turn_a_fiscal_year_into_every_day_april_to_march():
    crit = client.build_criteria(constants.TRAVEL, fiscal_year=2025)
    days = crit.filters["start_date"]
    assert days[0] == "2025-04-01" and days[-1] == "2026-03-31" and len(days) == 365
    # A date range inside the fiscal year narrows it.
    crit = client.build_criteria(
        constants.TRAVEL, fiscal_year=2025, date_from="2025-06-01", date_to="2026-12-31"
    )
    assert crit.filters["start_date"][0] == "2025-06-01"
    assert crit.filters["start_date"][-1] == "2026-03-31"


def test_date_range_needs_both_bounds_and_order_and_a_bounded_span():
    with pytest.raises(InvalidInput, match="Give both date_from and date_to"):
        client.build_criteria(constants.CONTRACTS, date_from="2024-01-01")
    with pytest.raises(InvalidInput, match="is after"):
        client.build_criteria(constants.CONTRACTS, date_from="2025-01-01", date_to="2024-01-01")
    with pytest.raises(InvalidInput, match="Fix: split it"):
        client.build_criteria(constants.CONTRACTS, date_from="2000-01-01", date_to="2024-01-01")
    with pytest.raises(InvalidInput, match="YYYY-MM-DD"):
        client.build_criteria(constants.CONTRACTS, date_from="01/02/2024", date_to="2024-03-01")


def test_value_range_is_checked_and_kept_for_the_client_side_filter():
    with pytest.raises(InvalidInput, match="is after"):
        client.build_criteria(constants.GRANTS, min_value=10, max_value=5)
    crit = client.build_criteria(constants.GRANTS, min_value=10)
    assert crit.in_range(10.0) and not crit.in_range(9.99) and not crit.in_range(None)


def test_an_argument_with_no_column_is_refused_with_the_valid_ones():
    with pytest.raises(InvalidInput, match="program cannot filter contracts. Fix: drop it"):
        client.build_criteria(constants.CONTRACTS, program="Canada Summer Jobs")
    with pytest.raises(InvalidInput, match="province 'ZZ' is not a province"):
        client.build_criteria(constants.GRANTS, province="ZZ")


def test_criteria_map_to_columns_per_dataset_and_language():
    crit = client.build_criteria(
        constants.GRANTS,
        party="Carleton",
        program="Accessibility",
        riding="35075",
        agreement_type="contribution",
        owner_org=" WAGE ",
        lang="fr",
    )
    assert crit.q == {"recipient_legal_name": "Carleton", "prog_name_fr": "Accessibility"}
    assert crit.filters == {
        "owner_org": "wage",
        "federal_riding_number": "35075",
        "agreement_type": "C",
    }
    crit = client.build_criteria(
        constants.TRAVEL, party="McGuinty", title="Minister", disclosure_group="ministers"
    )
    assert crit.q == {"name": "McGuinty", "title_en": "Minister"}
    assert crit.filters == {"disclosure_group": "MPSES"}


# --------------------------------------------------------------------------
# Search


async def test_search_lets_the_portal_filter_sort_and_page(httpx_mock):
    fake = _serve(
        httpx_mock,
        [
            _contract(1, contract_date="2024-05-01"),
            _contract(2, contract_date=None),
            _contract(3, contract_date="2024-06-01", vendor_name="Other Ltd"),
        ],
    )
    result = await client.search_contracts(vendor="acme", fiscal_year="2024-2025", limit=10)
    body = fake.bodies[-1]
    assert body["resource_id"] == constants.CONTRACTS.resource_id
    assert body["q"] == {"vendor_name": "acme"}
    assert body["sort"] == "contract_date desc nulls last, _id desc"
    assert body["filters"]["reporting_period"][0] == "2024-2025-Q1"
    assert result.total_matched == 2 and result.rows_scanned == 0
    record = result.records[0]
    assert record.contract_value == 100000.0
    assert record.instrument_type_label == "Contract"
    assert record.solicitation_procedure_label == "Non-Competitive"
    assert record.department.owner_org == "dnd-mdn"
    assert record.department.name == "National Defence"
    assert record.ministers_office is False
    assert record.source.resource_id == constants.CONTRACTS.resource_id
    assert record.source.record_id == 1
    assert record.source.dataset_url == (
        "https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b"
    )
    assert result.provenance.source == "proactive-disclosure"
    assert "Open Government Licence - Canada" in (result.provenance.licence or "")
    assert result.provenance.commercial_use == "allowed"
    assert result.filters["vendor"] == "acme"


async def test_value_range_scans_narrow_columns_then_fetches_the_page_by_id(httpx_mock):
    rows = [
        _contract(1, contract_value="5000"),
        _contract(2, contract_value="250000.5"),
        _contract(3, contract_value="1,000,000"),
        _contract(4, contract_value=None),
        _contract(5, contract_value="99999"),
    ]
    fake = _serve(httpx_mock, rows, page_cap=2)
    result = await client.search_contracts(min_value=99_999, sort="value_desc", limit=2)
    scans = [b for b in fake.bodies if b.get("fields")]
    # Three pages of two: the first carries the total, the others do not ask for it.
    assert [b["offset"] for b in scans] == [0, 2, 4]
    assert scans[0]["fields"] == ["_id", "contract_date", "contract_value"]
    assert all(b.get("include_total") is False for b in scans[1:])
    assert fake.bodies[-1]["filters"] == {"_id": [3, 2]}
    assert [r.contract_value for r in result.records] == [1_000_000.0, 250000.5]
    assert result.total_matched == 3 and result.rows_scanned == 5


async def test_value_sort_with_no_range_puts_blank_values_last(httpx_mock):
    _serve(httpx_mock, [_contract(1, contract_value=None), _contract(2, contract_value="7")])
    result = await client.search_contracts(sort="value_asc", limit=5)
    assert [r.source.record_id for r in result.records] == [2, 1]


async def test_scan_refuses_more_rows_than_the_cap_with_a_fix(httpx_mock, monkeypatch):
    monkeypatch.setattr(constants, "SCAN_MAX_ROWS", 3)
    _serve(httpx_mock, [_contract(n) for n in range(1, 6)])
    with pytest.raises(InvalidInput, match="5 rows match these filters.*Fix: narrow"):
        await client.search_contracts(min_value=1)


async def test_search_limit_and_offset_are_checked():
    with pytest.raises(InvalidInput, match="limit must be between 1 and 100"):
        await client.search_contracts(limit=101)
    with pytest.raises(InvalidInput, match="offset must be >= 0"):
        await client.search_contracts(offset=-1)


async def test_french_call_reads_french_columns_and_errors(httpx_mock):
    _serve(httpx_mock, [_contract(1, owner_org="pco-bcp", owner_org_title=PCO)])
    result = await client.search_contracts(lang="fr")
    record = result.records[0]
    assert record.description == "Conseils en gestion"
    assert record.department.name == "Bureau du Conseil privé"
    assert record.instrument_type_label == "Marché"
    assert record.source.dataset_url.startswith("https://open.canada.ca/data/fr/dataset/")
    assert "Licence du gouvernement ouvert" in (result.provenance.licence or "")
    with pytest.raises(InvalidInput, match="Solution\xa0: écrivez"):
        await client.search_contracts(fiscal_year="vingt", lang="fr")


async def test_portal_validation_error_is_invalid_input(httpx_mock):
    httpx_mock.add_response(
        url=SEARCH_URL,
        method="POST",
        status_code=409,
        json={
            "help": "h",
            "success": False,
            "error": {"filters": ['invalid value "nope"'], "__type": "Validation Error"},
        },
    )
    with pytest.raises(InvalidInput, match="Validation Error"):
        await client.search_contracts()


async def test_portal_5xx_after_retries_names_the_status(httpx_mock):
    # shared/ckan.py's mapping, which scripts/_smoke_common.py reads as an outage.
    httpx_mock.add_response(
        url=SEARCH_URL, method="POST", status_code=503, text="Service Unavailable", is_reusable=True
    )
    with pytest.raises(UpstreamError, match="HTTP 503"):
        await client.search_travel(name="Anand")


async def test_travel_and_hospitality_records(httpx_mock):
    travel_row = {
        "_id": 7,
        "ref_number": "T-2025-P10-0004",
        "disclosure_group": "MPSES",
        "title_en": "Minister of National Defence",
        "title_fr": "Ministre de la Défense nationale",
        "name": "McGuinty David",
        "purpose_en": "NATO meetings",
        "purpose_fr": "Réunions de l'OTAN",
        "start_date": "2026-03-13",
        "end_date": "2026-03-16",
        "destination_en": "Oslo, Norway",
        "destination_fr": "Oslo, Norvège",
        "destination_2_en": "London, United Kingdom",
        "destination_2_fr": "Londres, Royaume-Uni",
        "destination_other_en": None,
        "destination_other_fr": None,
        "airfare": "0.0",
        "other_transport": "785.48",
        "lodging": "507.15",
        "meals": "355.2",
        "other_expenses": "0.0",
        "total": "1647.83",
        "owner_org": "dnd-mdn",
        "owner_org_title": DND,
    }
    _serve(httpx_mock, [travel_row])
    result = await client.search_travel(name="mcguinty", disclosure_group="ministers")
    trip = result.records[0]
    assert trip.destinations == ["Oslo, Norway", "London, United Kingdom"]
    assert trip.total == 1647.83 and trip.lodging == 507.15
    assert trip.disclosure_group_label is not None and "Minister" in trip.disclosure_group_label
    assert trip.source.resource_id == constants.TRAVEL.resource_id

    httpx_mock.reset()
    hospitality_row = {
        "_id": 9,
        "disclosure_group": "SLE",
        "title_en": "Deputy Minister",
        "title_fr": "Sous-ministre",
        "name": "Frances McRae",
        "description_en": "Planning session",
        "description_fr": "Séance de planification",
        "start_date": "2024-08-29",
        "location_en": "Gatineau, Quebec, Canada",
        "location_fr": "Gatineau, Québec, Canada",
        "vendor_en": "Subway",
        "vendor_fr": "Subway",
        "employee_attendees": "8",
        "guest_attendees": "0",
        "total": "60.93",
        "owner_org": "wage",
        "owner_org_title": "Women and Gender Equality Canada | Femmes et Égalité des genres Canada",
    }
    _serve(httpx_mock, [hospitality_row])
    result = await client.search_hospitality(vendor="subway", lang="fr")
    event = result.records[0]
    assert event.vendors == ["Subway"] and event.employee_attendees == 8
    assert event.title == "Sous-ministre" and event.location == "Gatineau, Québec, Canada"
    assert event.department.name == "Femmes et Égalité des genres Canada"


# --------------------------------------------------------------------------
# Summary


def _amended_contracts() -> list[dict[str, Any]]:
    """P1 amended twice (100k -> 150k -> 400k); P2 alone; a PCO contract."""
    return [
        _contract(1, procurement_id="P1", contract_value="100000", reporting_period="2024-2025-Q1"),
        _contract(
            2,
            procurement_id="P1",
            contract_value="150000",
            instrument_type="A",
            reporting_period="2024-2025-Q2",
        ),
        _contract(
            3,
            procurement_id="P1",
            contract_value="400000",
            instrument_type="A",
            reporting_period="2024-2025-Q4",
        ),
        _contract(4, procurement_id="P2", contract_value="50000", vendor_name="Acme Inc"),
        _contract(
            5,
            procurement_id="P1",
            contract_value="20000",
            owner_org="pco-bcp",
            owner_org_title=PCO,
            vendor_name="Garda",
        ),
    ]


async def test_summary_counts_each_contract_once_at_its_latest_value(httpx_mock):
    fake = _serve(httpx_mock, _amended_contracts(), page_cap=2)
    summary = await client.summarize(dataset="contracts", group_by="department")
    assert [(g.key, g.label, g.count, g.total_value) for g in summary.groups] == [
        ("dnd-mdn", "National Defence", 2, 450_000.0),
        ("pco-bcp", "Privy Council Office", 1, 20_000.0),
    ]
    assert summary.total_count == 3 and summary.total_value == 470_000.0
    assert summary.rows_scanned == 5
    assert summary.groups[0].share_percent == pytest.approx(95.74, abs=0.01)
    fields = fake.bodies[0]["fields"]
    assert set(fields) == {
        "_id",
        "contract_value",
        "owner_org",
        "owner_org_title",
        "procurement_id",
        "reporting_period",
    }
    assert "latest row" in summary.method


async def test_summary_all_rows_sums_amendments_as_published(httpx_mock):
    _serve(httpx_mock, _amended_contracts())
    summary = await client.summarize(
        dataset="contracts", group_by="department", value_mode="all_rows"
    )
    assert summary.total_count == 5 and summary.total_value == 720_000.0


async def test_summary_groups_vendor_spellings_and_folds_the_rest(httpx_mock):
    _serve(httpx_mock, _amended_contracts())
    summary = await client.summarize(dataset="contracts", group_by="vendor", top=1)
    # "ACME INC." and "Acme Inc" are one vendor; its label is the commoner spelling.
    assert summary.groups[0].key == "acme inc"
    assert summary.groups[0].label == "ACME INC."
    assert summary.groups[0].total_value == 450_000.0
    assert summary.other_groups == 1 and summary.other_value == 20_000.0


async def test_summary_by_fiscal_year_is_chronological(httpx_mock):
    rows = _amended_contracts() + [
        _contract(6, procurement_id="P9", reporting_period="2023-2024-Q3", contract_value="1")
    ]
    _serve(httpx_mock, rows)
    summary = await client.summarize(dataset="contracts", group_by="fiscal_year", top=1)
    assert [g.key for g in summary.groups] == ["2023-2024", "2024-2025"]
    assert summary.other_groups == 0


async def test_grants_keep_the_highest_amendment_number(httpx_mock):
    def grant(_id: int, amendment: str, value: str, province: str = "ON") -> dict[str, Any]:
        return {
            "_id": _id,
            "ref_number": "001-2022-2023-Q4-00003",
            "amendment_number": amendment,
            "agreement_value": value,
            "recipient_province": province,
            "owner_org": "wage",
            "owner_org_title": "Women and Gender Equality Canada | Femmes et Égalité des genres",
            "agreement_start_date": "2023-01-15",
        }

    rows = [grant(1, "0", "464000"), grant(2, "1", "702337.0"), grant(3, "10", "9")]
    rows.append({**grant(4, "0", "1000", "QC"), "ref_number": "001-2024-2025-Q1-1"})
    _serve(httpx_mock, rows)
    summary = await client.summarize(dataset="grants", group_by="province")
    # Amendment 10 outranks 1 as a number, not as text.
    assert [(g.key, g.count, g.total_value) for g in summary.groups] == [
        ("QC", 1, 1000.0),
        ("ON", 1, 9.0),
    ]


async def test_travel_names_in_either_order_are_one_person(httpx_mock):
    def trip(_id: int, name: str, total: str) -> dict[str, Any]:
        return {"_id": _id, "name": name, "total": total, "owner_org": "nrcan-rncan"}

    _serve(
        httpx_mock,
        [
            trip(1, "Hodgson, Tim", "100"),
            trip(2, "Tim  Hodgson", "50"),
            trip(3, "Tim Hodgson", "1"),
        ],
    )
    summary = await client.summarize(dataset="travel", group_by="name")
    assert len(summary.groups) == 1
    assert summary.groups[0].label == "Tim Hodgson"
    assert summary.groups[0].count == 3 and summary.groups[0].total_value == 151.0


async def test_summary_rejects_a_grouping_the_dataset_lacks():
    with pytest.raises(InvalidInput, match="travel cannot be grouped by 'program'. Fix"):
        await client.summarize(dataset="travel", group_by="program")
    with pytest.raises(InvalidInput, match="Unknown dataset"):
        await client.summarize(dataset="lobbying")
    with pytest.raises(InvalidInput, match="top must be between"):
        await client.summarize(dataset="travel", top=0)


async def test_rows_without_a_value_are_counted_not_summed(httpx_mock):
    _serve(httpx_mock, [_contract(1, contract_value="n/a"), _contract(2, contract_value="10")])
    summary = await client.summarize(dataset="contracts", value_mode="all_rows")
    assert summary.total_count == 2 and summary.rows_without_value == 1
    assert summary.total_value == 10.0


# --------------------------------------------------------------------------
# Dataset list and tools


async def test_list_datasets_flags_a_resource_that_left_its_package(httpx_mock):
    def package(request: httpx.Request) -> httpx.Response:
        package_id = request.url.params["id"]
        spec = next(s for s in constants.DATASETS.values() if s.dataset_id == package_id)
        resources = (
            []
            if spec.key == "hospitality"
            else [
                {
                    "id": spec.resource_id,
                    "datastore_active": "true",
                    "last_modified": "2026-11-02T06:54:35",
                }
            ]
        )
        return httpx.Response(200, json={"success": True, "result": {"resources": resources}})

    httpx_mock.add_callback(package, url=PACKAGE_URL, is_reusable=True)
    _serve(httpx_mock, [_contract(1)])
    listing = await client.list_datasets()
    by_key = {info.dataset: info for info in listing.datasets}
    assert set(by_key) == {"contracts", "grants", "travel", "hospitality"}
    assert by_key["contracts"].resource_in_package is True
    assert by_key["contracts"].datastore_active is True
    assert by_key["contracts"].row_count == 1
    assert by_key["hospitality"].resource_in_package is False
    assert by_key["grants"].search_page_url == "https://search.open.canada.ca/grants"


async def test_tools_pass_their_arguments_and_lang_through(httpx_mock):
    _serve(httpx_mock, _amended_contracts())
    result = await disclosure_search_contracts(vendor="garda", lang="fr")
    assert result.records[0].department.name == "Bureau du Conseil privé"
    summary = await disclosure_summarize(dataset="contracts", owner_org="pco-bcp")
    assert summary.total_value == 20_000.0


def test_days_lists_every_day_inclusive():
    assert client._days(date(2024, 2, 28), date(2024, 3, 1)) == [
        "2024-02-28",
        "2024-02-29",
        "2024-03-01",
    ]

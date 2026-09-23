"""Tests for canadabuys contract history and bulk-file listing, shaped
around the per-amendment row layout confirmed live 2026-09-22: one row
per amendment sharing a reference number, the original amount on
amendment 000, and the running total repeated on every row.
"""

from __future__ import annotations

import csv
import io

import pytest

from maple_data_mcp.modules.canadabuys import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput

_COLUMNS = [
    "referenceNumber-numeroReference",
    "contractNumber-numeroContrat",
    "amendmentNumber-numeroModification",
    "contractAwardDate-dateAttributionContrat",
    "amendmentDate-dateModification",
    "contractAmount-montantContrat",
    "totalContractValue-valeurTotaleContrat",
    "procurementCategory-categorieApprovisionnement",
    "title-titre-eng",
    "contractStatus-statutContrat-eng",
    "supplierLegalName-nomLegalFournisseur-eng",
    "supplierStandardizedName-nomNormaliseFournisseur-eng",
    "contractingEntityName-nomEntitContractante-eng",
    "unspscDescription-eng",
    "unrelatedColumn",
]


def _csv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in _COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def _row(reference: str, amendment: str, amount: str, total: str, **extra: str) -> dict[str, str]:
    return {
        "referenceNumber-numeroReference": reference,
        "amendmentNumber-numeroModification": amendment,
        "contractAmount-montantContrat": amount,
        "totalContractValue-valeurTotaleContrat": total,
        "procurementCategory-categorieApprovisionnement": "*SRV",
        **extra,
    }


_CONTRACTS = _csv(
    [
        _row(
            "CW1",
            "001",
            "9632.01",
            "8130192.29",
            **{
                "contractStatus-statutContrat-eng": "Amended",
                "title-titre-eng": "Translation services",
                "supplierLegalName-nomLegalFournisseur-eng": "Ubiqus Ottawa Inc.",
                "supplierStandardizedName-nomNormaliseFournisseur-eng": "Societe Gamma Inc",
                "contractingEntityName-nomEntitContractante-eng": "PSPC",
                "amendmentDate-dateModification": "2026-07-01",
            },
        ),
        _row(
            "CW1",
            "000",
            "7848302.00",
            "8130192.29",
            **{
                "contractAwardDate-dateAttributionContrat": "2026-05-13",
                "title-titre-eng": "Translation services",
                "unrelatedColumn": "dropped",
            },
        ),
        _row(
            "CW2",
            "000",
            "50000.00",
            "50000.00",
            **{
                "title-titre-eng": "Snow removal",
                "procurementCategory-categorieApprovisionnement": "*CNST",
                "supplierLegalName-nomLegalFournisseur-eng": "Plow Co",
                "contractingEntityName-nomEntitContractante-eng": "Parks Canada",
            },
        ),
    ]
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    cache_module._caches.clear()
    monkeypatch.setattr(client, "current_fiscal_year", lambda today=None: "2026-2027")
    yield


def _url(year: str = "2026-2027") -> str:
    return constants.CONTRACTS_URL_TEMPLATE.format(fiscal_year=year)


async def test_search_contracts_merges_amendments(httpx_mock):
    httpx_mock.add_response(url=_url(), content=_CONTRACTS)
    result = await client.search_contracts()
    assert result.total_contracts == 2
    merged = result.contracts[0]
    assert merged.reference_number == "CW1"
    assert merged.original_amount == 7848302.0
    assert merged.total_contract_value == 8130192.29
    assert merged.amendment_count == 1
    assert merged.award_date == "2026-05-13"
    assert merged.status == "Amended"
    assert merged.latest_amendment_date == "2026-07-01"


async def test_search_contracts_supplier_matches_standardized_name(httpx_mock):
    httpx_mock.add_response(url=_url(), content=_CONTRACTS)
    result = await client.search_contracts(supplier="gamma")
    assert [c.reference_number for c in result.contracts] == ["CW1"]


async def test_search_contracts_filters_value_category_buyer(httpx_mock):
    httpx_mock.add_response(url=_url(), content=_CONTRACTS)
    assert (await client.search_contracts(min_value=1_000_000)).total_matched == 1
    construction = await client.search_contracts(category="construction", buyer="parks")
    assert [c.reference_number for c in construction.contracts] == ["CW2"]


async def test_search_contracts_query_matches_title(httpx_mock):
    httpx_mock.add_response(url=_url(), content=_CONTRACTS)
    result = await client.search_contracts("snow")
    assert [c.reference_number for c in result.contracts] == ["CW2"]


async def test_search_contracts_accepts_old_and_partial_years(httpx_mock):
    httpx_mock.add_response(url=_url("2009-2010"), content=_CONTRACTS)
    httpx_mock.add_response(url=_url("2009-jan-Mar"), content=_CONTRACTS)
    assert (await client.search_contracts(fiscal_year="2009-2010")).fiscal_year == "2009-2010"
    assert (await client.search_contracts(fiscal_year="2009-jan-Mar")).total_contracts == 2


@pytest.mark.parametrize("year", ["2008-2009", "2027-2028", "2009-jan-mar", "2015"])
async def test_search_contracts_rejects_bad_fiscal_year(year):
    with pytest.raises(InvalidInput):
        await client.search_contracts(fiscal_year=year)


async def test_list_bulk_files_reports_sizes(httpx_mock):
    for _title, name in constants.BULK_FILES.values():
        httpx_mock.add_response(
            method="HEAD",
            url=f"{constants.BASE_URL}/{name}",
            headers={"content-length": "558413231", "last-modified": "Fri, 28 Aug 2026"},
        )
    result = await client.list_bulk_files()
    assert len(result.files) == len(constants.BULK_FILES)
    assert result.files[0].size_bytes == 558413231
    assert result.files[0].url.startswith(constants.BASE_URL)

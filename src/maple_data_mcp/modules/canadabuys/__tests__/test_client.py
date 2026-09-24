"""Tests for canadabuys/client.py, shaped around the real CSV layout
confirmed live 2026-09-22: UTF-8 with BOM, bilingual `-eng`/`-fra`
column pairs, `*A\\n*B` multi-value cells, HTML in descriptions, and
`0.00` meaning an unreported total contract value (see client.py).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest

from maple_data_mcp.modules.canadabuys import client, constants
from maple_data_mcp.shared import cache as cache_module
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError

_TENDER_COLUMNS = [
    "title-titre-eng",
    "title-titre-fra",
    "referenceNumber-numeroReference",
    "amendmentNumber-numeroModification",
    "solicitationNumber-numeroSollicitation",
    "publicationDate-datePublication",
    "tenderClosingDate-appelOffresDateCloture",
    "tenderStatus-appelOffresStatut-eng",
    "tenderStatus-appelOffresStatut-fra",
    "procurementCategory-categorieApprovisionnement",
    "regionsOfDelivery-regionsLivraison-eng",
    "regionsOfDelivery-regionsLivraison-fra",
    "contractingEntityName-nomEntitContractante-eng",
    "contractingEntityName-nomEntitContractante-fra",
    "tenderDescription-descriptionAppelOffres-eng",
    "tenderDescription-descriptionAppelOffres-fra",
]
_AWARD_COLUMNS = [
    "title-titre-eng",
    "title-titre-fra",
    "referenceNumber-numeroReference",
    "publicationDate-datePublication",
    "contractAmount-montantContrat",
    "totalContractValue-valeurTotaleContrat",
    "procurementCategory-categorieApprovisionnement",
    "supplierLegalName-nomLegalFournisseur-eng",
    "supplierLegalName-nomLegalFournisseur-fra",
    "contractingEntityName-nomEntitContractante-eng",
    "contractingEntityName-nomEntitContractante-fra",
    "awardDescription-descriptionAttribution-eng",
    "awardDescription-descriptionAttribution-fra",
]


def _csv(columns: list[str], rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue().encode("utf-8-sig")


_TENDERS = _csv(
    _TENDER_COLUMNS,
    [
        {
            "title-titre-eng": "Snow and Ice Control Services CFB North Bay",
            "title-titre-fra": "Services de déneigement BFC North Bay",
            "referenceNumber-numeroReference": "WS1",
            "tenderClosingDate-appelOffresDateCloture": "2099-10-30T14:00:00",
            "tenderStatus-appelOffresStatut-eng": "Open",
            "procurementCategory-categorieApprovisionnement": "*SRV",
            "regionsOfDelivery-regionsLivraison-eng": "*Ontario (except NCR)",
            "contractingEntityName-nomEntitContractante-eng": "PSPC",
            "tenderDescription-descriptionAppelOffres-eng": "\r\n\t<p>Snow&nbsp;removal</p>",
        },
        {
            "title-titre-eng": "Welding Shop Ventilation, Halifax",
            "referenceNumber-numeroReference": "MX-2",
            "tenderClosingDate-appelOffresDateCloture": "2099-10-01T14:00:00",
            "procurementCategory-categorieApprovisionnement": "*CNST\n*SRV",
            "regionsOfDelivery-regionsLivraison-eng": "*Nova Scotia",
            "contractingEntityName-nomEntitContractante-eng": "Defence Construction Canada",
        },
    ],
)
_AWARDS = _csv(
    _AWARD_COLUMNS,
    [
        {
            "title-titre-eng": "Supply Diesel Exhaust Fluid",
            "referenceNumber-numeroReference": "MX-444028039551",
            "publicationDate-datePublication": "2026-05-19",
            "contractAmount-montantContrat": "2000000.00",
            "totalContractValue-valeurTotaleContrat": "0.00",
            "procurementCategory-categorieApprovisionnement": "*GD",
            "supplierLegalName-nomLegalFournisseur-eng": "Irving Oil Limited",
            "contractingEntityName-nomEntitContractante-eng": "Marine Atlantic",
        },
        {
            "title-titre-eng": "Translation services",
            "referenceNumber-numeroReference": "CW2",
            "publicationDate-datePublication": "2026-06-01",
            "contractAmount-montantContrat": "50000.00",
            "procurementCategory-categorieApprovisionnement": "*SRV",
            "supplierLegalName-nomLegalFournisseur-eng": "Traduction Zenith",
            "contractingEntityName-nomEntitContractante-eng": "PSPC",
        },
    ],
)


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_module._caches.clear()
    yield


@pytest.fixture
def _fiscal_2026(monkeypatch):
    # Pin "today" so tests relying on the default fiscal year don't
    # change meaning when the real calendar rolls over on April 1.
    monkeypatch.setattr(client, "current_fiscal_year", lambda today=None: "2026-2027")


def _awards_url(year: str = "2026-2027") -> str:
    return constants.AWARDS_URL_TEMPLATE.format(fiscal_year=year)


async def test_search_tenders_parses_and_sorts_soonest_closing_first(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders()
    assert result.total_notices == 2
    assert [t.reference_number for t in result.tenders] == ["MX-2", "WS1"]
    assert result.tenders[0].procurement_categories == ["CNST", "SRV"]


async def test_open_tenders_leave_out_notices_past_closing(httpx_mock):
    stale = _csv(
        _TENDER_COLUMNS,
        [
            {
                "referenceNumber-numeroReference": "OLD",
                "tenderClosingDate-appelOffresDateCloture": "2023-07-12T10:00:00",
            },
            {
                "referenceNumber-numeroReference": "NEW",
                "tenderClosingDate-appelOffresDateCloture": "2099-01-01T10:00:00",
            },
            {"referenceNumber-numeroReference": "UNDATED"},
        ],
    )
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=stale)
    result = await client.search_tenders()
    assert [t.reference_number for t in result.tenders] == ["NEW", "UNDATED"]
    assert "1 notices past their closing date" in (result.provenance.limits or "")


async def test_search_tenders_cleans_html_description(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders("snow")
    assert result.tenders[0].description == "Snow removal"


async def test_search_tenders_requires_every_query_term(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders("snow halifax")
    assert result.total_matched == 0


async def test_search_tenders_filters_category_region_buyer(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders(
        category="construction", region="nova scotia", buyer="defence"
    )
    assert [t.reference_number for t in result.tenders] == ["MX-2"]


async def test_search_tenders_french_falls_back_to_english_when_blank(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders(lang="fr")
    titles = {t.reference_number: t.title for t in result.tenders}
    assert titles["WS1"] == "Services de déneigement BFC North Bay"
    assert titles["MX-2"] == "Welding Shop Ventilation, Halifax"


async def test_search_tenders_new_set_uses_new_file(httpx_mock):
    httpx_mock.add_response(url=constants.NEW_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders(notice_set="new")
    assert result.notice_set == "new"


async def test_search_tenders_truncates_and_sets_coverage(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    result = await client.search_tenders(limit=1)
    assert result.returned_count == 1
    assert result.provenance.coverage is not None
    assert "1 of 2" in result.provenance.coverage


async def test_search_awards_filters_supplier_and_sorts_newest_first(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=_awards_url(), content=_AWARDS)
    result = await client.search_awards()
    assert [a.reference_number for a in result.awards] == ["CW2", "MX-444028039551"]
    irving = await client.search_awards(supplier="IRVING")
    assert irving.total_matched == 1


async def test_search_awards_zero_total_value_is_none(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=_awards_url(), content=_AWARDS)
    result = await client.search_awards(supplier="irving")
    award = result.awards[0]
    assert award.contract_amount == 2000000.0
    assert award.total_contract_value is None


async def test_search_awards_uses_requested_fiscal_year(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=_awards_url("2022-2023"), content=_AWARDS)
    result = await client.search_awards(fiscal_year="2022-2023")
    assert result.fiscal_year == "2022-2023"


@pytest.mark.parametrize("year", ["2021-2022", "2027-2028", "2025-2027", "2025"])
async def test_search_awards_rejects_bad_fiscal_year(year, _fiscal_2026):
    with pytest.raises(InvalidInput):
        await client.search_awards(fiscal_year=year)


async def test_get_notice_finds_open_tender_with_full_description(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    detail = await client.get_notice("WS1")
    assert detail.notice_kind == "tender"
    assert detail.tender is not None
    assert detail.tender.description == "Snow removal"


async def test_get_notice_falls_back_to_previous_year_awards(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    httpx_mock.add_response(url=_awards_url(), content=_csv(_AWARD_COLUMNS, []))
    httpx_mock.add_response(url=_awards_url("2025-2026"), content=_AWARDS)
    detail = await client.get_notice("CW2")
    assert detail.notice_kind == "award"
    assert detail.provenance.url == _awards_url("2025-2026")


async def test_get_notice_missing_raises_not_found(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=_TENDERS)
    httpx_mock.add_response(url=_awards_url(), content=_AWARDS)
    httpx_mock.add_response(url=_awards_url("2025-2026"), content=_AWARDS)
    with pytest.raises(NotFound):
        await client.get_notice("nope")


async def test_missing_file_raises_not_found(httpx_mock, _fiscal_2026):
    httpx_mock.add_response(url=_awards_url(), status_code=404)
    with pytest.raises(NotFound):
        await client.search_awards()


async def test_unexpected_columns_raise_upstream_error(httpx_mock):
    httpx_mock.add_response(url=constants.OPEN_TENDERS_URL, content=b"a,b\n1,2\n")
    with pytest.raises(UpstreamError):
        await client.search_tenders()


@pytest.mark.parametrize(
    "kwargs",
    [{"lang": "de"}, {"limit": 0}, {"category": "food"}, {"notice_set": "closed"}],
)
async def test_search_tenders_invalid_input(kwargs):
    with pytest.raises(InvalidInput):
        await client.search_tenders(**kwargs)


def test_current_fiscal_year_rolls_over_on_april_first():
    assert client.current_fiscal_year(datetime(2026, 3, 31, tzinfo=UTC)) == "2025-2026"
    assert client.current_fiscal_year(datetime(2026, 4, 1, tzinfo=UTC)) == "2026-2027"

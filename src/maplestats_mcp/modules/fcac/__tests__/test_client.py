"""Tests for the FCAC comparison-tool client.

Fixtures are live pages captured 2026-09-26 and trimmed to the WebForms
form (scripts, Canada.ca chrome and most of the view state removed):
Ontario secured credit cards (25 cards over 3 result pages) with one
detail page, Ontario USD cards in French (5 cards) with a detail,
Alberta USD savings accounts (6) with a detail, and the first page of
Ontario chequing accounts in French (61 accounts) with a detail.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from bs4 import BeautifulSoup

from maplestats_mcp.modules.fcac import client
from maplestats_mcp.shared import cache as cache_module
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable

_FIX = Path(__file__).parent / "fixtures"
_BASE = "https://itools-ioutils.fcac-acfc.gc.ca/"
_P = "ctl00$ctl00$MainContent$MainContent$"


def _page(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode())


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_module._caches.clear()
    yield


def _search(httpx_mock, tool: str, lang: str, filter_page: str, first_results: str) -> None:
    """GET the filter page, POST the search, follow the 302 to the results."""
    httpx_mock.add_response(url=f"{_BASE}{tool}/SearchFilter-{lang}.aspx", text=_page(filter_page))
    httpx_mock.add_response(
        url=f"{_BASE}{tool}/SearchFilter-{lang}.aspx?lang={lang}",
        method="POST",
        status_code=302,
        headers={"Location": f"/{tool}/SearchResult-{lang}.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}{tool}/SearchResult-{lang}.aspx", text=_page(first_results)
    )


def _secured_cards(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx", text=_page("cards_filter_en.html")
    )
    # "Show more optional filters" re-renders the filter page in place.
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx?lang=eng",
        method="POST",
        text=_page("cards_more_filters_en.html"),
    )
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx?lang=eng",
        method="POST",
        status_code=302,
        headers={"Location": "/CCCT-OCCC/SearchResult-eng.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchResult-eng.aspx", text=_page("cards_secured_p1_en.html")
    )
    for page in (2, 3):
        httpx_mock.add_response(
            url=f"{_BASE}CCCT-OCCC/SearchResult-eng.aspx?lang=eng",
            method="POST",
            text=_page(f"cards_secured_p{page}_en.html"),
        )


# ------------------------------------------------------------------ parsing


def test_numbers_follow_each_languages_separators():
    assert client._numbers("$6,000.00 minimum balance", "en") == [6000.0]
    assert client._numbers("6 000,00 $ Solde minimum", "fr") == [6000.0]
    assert client._numbers("150 000,00 $", "fr") == [150000.0]
    assert client._rates("21.9000% - 29.9000% Purchase interest rate", "en") == [21.9, 29.9]
    assert client._rates("10,9000 % Taux d’intérêt", "fr") == [10.9]


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("No annual fee", "en", 0.0),
        ("Aucun frais annuel", "fr", 0.0),
        ("Sans frais", "fr", 0.0),
        ("None", "en", 0.0),
        ("$599.00 annual fee", "en", 599.0),
        ("599,00 $ Frais annuels", "fr", 599.0),
        ("Not required", "en", None),
        ("Non requis", "fr", None),
    ],
)
def test_amount_reads_fees_and_no_fee_wording(text, lang, expected):
    assert client._amount(text, lang) == expected


def test_section_keys_do_not_depend_on_language():
    assert client._section_key("MainContent_MainContent_lblInteresrRateTitle") == "interest_rate"
    assert client._section_key("MainContent_MainContent_lblNSFFeesTitle") == "nsf_fees"
    assert client._section_key("MainContent_MainContent_lblCurrencyNameTitle") == "currency"
    assert client._section_key("MainContent_MainContent_Label1") == "account_history"
    assert (
        client._section_key("MainContent_MainContent_lblForeignConversionFee")
        == "foreign_conversion_fee"
    )


def test_pager_follows_next_number_then_ellipsis():
    def pager(inner: str) -> BeautifulSoup:
        return BeautifulSoup(
            f'<span id="MainContent_MainContent_lvSearchResult_dpSearchResult">{inner}</span>',
            "html.parser",
        )

    def link(target: str, label: str) -> str:
        return (
            f'<a class="btn btn-default" href="javascript:__doPostBack('
            f"'{target}','')\">{label}</a>"
        )

    middle = pager(link("p1", "1") + '<span class="btn btn-primary">2</span>' + link("p3", "3"))
    assert client._next_page_target(middle) == "p3"
    # Page 5 of a block of five: the next block is behind the trailing "...".
    end_of_block = pager(
        link("prev", "...")
        + link("p4", "4")
        + '<span class="btn btn-primary">5</span>'
        + link("next", "...")
    )
    assert client._next_page_target(end_of_block) == "next"
    last = pager(link("p1", "1") + '<span class="btn btn-primary">2</span>')
    assert client._next_page_target(last) is None


def test_french_account_rows_flag_low_cost_accounts():
    soup = BeautifulSoup(_page("accounts_chequing_p1_fr.html"), "html.parser")
    assert client._result_count(soup) == 61
    rows = [client._account_summary(r, "fr") for r in client._rows(soup)]
    assert len(rows) == 10
    tangerine = rows[0]
    assert tangerine.name == "Compte-chèques Tangerine" and tangerine.low_cost_no_cost
    assert tangerine.monthly_fee == 0.0 and tangerine.monthly_fee_text == "0,00 $ Frais mensuels"
    assert tangerine.transactions == ["Opérations combinées illimitées"]
    assert any(not r.low_cost_no_cost for r in rows)


# ---------------------------------------------------------------- searches


async def test_search_walks_every_page_and_posts_the_filters(httpx_mock):
    _secured_cards(httpx_mock)
    result = await client.search_credit_cards("ON", secured=True, limit=200)

    assert result.total_listed == 25 and result.total_matched == 25
    assert len({c.product_id for c in result.cards}) == 25
    first = result.cards[0]
    assert first.name == "moi RBC Visa" and first.institution == "Royal Bank of Canada"
    assert first.annual_fee == 0.0 and first.purchase_rate == 20.99
    assert first.rewards == ["Groceries", "Gas", "General merchandise"]

    posts = [r for r in httpx_mock.get_requests() if r.method == "POST"]
    more, search, page2, page3 = (_form(r) for r in posts)
    assert _P + "btnShowMoreFilters" in more
    assert search[_P + "ddlProvince"] == ["7"] and search[_P + "rblCurrency"] == ["14"]
    assert search[_P + "rblLookingForSecuredCard"] == ["Yes"]
    assert search[_P + "rblAreYouaStudent"] == ["No"]
    assert _P + "btnSearch" in search and "__VIEWSTATE" in search
    assert page2["__EVENTTARGET"] == [_P + "lvSearchResult$dpSearchResult$ctl00$ctl01"]
    assert page3["__EVENTTARGET"][0].startswith(_P + "lvSearchResult$dpSearchResult")


async def test_search_is_cached_and_filters_locally(httpx_mock):
    _secured_cards(httpx_mock)
    await client.search_credit_cards("ON", secured=True)
    cash = await client.search_credit_cards(
        "ON", secured=True, rewards=["cash_back"], sort="name", limit=5
    )
    assert cash.provenance.cached
    assert cash.total_listed == 25 and 0 < cash.total_matched < 25
    assert all("Cash back" in c.rewards for c in cash.cards)
    assert [c.name for c in cash.cards] == sorted((c.name for c in cash.cards), key=str.casefold)
    bmo = await client.search_credit_cards("ON", secured=True, institution="bmo montreal")
    assert bmo.total_matched and all(c.institution == "BMO Bank of Montreal" for c in bmo.cards)
    cheap = await client.search_credit_cards("ON", secured=True, max_purchase_rate=20.99)
    assert all(c.purchase_rate is not None and c.purchase_rate <= 20.99 for c in cheap.cards)


async def test_french_search_reads_french_numbers_and_accents(httpx_mock):
    _search(httpx_mock, "CCCT-OCCC", "fra", "cards_filter_fr.html", "cards_usd_fr.html")
    result = await client.search_credit_cards(
        "ON", currency="USD", lang="fr", query="montreal", limit=5
    )
    assert result.total_listed == 5 and result.total_matched == 1
    bmo = result.cards[0]
    assert bmo.institution == "BMO Banque de Montréal"
    assert bmo.annual_fee == 49.0 and bmo.purchase_rate == 21.99 and bmo.currency == "USD"
    assert result.provenance.url.endswith("CCCT-OCCC/SearchFilter-fra.aspx")
    search = _form(next(r for r in httpx_mock.get_requests() if r.method == "POST"))
    assert search[_P + "rblCurrency"] == ["15"]
    assert _P + "rblLookingForSecuredCard" not in search  # no optional-filters step


async def test_savings_search_reads_interest_rates_and_groups(httpx_mock):
    _search(httpx_mock, "ACT-OCC", "eng", "accounts_filter_en.html", "accounts_usd_savings_en.html")
    result = await client.search_bank_accounts(
        "AB", account_type="savings", currency="USD", groups=["student", "senior"]
    )
    assert result.total_listed == 6 and result.groups == ["senior", "student"]
    rbc = result.accounts[0]
    assert rbc.name == "RBC US Investment Savings Account" and rbc.interest_rate == 3.15
    assert rbc.monthly_fee is None and rbc.currency == "USD"
    assert rbc.transactions == [
        "Unlimited in-branch transactions",
        "Not available for self-serve transactions",
    ]
    search = _form(next(r for r in httpx_mock.get_requests() if r.method == "POST"))
    assert search[_P + "ddlProvince"] == ["10"] and search[_P + "rblAccountType"] == ["2"]
    assert search[_P + "rblCurrency"] == ["4"]
    assert search[_P + "cblDemographic$0"] == ["25"] and search[_P + "cblDemographic$4"] == ["30"]


async def test_short_walk_raises_and_is_not_cached(httpx_mock):
    short = _page("accounts_usd_savings_en.html").replace(
        "6 results match your filters", "7 results match your filters"
    )
    for _ in range(2):
        httpx_mock.add_response(
            url=f"{_BASE}ACT-OCC/SearchFilter-eng.aspx", text=_page("accounts_filter_en.html")
        )
        httpx_mock.add_response(
            url=f"{_BASE}ACT-OCC/SearchFilter-eng.aspx?lang=eng",
            method="POST",
            status_code=302,
            headers={"Location": "/ACT-OCC/SearchResult-eng.aspx"},
        )
        httpx_mock.add_response(url=f"{_BASE}ACT-OCC/SearchResult-eng.aspx", text=short)
        with pytest.raises(UpstreamError, match="reported 7 products but 6"):
            await client.search_bank_accounts("AB", account_type="savings", currency="USD")


async def test_lost_session_is_retried_once_in_a_new_session(httpx_mock):
    httpx_mock.add_response(
        url=f"{_BASE}ACT-OCC/SearchFilter-eng.aspx", text=_page("accounts_filter_en.html")
    )
    httpx_mock.add_response(
        url=f"{_BASE}ACT-OCC/SearchFilter-eng.aspx?lang=eng",
        method="POST",
        status_code=302,
        headers={"Location": "/ACT-OCC/Error.aspx?aspxerrorpath=/ACT-OCC/SearchFilter.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}ACT-OCC/Error.aspx?aspxerrorpath=/ACT-OCC/SearchFilter.aspx",
        text="<html>error</html>",
    )
    _search(httpx_mock, "ACT-OCC", "eng", "accounts_filter_en.html", "accounts_usd_savings_en.html")
    result = await client.search_bank_accounts("AB", account_type="savings", currency="USD")
    assert result.total_listed == 6


async def test_lost_session_twice_raises(httpx_mock):
    for _ in range(2):
        httpx_mock.add_response(
            url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx", text=_page("cards_filter_en.html")
        )
        httpx_mock.add_response(
            url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx?lang=eng",
            method="POST",
            status_code=302,
            headers={"Location": "/CCCT-OCCC/SessionExpired-eng.aspx"},
        )
        httpx_mock.add_response(
            url=f"{_BASE}CCCT-OCCC/SessionExpired-eng.aspx", text="<html>expired</html>"
        )
    with pytest.raises(UpstreamError, match="lost the search session twice"):
        await client.search_credit_cards("ON")


async def test_server_errors_become_typed_errors(httpx_mock):
    httpx_mock.add_response(url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx", status_code=503)
    httpx_mock.add_response(url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx", status_code=503)
    httpx_mock.add_response(url=f"{_BASE}CCCT-OCCC/SearchFilter-eng.aspx", status_code=503)
    with pytest.raises(UpstreamError, match="HTTP 503"):
        await client.search_credit_cards("ON")
    for _ in range(3):
        httpx_mock.add_exception(httpx.ConnectTimeout("slow"))
    with pytest.raises(UpstreamUnavailable):
        await client.search_bank_accounts("ON")


# ------------------------------------------------------------------ details


async def test_card_detail_opens_the_row_on_its_page(httpx_mock):
    _secured_cards(httpx_mock)  # for the listing check
    _secured_cards(httpx_mock)  # the detail session walks to page 3
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchResult-eng.aspx?lang=eng",
        method="POST",
        status_code=302,
        headers={"Location": "/CCCT-OCCC/ProductDetail-eng.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/ProductDetail-eng.aspx", text=_page("card_detail_en.html")
    )
    card = await client.get_credit_card("7C9FDB48-9220-4EAD-B6A3-7E2D011FACAC", "ON", secured=True)
    assert card.product_id == "7c9fdb48-9220-4ead-b6a3-7e2d011facac"
    assert card.name == "BMO CashBack World Elite Mastercard"
    assert card.annual_fee == 139.0 and card.annual_fee_additional_card == 50.0
    assert (card.purchase_rate, card.cash_advance_rate, card.balance_transfer_rate) == (
        21.99,
        23.99,
        23.99,
    )
    assert card.foreign_conversion_fee == 2.5
    assert card.minimum_personal_income == 80000.0 and card.minimum_household_income == 150000.0
    assert card.rewards == ["Cash back", "Groceries", "Gas"]
    insurance = next(s for s in card.sections if s.key == "insurance_options")
    assert insurance.items and all(i.label for i in insurance.items)
    click = _form([r for r in httpx_mock.get_requests() if r.method == "POST"][-1])
    assert _P + "lvSearchResult$ctrl0$btnViewItemDetail" in click


async def test_french_card_detail(httpx_mock):
    _search(httpx_mock, "CCCT-OCCC", "fra", "cards_filter_fr.html", "cards_usd_fr.html")
    _search(httpx_mock, "CCCT-OCCC", "fra", "cards_filter_fr.html", "cards_usd_fr.html")
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/SearchResult-fra.aspx?lang=fra",
        method="POST",
        status_code=302,
        headers={"Location": "/CCCT-OCCC/ProductDetail-fra.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}CCCT-OCCC/ProductDetail-fra.aspx", text=_page("card_detail_fr.html")
    )
    card = await client.get_credit_card(
        "867e43e2-a87f-4485-b265-cc57190dc707", "ON", currency="USD", lang="fr"
    )
    assert card.name == "Carte Visa* TD Dollars US" and card.currency == "USD"
    assert card.annual_fee == 39.0 and card.annual_fee_additional_card == 0.0  # "Sans frais"
    assert card.cash_advance_rate == 22.99 and card.balance_transfer_rate is None
    assert card.minimum_personal_income is None and card.minimum_household_income == 35000.0
    rates = next(s for s in card.sections if s.key == "interest_rate")
    assert rates.title == "Taux d’intérêt" and rates.items[2].value == "Non disponible"


async def test_account_details_in_both_languages(httpx_mock):
    _search(httpx_mock, "ACT-OCC", "eng", "accounts_filter_en.html", "accounts_usd_savings_en.html")
    _search(httpx_mock, "ACT-OCC", "eng", "accounts_filter_en.html", "accounts_usd_savings_en.html")
    httpx_mock.add_response(
        url=f"{_BASE}ACT-OCC/SearchResult-eng.aspx?lang=eng",
        method="POST",
        status_code=302,
        headers={"Location": "/ACT-OCC/ProductDetail-eng.aspx"},
    )
    httpx_mock.add_response(
        url=f"{_BASE}ACT-OCC/ProductDetail-eng.aspx", text=_page("account_savings_detail_en.html")
    )
    savings = await client.get_bank_account(
        "0b59d9e5-02b5-44ec-8ddc-30babf21ecfd", "AB", account_type="savings", currency="USD"
    )
    assert savings.account_type == "savings" and savings.monthly_fee == 0.0
    assert savings.interest_rates == ["3.1500% $0.00 - Unlimited"]
    assert savings.nsf_fee is None
    assert [i.label for i in savings.included_transactions] == ["In-branch", "Self - serve"]
    click = _form([r for r in httpx_mock.get_requests() if r.method == "POST"][-1])
    # Savings rows name their button btnViewItemDetailSavings.
    assert _P + "lvSavingsAccountResult$ctrl0$btnViewItemDetailSavings" in click

    soup = BeautifulSoup(_page("account_chequing_detail_fr.html"), "html.parser")
    sections = client._sections(soup)
    chequing = client._account_detail("x", sections, "fr")
    assert chequing["name"] == "Compte-chèques Tangerine" and chequing["nsf_fee"] == 10.0
    assert len(chequing["interest_rates"]) == 3
    withdraw = next(s for s in sections if s.key == "withdraw_fees")
    assert ("GAB - autres institutions", "1,50 $") in [(i.label, i.value) for i in withdraw.items]


async def test_detail_for_unlisted_product_is_not_found(httpx_mock):
    _search(httpx_mock, "ACT-OCC", "eng", "accounts_filter_en.html", "accounts_usd_savings_en.html")
    with pytest.raises(NotFound, match="pass the options used in the search"):
        await client.get_bank_account(
            "00000000-0000-0000-0000-000000000000", "AB", account_type="savings", currency="USD"
        )


@pytest.mark.parametrize(
    "call",
    [
        lambda: client.search_credit_cards("XX"),
        lambda: client.search_credit_cards("ON", currency="EUR"),
        lambda: client.search_credit_cards("ON", limit=0),
        lambda: client.search_credit_cards("ON", sort="cheapest"),
        lambda: client.search_credit_cards("ON", rewards=["points"]),
        lambda: client.search_bank_accounts("ON", account_type="tfsa"),
        lambda: client.search_bank_accounts("ON", groups=["veteran"]),
        lambda: client.get_credit_card("not-an-id", "ON"),
        lambda: client.get_bank_account("abc", "ON"),
        lambda: client.search_bank_accounts("ON", lang="es"),
    ],
)
async def test_invalid_input_is_rejected_before_any_request(call):
    with pytest.raises(InvalidInput):
        await call()

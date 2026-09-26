"""MCP tools for FCAC's credit card and account comparison tools."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.fcac import client, constants
from maplestats_mcp.modules.fcac.schemas import (
    AccountDetail,
    AccountGroup,
    AccountSearchResult,
    AccountType,
    CreditCardDetail,
    CreditCardSearchResult,
    Currency,
    Province,
    Reward,
)

Lang = Literal["en", "fr"]


@tool
async def fcac_search_credit_cards(
    province: Province,
    currency: Currency = "CAD",
    student: bool = False,
    secured: bool = False,
    query: str = "",
    institution: str = "",
    max_annual_fee: float | None = None,
    max_purchase_rate: float | None = None,
    rewards: list[Reward] | None = None,
    sort: Literal["annual_fee", "purchase_rate", "institution", "name"] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> CreditCardSearchResult:
    """Compare credit cards offered in a province, from FCAC's Credit Card Comparison Tool.

    Use for: which credit cards are available in a province (two-letter
    code, e.g. 'ON', 'QC') and what they cost: annual fee, purchase
    interest rate and reward categories, for every card the financial
    institutions list with the Financial Consumer Agency of Canada (about
    95 in Ontario). Filter by words in the card or bank name, institution,
    maximum annual fee (dollars), maximum purchase rate (percent) and
    rewards ('cash_back', 'travel', 'groceries', 'gas',
    'general_merchandise'; every one given must apply). student=True adds
    student cards; secured=True lists secured cards instead. Default order
    is FCAC's (annual fee, low to high). Pass a product_id with the same
    province and options to fcac_get_credit_card for cash advance and
    balance transfer rates, foreign conversion fee, minimum income and
    insurance. Read live; lang sets names and labels.
    Keywords: credit card, interest rate, annual fee, APR, rewards card,
    cash back, travel rewards, low interest card, FCAC, compare cards,
    bank fees, consumer finance.
    Mots-clés : carte de crédit, taux d'intérêt, frais annuels,
    récompenses, remise en argent, carte à faible taux, ACFC, comparer
    les cartes, frais bancaires, consommation financière.
    """
    return await client.search_credit_cards(
        province,
        currency=currency,
        student=student,
        secured=secured,
        query=query,
        institution=institution,
        max_annual_fee=max_annual_fee,
        max_purchase_rate=max_purchase_rate,
        rewards=rewards or (),
        sort=sort,
        limit=limit,
        lang=lang,
    )


@tool
async def fcac_get_credit_card(
    product_id: str,
    province: Province,
    currency: Currency = "CAD",
    student: bool = False,
    secured: bool = False,
    lang: Lang = "en",
) -> CreditCardDetail:
    """Full details of one credit card from FCAC's Credit Card Comparison Tool.

    Use for: one card's annual fees (first and additional card),
    purchase, cash advance and balance transfer interest rates, foreign
    currency conversion fee, minimum personal and household income,
    reward categories and how to redeem them, other benefits, and
    included insurance (travel medical, trip cancellation, rental car,
    and more). product_id comes from fcac_search_credit_cards; pass the
    same province, currency, student and secured values used there,
    because the tool only opens a card from its result list. Every
    section of the page is also returned under `sections`.
    Keywords: credit card details, cash advance rate, balance transfer
    rate, foreign transaction fee, minimum income, card insurance,
    annual fee, FCAC, card benefits, rewards program.
    Mots-clés : détails de carte de crédit, taux d'avance de fonds,
    taux de transfert de solde, frais de conversion de devises, revenu
    minimum, assurance carte, frais annuels, ACFC, avantages.
    """
    return await client.get_credit_card(
        product_id,
        province,
        currency=currency,
        student=student,
        secured=secured,
        lang=lang,
    )


@tool
async def fcac_search_bank_accounts(
    province: Province,
    account_type: AccountType = "chequing",
    currency: Currency = "CAD",
    groups: list[AccountGroup] | None = None,
    query: str = "",
    institution: str = "",
    max_monthly_fee: float | None = None,
    low_cost_only: bool = False,
    sort: Literal["monthly_fee", "institution", "name"] | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    lang: Lang = "en",
) -> AccountSearchResult:
    """Compare chequing or savings accounts in a province, from FCAC's Account Comparison Tool.

    Use for: bank and credit union accounts available in a province
    (two-letter code) with their monthly fee (chequing), interest rate
    (savings), included transactions and whether they fall under the
    Commitment on Low-Cost and No-Cost Accounts (about 61 chequing and
    38 savings accounts in Ontario). groups adds accounts offered to
    'senior', 'gis_recipient', 'rdsp_beneficiary', 'youth', 'student',
    'newcomer', 'indigenous', 'social_assistance' or
    'disability_tax_credit' customers. Filter by words in the name,
    institution, maximum monthly fee (dollars) or low_cost_only. Default
    order is FCAC's (most included transactions first). Pass a product_id
    with the same options to fcac_get_bank_account for every fee. Read
    live; lang sets names and labels.
    Keywords: bank account, chequing account, savings account, monthly
    fee, bank fees, low-cost account, no-fee account, interest rate,
    FCAC, compare accounts, credit union, transactions.
    Mots-clés : compte bancaire, compte-chèques, compte d'épargne, frais
    mensuels, frais bancaires, compte à frais modiques, compte sans
    frais, taux d'intérêt, ACFC, coopérative de crédit.
    """
    return await client.search_bank_accounts(
        province,
        account_type=account_type,
        currency=currency,
        groups=groups or (),
        query=query,
        institution=institution,
        max_monthly_fee=max_monthly_fee,
        low_cost_only=low_cost_only,
        sort=sort,
        limit=limit,
        lang=lang,
    )


@tool
async def fcac_get_bank_account(
    product_id: str,
    province: Province,
    account_type: AccountType = "chequing",
    currency: Currency = "CAD",
    groups: list[AccountGroup] | None = None,
    lang: Lang = "en",
) -> AccountDetail:
    """Every fee of one chequing or savings account, from FCAC's Account Comparison Tool.

    Use for: one account's monthly fee and how to waive it, included
    transactions, interest rate tiers, and the fees once included
    transactions run out: withdrawals (branch, ATM, other bank's ATM,
    abroad), transfers and Interac e-Transfers, overdraft protection,
    non-sufficient funds (NSF), debit purchases abroad, bill payments,
    cheque images and statements. product_id comes from
    fcac_search_bank_accounts; pass the same province, account_type,
    currency and groups used there, because the tool only opens an
    account from its result list. Every section is under `sections`.
    Keywords: bank account fees, NSF fee, overdraft fee, ATM fee,
    e-Transfer fee, monthly fee waiver, minimum balance, savings
    interest rate, FCAC, chequing account.
    Mots-clés : frais de compte bancaire, frais d'insuffisance de fonds,
    frais de découvert, frais de guichet, virement Interac, solde
    minimum, taux d'intérêt épargne, ACFC, compte-chèques.
    """
    return await client.get_bank_account(
        product_id,
        province,
        account_type=account_type,
        currency=currency,
        groups=groups or (),
        lang=lang,
    )

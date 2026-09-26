"""Typed responses for FCAC's credit card and account comparison tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Province = Literal["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
Currency = Literal["CAD", "USD", "other"]
AccountType = Literal["chequing", "savings"]
AccountGroup = Literal[
    "senior",
    "gis_recipient",
    "rdsp_beneficiary",
    "youth",
    "student",
    "newcomer",
    "indigenous",
    "social_assistance",
    "disability_tax_credit",
]
Reward = Literal["cash_back", "travel", "groceries", "gas", "general_merchandise"]


class DetailItem(BaseModel):
    label: str | None = Field(
        default=None, description="The item's label as shown, e.g. 'Cash advance'."
    )
    value: str


class DetailSection(BaseModel):
    key: str = Field(
        description=(
            "Language-independent section key from the page's own element id, "
            "e.g. 'annual_fee', 'interest_rate', 'withdraw_fees'."
        )
    )
    title: str = Field(description="Section title as shown in the requested language.")
    items: list[DetailItem] = Field(default_factory=list)


class CreditCardSummary(BaseModel):
    product_id: str = Field(description="FCAC's product id; pass it to fcac_get_credit_card.")
    name: str
    institution: str
    annual_fee: float | None = Field(
        default=None, description="Annual fee for the first card in dollars; 0 for no fee."
    )
    annual_fee_text: str
    purchase_rate: float | None = Field(
        default=None, description="Purchase interest rate in percent (low end of a range)."
    )
    purchase_rate_max: float | None = Field(
        default=None, description="High end when the issuer gives a range of purchase rates."
    )
    currency: str
    rewards: list[str] = Field(default_factory=list, description="Reward categories as shown.")


class CreditCardSearchResult(BaseModel):
    province: Province
    currency: Currency
    student: bool
    secured: bool
    total_listed: int = Field(description="Cards FCAC lists for the province and options.")
    total_matched: int = Field(description="Cards left after this tool's own filters.")
    returned_count: int
    cards: list[CreditCardSummary] = Field(default_factory=list)
    provenance: Provenance


class CreditCardDetail(BaseModel):
    product_id: str
    name: str
    institution: str
    currency: str | None = None
    product_url: str | None = None
    annual_fee: float | None = Field(default=None, description="First card, dollars.")
    annual_fee_additional_card: float | None = Field(
        default=None, description="Second card, dollars."
    )
    purchase_rate: float | None = Field(default=None, description="Percent (low end).")
    cash_advance_rate: float | None = Field(default=None, description="Percent (low end).")
    balance_transfer_rate: float | None = Field(default=None, description="Percent (low end).")
    foreign_conversion_fee: float | None = Field(
        default=None, description="Percent of the transaction value."
    )
    minimum_personal_income: float | None = Field(
        default=None, description="Dollars; null when not required or not stated."
    )
    minimum_household_income: float | None = Field(
        default=None, description="Dollars; null when not required or not stated."
    )
    rewards: list[str] = Field(default_factory=list)
    sections: list[DetailSection] = Field(
        default_factory=list,
        description="Every section of the detail page, including insurance and benefits.",
    )
    provenance: Provenance


class AccountSummary(BaseModel):
    product_id: str = Field(description="FCAC's product id; pass it to fcac_get_bank_account.")
    name: str
    institution: str
    low_cost_no_cost: bool = Field(
        description="Flagged under the Commitment on Low-Cost and No-Cost Accounts."
    )
    monthly_fee: float | None = Field(
        default=None, description="Dollars per month (chequing accounts)."
    )
    monthly_fee_text: str | None = None
    interest_rate: float | None = Field(
        default=None, description="Percent (savings accounts; low end of a range)."
    )
    interest_rate_text: str | None = None
    transactions: list[str] = Field(
        default_factory=list, description="Included transactions as shown."
    )
    currency: str


class AccountSearchResult(BaseModel):
    province: Province
    account_type: AccountType
    currency: Currency
    groups: list[AccountGroup] = Field(default_factory=list)
    total_listed: int = Field(description="Accounts FCAC lists for the province and options.")
    total_matched: int = Field(description="Accounts left after this tool's own filters.")
    returned_count: int
    accounts: list[AccountSummary] = Field(default_factory=list)
    provenance: Provenance


class AccountDetail(BaseModel):
    product_id: str
    account_type: AccountType
    name: str
    institution: str
    currency: str | None = None
    product_url: str | None = None
    monthly_fee: float | None = Field(default=None, description="Dollars per month.")
    monthly_fee_notes: list[str] = Field(
        default_factory=list,
        description="Discounted fee and how to waive the fee (e.g. a minimum balance).",
    )
    included_transactions: list[DetailItem] = Field(default_factory=list)
    interest_rates: list[str] = Field(
        default_factory=list,
        description="Each rate tier as shown, e.g. '0.0050% $10,000.00 - $24,999.99', or 'None'.",
    )
    nsf_fee: float | None = Field(
        default=None, description="Non-sufficient funds fee, dollars (chequing accounts)."
    )
    sections: list[DetailSection] = Field(
        default_factory=list,
        description="Every section of the detail page: withdrawal, transfer, overdraft, "
        "debit, bill payment and cheque fees, account history, notes.",
    )
    provenance: Provenance

"""Typed responses for the federal proactive disclosure tables."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

DatasetName = Literal["contracts", "grants", "travel", "hospitality"]
SortOrder = Literal["date_desc", "date_asc", "value_desc", "value_asc"]
ValueMode = Literal["latest_per_agreement", "all_rows"]
GroupBy = Literal[
    "department",
    "vendor",
    "recipient",
    "name",
    "title",
    "program",
    "province",
    "riding",
    "fiscal_year",
    "quarter",
    "commodity_type",
    "solicitation_procedure",
    "instrument_type",
    "country_of_vendor",
    "economic_object_code",
    "recipient_type",
    "agreement_type",
    "disclosure_group",
]
DisclosureGroupArg = Literal["ministers", "senior_officials"]
InstrumentTypeArg = Literal["contract", "amendment", "standing_offer"]
AgreementTypeArg = Literal["grant", "contribution", "other"]


class RecordSource(BaseModel):
    """Where one row lives, so it can be cited and found again."""

    dataset_id: str = Field(description="open.canada.ca dataset (package) id.")
    resource_id: str = Field(description="DataStore table (resource) id.")
    record_id: int | None = Field(
        default=None, description="The row's DataStore _id within that table."
    )
    dataset_url: str = Field(description="The dataset's open.canada.ca page, to cite.")


class Department(BaseModel):
    owner_org: str | None = Field(
        default=None, description="open.canada.ca organization code, e.g. 'dnd-mdn'."
    )
    name: str | None = Field(default=None, description="Organization name in the call's language.")


class ContractRecord(BaseModel):
    reference_number: str | None = None
    procurement_id: str | None = Field(
        default=None,
        description="Contract number; the amendments of one contract share it (with owner_org).",
    )
    vendor_name: str | None = None
    vendor_postal_code: str | None = None
    buyer_name: str | None = None
    contract_date: str | None = None
    contract_period_start: str | None = None
    delivery_date: str | None = Field(default=None, description="Period end or delivery date.")
    contract_value: float | None = Field(
        default=None,
        description="Total contract value in CAD with taxes, including all amendments so far "
        "(for an amendment row, the amended total).",
    )
    original_value: float | None = None
    amendment_value: float | None = None
    description: str | None = Field(default=None, description="Description of work.")
    comments: str | None = None
    instrument_type: str | None = Field(
        default=None,
        description="C contract, A amendment, SOSA standing offer or supply arrangement.",
    )
    instrument_type_label: str | None = None
    solicitation_procedure: str | None = None
    solicitation_procedure_label: str | None = None
    commodity_type: str | None = None
    commodity_type_label: str | None = None
    commodity_code: str | None = None
    economic_object_code: str | None = None
    country_of_vendor: str | None = None
    number_of_bids: int | None = None
    ministers_office: bool | None = Field(
        default=None, description="Contract for a minister's office."
    )
    former_public_servant: bool | None = Field(
        default=None, description="Vendor is a former public servant receiving a PSSA pension."
    )
    reporting_period: str | None = Field(
        default=None,
        description="Fiscal quarter in which the row was published, e.g. '2024-2025-Q3'.",
    )
    department: Department
    source: RecordSource


class GrantRecord(BaseModel):
    ref_number: str | None = Field(
        default=None, description="Shared by an agreement's amendment rows (with owner_org)."
    )
    amendment_number: int | None = Field(default=None, description="0 for the original.")
    amendment_date: str | None = None
    agreement_type: str | None = Field(
        default=None, description="G grant, C contribution, O other."
    )
    agreement_type_label: str | None = None
    recipient_type: str | None = None
    recipient_type_label: str | None = None
    recipient_legal_name: str | None = None
    recipient_operating_name: str | None = None
    recipient_business_number: str | None = None
    research_organization_name: str | None = None
    recipient_country: str | None = None
    recipient_province: str | None = None
    recipient_city: str | None = None
    recipient_postal_code: str | None = None
    federal_riding_name: str | None = None
    federal_riding_number: str | None = None
    program_name: str | None = None
    program_purpose: str | None = None
    agreement_title: str | None = None
    agreement_number: str | None = None
    agreement_value: float | None = Field(
        default=None,
        description="Agreement value in CAD: the total as of this row (an amendment row "
        "restates the whole value, not the change).",
    )
    foreign_currency_type: str | None = None
    foreign_currency_value: float | None = None
    agreement_start_date: str | None = None
    agreement_end_date: str | None = None
    description: str | None = None
    expected_results: str | None = None
    naics_identifier: str | None = None
    department: Department
    source: RecordSource


class TravelRecord(BaseModel):
    ref_number: str | None = None
    disclosure_group: str | None = Field(
        default=None,
        description="MPSES (ministers, their staff, parliamentary secretaries, exempt staff) or "
        "SLE (senior officers and employees); null on older rows.",
    )
    disclosure_group_label: str | None = None
    name: str | None = Field(default=None, description="As published, often 'Last First'.")
    title: str | None = None
    purpose: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    destinations: list[str] = Field(default_factory=list)
    airfare: float | None = None
    other_transport: float | None = None
    lodging: float | None = None
    meals: float | None = Field(default=None, description="Meals and incidentals.")
    other_expenses: float | None = None
    total: float | None = Field(default=None, description="Total in CAD.")
    comments: str | None = None
    department: Department
    source: RecordSource


class HospitalityRecord(BaseModel):
    ref_number: str | None = None
    disclosure_group: str | None = Field(
        default=None, description="MPSES (ministers and their staff) or SLE (senior officers)."
    )
    disclosure_group_label: str | None = None
    name: str | None = None
    title: str | None = None
    description: str | None = Field(default=None, description="Purpose of the event.")
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    vendors: list[str] = Field(default_factory=list)
    employee_attendees: int | None = Field(
        default=None, description="Government of Canada officials attending."
    )
    guest_attendees: int | None = None
    total: float | None = Field(default=None, description="Total cost in CAD.")
    comments: str | None = None
    department: Department
    source: RecordSource


class _Page(BaseModel):
    dataset: DatasetName
    total_matched: int = Field(
        description="Rows matching every filter (after the value range, when one is given)."
    )
    returned_count: int
    offset: int
    limit: int
    filters: dict[str, str | int | float | bool | list[str]] = Field(
        default_factory=dict, description="The filters applied, as sent or computed."
    )
    rows_scanned: int = Field(
        default=0,
        description="Rows read to apply a value range or value sort (0 when the portal "
        "filtered and sorted on its own).",
    )
    dataset_url: str
    resource_id: str


class ContractSearchResult(_Page):
    records: list[ContractRecord]
    provenance: Provenance


class GrantSearchResult(_Page):
    records: list[GrantRecord]
    provenance: Provenance


class TravelSearchResult(_Page):
    records: list[TravelRecord]
    provenance: Provenance


class HospitalitySearchResult(_Page):
    records: list[HospitalityRecord]
    provenance: Provenance


class SummaryGroup(BaseModel):
    key: str | None = Field(description="The group's code or value (null: not reported).")
    label: str | None = Field(default=None, description="Readable name in the call's language.")
    count: int = Field(description="Rows (or agreements, with latest_per_agreement) counted.")
    total_value: float = Field(description="Sum of the value column in CAD.")
    share_percent: float | None = Field(
        default=None, description="Share of the overall total value."
    )


class DisclosureSummary(BaseModel):
    dataset: DatasetName
    group_by: GroupBy
    value_field: str = Field(description="The column summed.")
    value_mode: ValueMode
    groups: list[SummaryGroup]
    other_groups: int = Field(
        default=0, description="Groups beyond `top`, folded into other_count/other_value."
    )
    other_count: int = 0
    other_value: float = 0.0
    total_count: int
    total_value: float
    rows_scanned: int = Field(description="Rows read from the table to compute the totals.")
    rows_without_value: int = Field(
        default=0, description="Rows whose value is blank or not a number (counted, not summed)."
    )
    filters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    dataset_url: str
    resource_id: str
    method: str = Field(
        description="How the totals were computed (the portal has no SQL or aggregate API)."
    )
    provenance: Provenance


class DatasetInfo(BaseModel):
    dataset: DatasetName
    title: str
    dataset_id: str
    resource_id: str
    dataset_url: str
    search_page_url: str = Field(description="The government's own search page for this table.")
    resource_in_package: bool = Field(
        description="False when the package no longer lists this resource id (it has moved)."
    )
    datastore_active: bool | None = None
    row_count: int | None = None
    last_modified: str | None = Field(default=None, description="Resource last modified (UTC).")
    value_field: str
    date_field: str
    group_by: list[str]
    licence: str | None = None


class DatasetList(BaseModel):
    datasets: list[DatasetInfo]
    provenance: Provenance

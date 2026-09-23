from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class TenderNotice(BaseModel):
    reference_number: str
    solicitation_number: str | None
    amendment_number: str | None
    title: str
    status: str | None
    publication_date: str | None
    closing_date: str | None
    procurement_categories: list[str]
    procurement_method: str | None
    contracting_entity: str | None
    regions_of_delivery: list[str]
    unspsc: list[str]
    notice_url: str | None
    description: str | None


class AwardNotice(BaseModel):
    reference_number: str
    solicitation_number: str | None
    contract_number: str | None
    title: str
    status: str | None
    publication_date: str | None
    award_date: str | None
    contract_start_date: str | None
    contract_end_date: str | None
    contract_amount: float | None
    total_contract_value: float | None
    currency: str | None
    supplier_name: str | None
    supplier_city: str | None
    supplier_province: str | None
    supplier_country: str | None
    contracting_entity: str | None
    procurement_categories: list[str]
    procurement_method: str | None
    regions_of_delivery: list[str]
    unspsc: list[str]
    description: str | None


class ContractRecord(BaseModel):
    reference_number: str
    contract_number: str | None
    title: str
    status: str | None
    award_date: str | None
    contract_start_date: str | None
    contract_end_date: str | None
    original_amount: float | None
    total_contract_value: float | None
    currency: str | None
    amendment_count: int
    latest_amendment_date: str | None
    supplier_name: str | None
    supplier_standardized_name: str | None
    supplier_province: str | None
    supplier_country: str | None
    contracting_entity: str | None
    end_user_entity: str | None
    procurement_categories: list[str]
    procurement_method: str | None
    limited_tendering_reason: str | None
    commodity: list[str]


class TenderSearchResult(BaseModel):
    query: str
    notice_set: str
    tenders: list[TenderNotice]
    returned_count: int
    total_matched: int
    total_notices: int
    provenance: Provenance


class AwardSearchResult(BaseModel):
    query: str
    fiscal_year: str
    awards: list[AwardNotice]
    returned_count: int
    total_matched: int
    total_notices: int
    provenance: Provenance


class NoticeDetail(BaseModel):
    reference_number: str
    notice_kind: str
    tender: TenderNotice | None
    award: AwardNotice | None
    provenance: Provenance


class ContractSearchResult(BaseModel):
    query: str
    fiscal_year: str
    contracts: list[ContractRecord]
    returned_count: int
    total_matched: int
    total_contracts: int
    provenance: Provenance


class BulkFile(BaseModel):
    key: str
    title: str
    url: str
    size_bytes: int | None
    last_modified: str | None


class BulkFileList(BaseModel):
    files: list[BulkFile]
    provenance: Provenance

"""Typed responses for CIPO's IP Horizons researcher datasets."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

IpType = Literal["patent", "industrial_design", "trademark"]


class IpHorizonsFile(BaseModel):
    ip_type: IpType
    table: str = Field(description="Table name without its prefix, e.g. 'main', 'claim'.")
    text_format: bool = Field(description="True for the '_txt_format' variant of a table.")
    number_from: int | None = Field(
        default=None, description="First patent number in this file, when the table is split."
    )
    number_to: int | None = Field(
        default=None, description="Last patent number in this file, when the table is split."
    )
    release_date: date | None = None
    name: str
    url: str


class IpHorizonsCatalogue(BaseModel):
    files: list[IpHorizonsFile] = Field(default_factory=list)
    returned_count: int
    tables: list[str] = Field(
        default_factory=list, description="Every table the package lists, in any release."
    )
    provenance: Provenance


class DictionaryField(BaseModel):
    table: str
    name_en: str
    name_fr: str | None = None
    type_en: str | None = None
    type_fr: str | None = None
    description_en: str | None = None
    description_fr: str | None = None


class IpHorizonsDictionary(BaseModel):
    ip_type: IpType
    fields: list[DictionaryField] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="Coverage, delimiter and encoding notes."
    )
    provenance: Provenance


class PatentSummary(BaseModel):
    patent_number: int
    title_en: str | None = None
    title_fr: str | None = None
    filing_date: str | None = None
    grant_date: str | None = None
    status_code: str | None = None
    application_type: str | None = Field(default=None, description="PCT or NON-PCT.")
    document_kind: str | None = None
    filing_country: str | None = None
    filing_language: str | None = None
    pct_application_number: str | None = None
    pct_publication_number: str | None = None
    parent_application_number: str | None = None


class PatentParty(BaseModel):
    party_type: str | None = Field(default=None, description="Owner, Inventor, Applicant or Agent.")
    name: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    owner_from: str | None = None
    owner_to: str | None = None


class PatentClassification(BaseModel):
    sequence: int | None = None
    symbol: str = Field(description="IPC symbol, e.g. 'H03K 19/20'.")
    section: str | None = None
    class_title: str | None = None
    subclass_title: str | None = None
    group_title: str | None = None
    subgroup_title: str | None = None
    version_date: str | None = None


class PatentRecord(BaseModel):
    patent: PatentSummary
    parties: list[PatentParty] = Field(default_factory=list)
    classifications: list[PatentClassification] = Field(default_factory=list)
    classifications_included: bool
    release_date: date | None = None
    provenance: Provenance


class PatentSearchResult(BaseModel):
    patents: list[PatentSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    filters: dict[str, str] = Field(default_factory=dict)
    release_date: date | None = None
    provenance: Provenance

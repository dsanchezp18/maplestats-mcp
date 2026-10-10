"""Typed responses for the CRA registered charities module."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CharityRecord(BaseModel):
    business_number: str
    legal_name: str | None = None
    account_name: str | None = None
    designation_code: str | None = None
    designation: str | None = None
    category_code: str | None = None
    sub_category_code: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str | None = None


class CharityProgram(BaseModel):
    code: str | None = None
    percent: str | None = None
    description: str | None = None


class CharityDirector(BaseModel):
    last_name: str | None = None
    first_name: str | None = None
    initials: str | None = None
    position: str | None = None
    at_arms_length: bool | None = None
    start_date: date | None = None
    end_date: date | None = None


class CharitySearchResult(BaseModel):
    list_year: int
    query: str | None = None
    province: str | None = None
    designation: str | None = None
    total_count: int
    returned_count: int
    offset: int
    limit: int
    charities: list[CharityRecord] = Field(default_factory=list)
    provenance: Provenance


class CharityDetail(BaseModel):
    list_year: int
    charity: CharityRecord
    fiscal_period_end: date | None = None
    programs: list[CharityProgram] = Field(default_factory=list)
    dataset_url: str
    provenance: Provenance


class CharityDirectors(BaseModel):
    list_year: int
    business_number: str
    fiscal_period_end: date | None = None
    total_count: int
    returned_count: int
    directors: list[CharityDirector] = Field(default_factory=list)
    provenance: Provenance

"""Typed responses for Corporations Canada's federal corporation lookup API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CorporationName(BaseModel):
    name: str
    name_type: str | None = None
    current: bool = False
    effective_date: date | None = None
    expiry_date: date | None = None


class CorporationAddress(BaseModel):
    address_lines: list[str] = Field(default_factory=list)
    city: str | None = None
    province_code: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    current: bool = False


class DirectorLimits(BaseModel):
    minimum: int | None = None
    maximum: int | None = None


class AnnualReturn(BaseModel):
    year_of_filing: str | None = None
    annual_meeting_date: date | None = None


class Activity(BaseModel):
    activity: str
    activity_date: date | None = None


class CorporationDetail(BaseModel):
    corporation_id: str
    act: str | None = None
    status: str | None = None
    business_number: str | None = None
    names: list[CorporationName] = Field(default_factory=list)
    addresses: list[CorporationAddress] = Field(default_factory=list)
    director_limits: DirectorLimits | None = None
    annual_returns: list[AnnualReturn] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    landing_page_url: str
    provenance: Provenance

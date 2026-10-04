"""Typed responses for the medical device licence tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DeviceCompany(BaseModel):
    company_id: int
    name: str
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = Field(default=None, description="Two-letter country code.")
    postal_code: str | None = None
    active: bool | None = None


class DeviceLicence(BaseModel):
    licence_number: int
    licence_name: str | None = None
    status: str | None = None
    status_code: str | None = None
    risk_class: int | None = Field(
        default=None, description="Device class 2, 3 or 4 (class I devices need no licence)."
    )
    licence_type: str | None = None
    first_issued: str | None = None
    end_date: str | None = Field(default=None, description="Cancellation date; null if active.")
    company_id: int | None = None
    company_name: str | None = None


class DeviceLicenceList(BaseModel):
    licences: list[DeviceLicence] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    by_risk_class: dict[str, int] = Field(default_factory=dict)
    provenance: Provenance


class Device(BaseModel):
    device_id: int
    licence_number: int
    trade_name: str | None = None
    first_licensed: str | None = None
    end_date: str | None = Field(default=None, description="Date removed from the licence.")
    identifiers: list[str] = Field(
        default_factory=list, description="Model or catalogue numbers on the label."
    )


class DeviceLicenceDetail(BaseModel):
    licence: DeviceLicence
    company: DeviceCompany | None = None
    devices: list[Device] = Field(default_factory=list)
    device_count: int
    mdall_page: str
    provenance: Provenance


class DeviceList(BaseModel):
    devices: list[Device] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance

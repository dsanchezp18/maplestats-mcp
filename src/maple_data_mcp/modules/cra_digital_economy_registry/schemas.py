from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class DigitalEconomyRegistrant(BaseModel):
    legal_name: str
    trade_name: str | None
    business_number: str
    effective_registration_date: str
    effective_deregistration_date: str | None


class DigitalEconomyRegistryResult(BaseModel):
    query: str
    registrants: list[DigitalEconomyRegistrant]
    returned_count: int
    total_matched: int
    total_registrants: int
    provenance: Provenance

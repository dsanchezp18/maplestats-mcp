from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class DigitalEconomyRegistrant(BaseModel):
    legal_name: str
    trade_name: str | None
    business_number: str
    effective_registration_date: date | None = Field(
        description="ISO date; null only if the page's text could not be read as a date."
    )
    effective_deregistration_date: date | None
    registration_date_text: str = Field(
        description="The date as the page prints it, e.g. 'July 1, 2023' or '1 juillet 2021'."
    )
    deregistration_date_text: str | None = None


class DigitalEconomyRegistryResult(BaseModel):
    query: str
    registrants: list[DigitalEconomyRegistrant]
    returned_count: int
    total_matched: int
    total_registrants: int
    provenance: Provenance

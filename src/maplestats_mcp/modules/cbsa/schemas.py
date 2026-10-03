"""Typed responses for CBSA border wait times."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

WaitStatus = Literal["no_delay", "minutes", "not_applicable", "not_reported", "closed", "other"]


class WaitTime(BaseModel):
    status: WaitStatus = Field(
        description="no_delay, minutes (see `minutes`), not_applicable (the lane does not "
        "exist at this crossing), not_reported ('--': CBSA posts no figure, which is the "
        "case for most U.S.-bound lanes), closed, or other (see `text`)."
    )
    minutes: int | None = Field(default=None, description="0 for no delay.")
    text: str = Field(description="The value as CBSA wrote it.")


class BorderCrossing(BaseModel):
    office: str = Field(description="CBSA office name, e.g. 'Peace Bridge'.")
    location: str = Field(description="Both sides, e.g. 'Fort Erie, ON/Buffalo, NY'.")
    province: str | None = Field(default=None, description="Two-letter code of the Canadian side.")
    us_state: str | None = Field(default=None, description="Two-letter code of the U.S. side.")
    updated: str = Field(description="CBSA's own update time with its zone, e.g. '13:15 EDT'.")
    updated_at: datetime | None = Field(
        default=None, description="The same time with its UTC offset, when the zone is known."
    )
    commercial_canada_bound: WaitTime | None = None
    commercial_us_bound: WaitTime | None = None
    travellers_canada_bound: WaitTime | None = None
    travellers_us_bound: WaitTime | None = None


class BorderWaitTimes(BaseModel):
    crossings: list[BorderCrossing] = Field(default_factory=list)
    total_crossings: int = Field(description="Crossings in the file before filtering.")
    returned_count: int
    longest_travellers_wait: str | None = Field(
        default=None, description="The crossing with the longest traveller wait shown, if any."
    )
    historical_data: str = Field(
        description="Where the historical wait-time files are, for trends over time."
    )
    provenance: Provenance

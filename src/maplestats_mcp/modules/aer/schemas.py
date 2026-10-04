from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class WellLicenceDailyReport(BaseModel):
    day: str
    report_date: date | None
    expected_date: date | None = Field(
        default=None, description="The most recent date with this weekday, in Alberta time."
    )
    note: str | None = Field(
        default=None,
        description="Set when the file still holds an older week's list than expected_date.",
    )
    raw_text: str
    provenance: Provenance


class WellLicenceArchiveLink(BaseModel):
    year: int
    month: int | None
    url: str
    exists: bool
    size_bytes: int | None
    note: str | None = None
    provenance: Provenance


class ProductionVolumesLink(BaseModel):
    product: str
    url: str
    exists: bool
    size_bytes: int | None
    last_modified: str | None
    provenance: Provenance

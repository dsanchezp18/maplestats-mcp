from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class WellLicenceDailyReport(BaseModel):
    day: str
    report_date: date | None
    raw_text: str
    provenance: Provenance


class WellLicenceArchiveLink(BaseModel):
    year: int
    month: int | None
    url: str
    exists: bool
    size_bytes: int | None
    provenance: Provenance


class ProductionVolumesLink(BaseModel):
    product: str
    url: str
    exists: bool
    size_bytes: int | None
    last_modified: str | None
    provenance: Provenance

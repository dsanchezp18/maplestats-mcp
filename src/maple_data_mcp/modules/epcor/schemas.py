from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance

Plant = Literal["els", "rossdale"]
System = Literal["water", "wastewater"]


class DailyReading(BaseModel):
    date: date | None
    date_label: str
    total_hardness: float | None
    ph: float | None
    temperature: float | None
    total_chlorine_residual: float | None
    alkalinity: float | None
    conductivity: float | None
    caustic_soda_dose: float | None


class DailyWaterQuality(BaseModel):
    plant: Plant
    plant_name: str
    units: dict[str, str]
    readings: list[DailyReading]
    provenance: Provenance


class WaterQualityReport(BaseModel):
    year: int | None
    month: int | None
    system: System
    kind: str
    file_name: str
    url: str


class WaterQualityReportList(BaseModel):
    total_matches: int
    kinds_available: list[str]
    reports: list[WaterQualityReport]
    provenance: Provenance

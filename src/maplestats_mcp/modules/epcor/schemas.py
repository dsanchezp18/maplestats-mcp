from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from maplestats_mcp.shared.models import Provenance

Plant = Literal["els", "rossdale"]


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

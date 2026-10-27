from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Plant = Literal["els", "rossdale"]


class DailyReading(BaseModel):
    # dt.date: assigning Field() to a field named `date` would shadow the type.
    date: dt.date | None = Field(
        description="Computed by MapleStats from date_label, which has no year: the latest "
        "such day not after today in Edmonton. Null when the label is not MON-DD."
    )
    date_label: str = Field(description="The day as the page shows it, e.g. 'OCT-26'.")
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

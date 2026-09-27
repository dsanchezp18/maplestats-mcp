"""Typed responses for the Canadian Food Inspection Agency (CFIA) module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

PremisesStatus = Literal["current", "released"]
PremisesType = Literal["commercial", "non_commercial", "captive_wild"]


class DiseaseYearCount(BaseModel):
    year: int
    disease_key: str = Field(
        description="Stable key, e.g. 'chronic_wasting_disease'; the same in both languages."
    )
    disease: str = Field(description="Disease name as the page writes it in the chosen language.")
    count: int = Field(
        description="Confirmed farmed herds or flocks (premises) affected that year, as published."
    )
    note: str | None = Field(default=None, description="The table note attached to the row.")
    detections_tool: str | None = Field(
        default=None,
        description="Tool with one row per detection (date, province, animal type), when any.",
    )


class CountTotal(BaseModel):
    key: str = Field(description="The year, or the disease key.")
    label: str
    total: int
    rows: int = Field(description="Number of year-disease rows added up.")


class ReportableDiseaseResult(BaseModel):
    year_from: int
    year_to: int
    diseases: list[str] = Field(description="Disease keys matched by the filter, or all shown.")
    rows: list[DiseaseYearCount]
    row_count: int
    totals: list[CountTotal] | None = Field(
        default=None, description="Sums by year or by disease, when totals_by is set."
    )
    current_as_of: date | None = Field(
        default=None,
        description="The page's 'Current as of' date: counts run to the end of that month.",
    )
    years_available: list[int]
    source_page: str
    notes: list[str]
    provenance: Provenance


class DiseaseDetection(BaseModel):
    disease_key: str
    disease: str
    year: int
    date_confirmed: date | None = Field(
        default=None, description="None when the published day and month cannot be read."
    )
    date_text: str = Field(description="Day and month as published, without table notes.")
    location: str = Field(description="Location as published, usually a province.")
    province_codes: list[str] = Field(
        description="Two-letter codes named in the location ('Alberta and Saskatchewan' gives two)."
    )
    animal_type: str = Field(description="Animal type infected, as published.")
    herds: int = Field(
        description="Herds or flocks in this row: 1 unless the row says '(3 herds)'. These add "
        "up to the yearly counts in cfia_reportable_diseases."
    )
    age: str | None = Field(default=None, description="Age of the animal (BSE page only).")
    note: str | None = Field(default=None, description="The table note attached to the row.")


class DetectionCount(BaseModel):
    key: str = Field(description="Year, YYYY-MM month, province code or animal type.")
    label: str
    detections: int = Field(description="Rows (confirmations) in the group.")
    herds: int = Field(description="Herds or flocks in the group.")


class DiseaseDetectionResult(BaseModel):
    diseases: list[str]
    year_from: int | None = None
    year_to: int | None = None
    rows: list[DiseaseDetection]
    row_count: int
    herd_count: int
    counts: list[DetectionCount] | None = Field(
        default=None, description="Groups by year, month, province or animal type, when asked."
    )
    source_pages: list[str]
    last_modified: dict[str, date] = Field(
        description="Each disease page's 'Date modified', by disease key."
    )
    notes: list[str]
    provenance: Provenance


class InfectedPremises(BaseModel):
    premises_id: str = Field(description="CFIA infected premises id, e.g. 'AB-IP116'.")
    province_code: str
    province: str
    location: str | None = Field(
        default=None, description="Municipality or area, as published in the chosen language."
    )
    date_detected: date | None = None
    status: PremisesStatus | None = Field(
        default=None,
        description="'current' (under CFIA quarantine) or 'released'; None if the row has "
        "neither marker.",
    )
    premises_type: str | None = Field(
        default=None, description="'commercial', 'non_commercial' or 'captive_wild'."
    )
    premises_type_label: str | None = None
    woah_classification: Literal["poultry", "non_poultry"] | None = Field(
        default=None,
        description="WOAH premises classification; None for the low pathogenic (LPAI) rows.",
    )
    woah_classification_label: str | None = None
    low_pathogenic: bool = Field(
        description="True where the page marks the premises as low pathogenic (LPAI)."
    )
    control_zone: str | None = Field(
        default=None, description="Primary control zone as published, e.g. 'PCZ-337' or 'ZCP-337'."
    )
    control_zone_order: Literal["active", "revoked", "released"] | None = Field(
        default=None, description="Status of the order declaring the zone; None for N/A."
    )
    control_zone_order_text: str | None = Field(
        default=None, description="That status as published, e.g. 'Revoked; PCZ-239 Revoked'."
    )


class PremisesCount(BaseModel):
    key: str = Field(description="Province code, YYYY-MM month, year or premises type.")
    label: str
    current: int
    released: int
    total: int


class ProvinceStatus(BaseModel):
    province_code: str
    province: str
    current_premises: int | None = None
    released_premises: int | None = None
    birds_impacted: int | None = Field(
        default=None, description="None when the page gives a range such as 'Under 100'."
    )
    birds_impacted_text: str = Field(description="The birds figure as published.")


class ProvinceStatusSummary(BaseModel):
    rows: list[ProvinceStatus]
    total_current: int | None = None
    total_released: int | None = None
    total_birds_impacted: int | None = None
    birds_as_of: date | None = Field(
        default=None, description="The 'Updated' date printed in the birds column header."
    )
    last_modified: date | None = None
    source_page: str


class AvianInfluenzaResult(BaseModel):
    status: Literal["current", "released", "all"]
    total_matched: int
    returned_count: int
    premises: list[InfectedPremises] = Field(description="Newest first, up to `limit`.")
    counts_by: str
    counts: list[PremisesCount] = Field(description="Counts of the matched premises.")
    province_summary: ProvinceStatusSummary | None = Field(
        default=None,
        description="The official status-by-province table (all premises, not filtered).",
    )
    source_page: str
    notes: list[str]
    provenance: Provenance

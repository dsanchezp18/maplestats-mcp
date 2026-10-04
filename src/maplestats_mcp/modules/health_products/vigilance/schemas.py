"""Typed responses for the Canada Vigilance tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class ReportDrug(BaseModel):
    drug_product_id: int | None = None
    drug_name: str | None = None
    role: str | None = Field(
        default=None, description="Suspect, Concomitant, Drug used to treat AE..."
    )
    route: str | None = None
    dose: str | None = None
    frequency: str | None = None
    therapy_duration: str | None = None
    dosage_form: str | None = None
    indication: str | None = None


class VigilanceReport(BaseModel):
    report_id: int
    report_number: str | None = Field(
        default=None, description="Report number as published, e.g. 000000195 or E2B_08853423."
    )
    version: int | None = None
    date_received: str | None = Field(default=None, description="Latest received date.")
    initial_date_received: str | None = None
    report_type: str | None = None
    source: str | None = None
    reporter_type: str | None = None
    mah_number: str | None = Field(
        default=None, description="Market authorization holder's own number."
    )
    sex: str | None = None
    age: str | None = None
    age_years: float | None = None
    weight: str | None = None
    height: str | None = None
    outcome: str | None = None
    serious: str | None = None
    serious_criteria: list[str] = Field(
        default_factory=list,
        description="Death, disability, congenital anomaly, life threatening, hospitalization...",
    )
    reactions: str | None = Field(
        default=None, description="MedDRA preferred terms, comma-separated."
    )
    system_organ_classes: str | None = None
    reaction_duration: str | None = None
    drugs: list[ReportDrug] = Field(default_factory=list)
    provenance: Provenance


class VigilanceCode(BaseModel):
    code: str
    label: str


class VigilanceCodeTables(BaseModel):
    tables: dict[str, list[VigilanceCode]] = Field(default_factory=dict)
    provenance: Provenance


class ReactionReportHit(BaseModel):
    report_id: int
    reactions: list[str] = Field(default_factory=list, description="Matched MedDRA terms.")
    system_organ_classes: list[str] = Field(default_factory=list)


class ReactionSearchResult(BaseModel):
    reports: list[ReactionReportHit] = Field(
        default_factory=list, description="Matching reports, highest (newest) report id first."
    )
    returned_count: int
    reports_matched: int
    reaction_rows_matched: int
    top_reactions: dict[str, int] = Field(
        default_factory=dict, description="Matched rows per MedDRA preferred term."
    )
    by_system_organ_class: dict[str, int] = Field(default_factory=dict)
    complete: bool = Field(description="False when the scan ceiling stopped the read early.")
    newest_report_id_scanned: int | None = None
    scanned_mb: float = Field(description="Compressed megabytes read from the extract.")
    extract_folder: str | None = Field(
        default=None, description="Folder in the ZIP, e.g. cvponline_extract_20260531."
    )
    provenance: Provenance

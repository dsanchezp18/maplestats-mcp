"""Typed responses for PMPRB annual report tables and patented medicines."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Value = float | int | str | None
MedicineStatus = Literal[
    "within_guidelines",
    "does_not_trigger",
    "under_investigation",
    "under_review",
    "voluntary_compliance_undertaking",
    "notice_of_hearing",
    "stay_order",
]


class PmprbReport(BaseModel):
    year: int
    kind: Literal["annual_report", "patented_medicines_list"]
    title: str
    url: str


class PmprbTableInfo(BaseModel):
    year: int
    index: int = Field(description="Position of the table in the report, from 1.")
    label: str | None = Field(
        default=None, description="The report's own title, e.g. 'Figure 1. Annual Rate ...'."
    )
    subtitle: str | None = Field(
        default=None, description="A sub-table's caption, when a figure or table has several."
    )
    section: str | None = Field(default=None, description="The report heading it sits under.")
    columns: list[str] = Field(default_factory=list)
    row_count: int


class PmprbTableList(BaseModel):
    reports: list[PmprbReport] = Field(
        default_factory=list, description="Reports and lists published as HTML."
    )
    tables: list[PmprbTableInfo] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance


class PmprbTable(BaseModel):
    info: PmprbTableInfo
    rows: list[dict[str, Value]] = Field(
        default_factory=list,
        description="Rows keyed by column. Numbers are parsed; '$' and '%' are dropped, "
        "so read the unit from the column name or label.",
    )


class PmprbTableResult(BaseModel):
    report: PmprbReport
    tables: list[PmprbTable] = Field(default_factory=list)
    provenance: Provenance


class PmprbMedicine(BaseModel):
    company: str = Field(description="The rights holder (patentee) that reported it.")
    din: str = Field(description="Drug Identification Number.")
    brand_name: str
    medicinal_ingredient: str
    atc: str | None = Field(default=None, description="ATC class code.")
    dosage_form: str | None = None
    comments: str | None = Field(
        default=None, description="'Introduced' or 'Expired' during the year, or empty."
    )
    status: str | None = Field(default=None, description="Price review status code.")
    status_label: str | None = None


class PmprbMedicineList(BaseModel):
    report: PmprbReport
    medicines: list[PmprbMedicine] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    by_status: dict[str, int] = Field(default_factory=dict)
    provenance: Provenance

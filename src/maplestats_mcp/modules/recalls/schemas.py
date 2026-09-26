"""Typed responses for the Government of Canada Recalls and Safety Alerts site."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class RecallSummary(BaseModel):
    recall_id: int = Field(description="The site's node id (NID); pass it to recalls_get.")
    title: str
    product: str | None = None
    issue: str | None = Field(default=None, description="Hazard or issue, e.g. 'Milk', 'Brakes'.")
    category: str | None = Field(
        default=None, description="Category leaves joined by ' - ', e.g. 'Drugs - Medical devices'."
    )
    recall_class: str | None = Field(
        default=None,
        description="CFIA food 'Class 1-3' or Health Canada 'Type I-III'; empty for most others.",
    )
    organization: str = Field(description="Publishing unit as the dump names it, in `lang`.")
    agency: str = Field(description="health_canada, cfia, transport_canada, or other.")
    product_types: list[str] = Field(
        description="Derived: food, health_product, consumer_product and/or vehicle."
    )
    last_updated: date | None = None
    archived: bool
    tc_recall_number: str | None = Field(
        default=None, description="Transport Canada recall number, for tc_recalls_get."
    )
    url: str


class RecallSearchResult(BaseModel):
    recalls: list[RecallSummary]
    total_matched: int
    returned_count: int
    offset: int
    limit: int
    provenance: Provenance


class RecallCount(BaseModel):
    key: str
    count: int


class RecallCountsResult(BaseModel):
    group_by: str
    total_matched: int = Field(description="Notices matching the filters, before grouping.")
    groups: list[RecallCount]
    groups_total: int = Field(description="Distinct groups before the `top` cap.")
    provenance: Provenance


class LabelValue(BaseModel):
    label: str
    value: str


class RecallSection(BaseModel):
    heading: str
    text: str


class RecallTable(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    truncated: bool = False


class RecallDetail(BaseModel):
    recall_id: int
    url: str = Field(description="The recall page the details were read from.")
    lang: str
    layout: Literal["current", "legacy"] = Field(
        description=(
            "'current' pages have labelled fields; 'legacy' pages (notices migrated from the "
            "old site) carry a label/value header in `details` and free text in `legacy_text`."
        )
    )
    title: str
    alert_type: str | None = Field(
        default=None, description="e.g. 'Health product recall', 'Public advisory'."
    )
    archived: bool
    product: str | None = None
    issue: list[str] = Field(default_factory=list)
    category: list[str] = Field(
        default_factory=list, description="Full category paths, e.g. 'Food - Dairy'."
    )
    recall_class: str | None = None
    what_to_do: str | None = None
    audience: list[str] = Field(default_factory=list)
    distribution: list[str] = Field(default_factory=list)
    companies: str | None = None
    published_by: str | None = None
    agency: str | None = None
    brands: list[str] = Field(default_factory=list)
    recall_date: date | None = None
    last_updated: date | None = None
    first_published: date | None = None
    identification_number: str | None = None
    agency_reference: LabelValue | None = Field(
        default=None,
        description="The publishing agency's own id, e.g. the Transport Canada recall number.",
    )
    sections: list[RecallSection] = Field(default_factory=list)
    tables: list[RecallTable] = Field(
        default_factory=list, description="Affected products tables (lots, UPCs, models)."
    )
    details: list[LabelValue] = Field(default_factory=list)
    legacy_text: str | None = None
    provenance: Provenance

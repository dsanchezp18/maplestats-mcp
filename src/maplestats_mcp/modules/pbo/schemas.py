"""Typed responses for PBO publications."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

PublicationType = Literal["RP", "NT", "LEG", "ES", "OA", "LIBARC"]
Value = float | int | str | bool | None


class PboPublicationSummary(BaseModel):
    id: str = Field(description="PBO publication id, e.g. 'LEG-2526-012-S'.")
    type: str
    type_label: str
    title: str
    abstract: str | None = None
    release_date: str | None = None
    url: str | None = Field(default=None, description="The publication's page on pbo-dpb.ca.")
    pdf_url: str | None = None


class PboSearchResult(BaseModel):
    publications: list[PboPublicationSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    page: int
    last_page: int
    provenance: Provenance


class PboTable(BaseModel):
    reference: str | None = Field(default=None, description="e.g. 'Table 1'.")
    label: str | None = None
    kind: Literal["table", "html", "kvlist"]
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Value]] = Field(
        default_factory=list, description="table and kvlist slices: rows keyed by column label."
    )
    cells: list[list[str]] = Field(
        default_factory=list, description="html slices: rows of cell text as published."
    )
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PboPublication(BaseModel):
    publication: PboPublicationSummary
    has_structured_content: bool = Field(
        description="False for older publications, which are PDF only."
    )
    tables: list[PboTable] = Field(default_factory=list)
    text: str | None = Field(default=None, description="The markdown text, capped.")
    text_truncated: bool = False
    provenance: Provenance


RequestStatus = Literal[
    "completed", "pending", "pending_correspondence", "pending_data", "canceled"
]
Disposition = Literal["all_disclosed", "disclosed_in_part", "nothing_disclosed", "does_not_exist"]


class PboInformationRequestSummary(BaseModel):
    id: str = Field(description="PBO's request number, e.g. 'IR0959' (a few are 'RI…').")
    summary: str = Field(description="What PBO asked for, in PBO's words.")
    department: str
    department_acronym: str | None = None
    request_date: str | None = Field(default=None, description="YYYY-MM-DD.")
    deadline_date: str | None = None
    extension_date: str | None = Field(
        default=None, description="New deadline when the department was given more time."
    )
    status: str = Field(description="completed, pending, pending_correspondence, ...")
    status_label: str
    disposition: str | None = Field(
        default=None,
        description="all_disclosed, disclosed_in_part, nothing_disclosed or does_not_exist; "
        "null while pending or canceled.",
    )
    disposition_label: str | None = None
    disposition_note: str | None = None
    days_past_deadline: int | None = Field(
        default=None,
        description="Open requests only: days since the deadline (or extension) passed; "
        "0 when not yet due.",
    )
    url: str | None = Field(default=None, description="The request's page on pbo-dpb.ca.")


class PboInformationRequestList(BaseModel):
    requests: list[PboInformationRequestSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    page: int
    last_page: int
    by_disposition: dict[str, int] = Field(
        default_factory=dict,
        description="Matched requests by outcome ('none' for pending or canceled).",
    )
    by_status: dict[str, int] = Field(default_factory=dict)
    by_department: dict[str, int] = Field(
        default_factory=dict, description="Matched requests per department, top 15."
    )
    provenance: Provenance


class PboInformationRequestFile(BaseModel):
    document_type: str
    label: str
    mime: str | None = None
    url: str | None = Field(default=None, description="The letter in the requested language.")


class PboInformationRequest(BaseModel):
    request: PboInformationRequestSummary
    files: list[PboInformationRequestFile] = Field(
        default_factory=list, description="PBO's request letter and the department's replies."
    )
    provenance: Provenance

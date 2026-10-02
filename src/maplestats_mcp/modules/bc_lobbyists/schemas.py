"""Typed responses for the BC lobbyists registry (ORL open data)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.modules.bc_lobbyists import constants
from maplestats_mcp.shared.models import Provenance

RegistrationKind = Literal["consultant", "in_house"]
RegistrationStatus = Literal["active", "ended"]
GroupBy = Literal[
    "client", "ministry", "office_holder", "subject_matter", "lobbyist", "month", "year"
]
CodeKind = Literal["subject_matters", "intended_outcomes", "ministries"]


class OrlTopic(BaseModel):
    topic: str = Field(description="The lobbying objective as the filer wrote it.")
    subject_matters: list[str] = Field(default_factory=list)
    intended_outcomes: list[str] = Field(
        default_factory=list,
        description="What the lobbying aims at, as the registry words it (legislation, "
        "regulation, program or policy, contract or grant, privatization).",
    )


class OrlRegistration(BaseModel):
    registration_id: str = Field(description="Registry record id, e.g. 'R-56584653'.")
    registration_number: str = Field(
        description="'filer-client-version', e.g. '9997-443-56'; the last number counts "
        "the approved versions of the registration."
    )
    kind: RegistrationKind
    kind_label: str
    legislation: Literal["lta", "legacy"] = Field(
        description="lta = filed under the Lobbyists Transparency Act (from 2020-05-04)."
    )
    status: RegistrationStatus = Field(
        description="active when the latest version has no end date."
    )
    status_label: str
    first_registered: date | None = Field(
        default=None, description="Start of the earliest version in this registration's chain."
    )
    version_start: date | None = None
    ended: date | None = None
    posted: date | None = None
    client_number: str | None = Field(
        default=None, description="Registry id of the client or organization."
    )
    client_name: str
    client_description: str | None = None
    client_website: str | None = None
    firm: str | None = Field(default=None, description="Consulting firm (consultant returns).")
    filer: str | None = Field(default=None, description="Designated filer.")
    filer_title: str | None = None
    arranges_meetings: bool | None = Field(
        default=None,
        description="Whether a lobbyist will arrange meetings between an office holder and "
        "someone else (not collected before the 2020 Act).",
    )
    lobbyist_count: int
    lobbyists: list[str] = Field(default_factory=list)
    agencies: list[str] = Field(
        default_factory=list, description="Ministries and provincial entities to be contacted."
    )
    topic_count: int
    topics: list[OrlTopic] = Field(default_factory=list)


class OrlRegistrationList(BaseModel):
    registrations: list[OrlRegistration] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_kind: dict[str, int] = Field(default_factory=dict)
    note: str = Field(
        description="Which versions are searched; a superseded version is never listed."
    )
    attribution: str = constants.ATTRIBUTION
    omitted: str
    provenance: Provenance


class OrlRegistrationDetail(BaseModel):
    registrations: list[OrlRegistration] = Field(
        default_factory=list,
        description="The registration, with every lobbyist and topic in full. A "
        "'filer-client' pair without a version returns the current version of each "
        "matching registration.",
    )
    attribution: str = constants.ATTRIBUTION
    omitted: str
    provenance: Provenance


class OrlOfficeHolder(BaseModel):
    name: str
    title: str | None = None
    branch: str | None = None
    agency: str | None = Field(
        default=None,
        description="Ministry or public agency, or 'Member(s) of the BC Legislative Assembly'.",
    )


class OrlActivityReport(BaseModel):
    report_id: str = Field(description="Lobbying activity report id, e.g. 'LAR-10'.")
    meeting_date: date | None = Field(
        default=None, description="Day the lobbying communication took place."
    )
    client_number: str | None = None
    client_name: str
    registration_kind: RegistrationKind | None = None
    filer: str | None = Field(default=None, description="Designated filer who certified it.")
    lobbyists: list[str] = Field(
        default_factory=list,
        description="In-house lobbyists who took part (organization reports only).",
    )
    arranged_meeting: bool | None = Field(
        default=None,
        description="True when the report is about arranging the meeting, not holding it.",
    )
    coalition_members: list[str] = Field(default_factory=list)
    office_holders: list[OrlOfficeHolder] = Field(default_factory=list)
    topics: list[OrlTopic] = Field(default_factory=list)
    topic_count: int
    submitted: date | None = None
    posted: date | None = None


class OrlActivityReportList(BaseModel):
    reports: list[OrlActivityReport] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    first_meeting: date | None = None
    last_meeting: date | None = None
    note: str
    attribution: str = constants.ATTRIBUTION
    omitted: str
    provenance: Provenance


class OrlGroupRow(BaseModel):
    key: str
    reports: int = Field(description="Distinct activity reports counting this key.")
    first_meeting: date | None = None
    last_meeting: date | None = None


class OrlActivitySummary(BaseModel):
    group_by: GroupBy
    rows: list[OrlGroupRow] = Field(default_factory=list)
    groups_total: int = Field(description="Distinct keys found; `rows` shows the top ones.")
    total_reports: int = Field(description="Reports matching the filters.")
    note: str
    attribution: str = constants.ATTRIBUTION
    omitted: str
    provenance: Provenance


class OrlCode(BaseModel):
    code: str | None = None
    name: str
    reports: int | None = Field(
        default=None, description="Activity reports naming it (ministries only)."
    )


class OrlCodeList(BaseModel):
    kind: CodeKind
    codes: list[OrlCode] = Field(default_factory=list)
    total: int
    attribution: str = constants.ATTRIBUTION
    provenance: Provenance

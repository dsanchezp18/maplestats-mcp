"""Typed responses for the House of Commons open data module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Member(BaseModel):
    person_id: int = Field(description="Pass this to ourcommons_get_member_roles.")
    honorific: str | None = None
    first_name: str
    last_name: str
    constituency: str
    province: str
    party: str
    elected: datetime | None = Field(description="Start of the current mandate.")


class MemberList(BaseModel):
    members: list[Member]
    total_members: int = Field(description="Members matching the filters, before the limit.")
    truncated: bool
    provenance: Provenance


class SeatRole(BaseModel):
    constituency: str
    province: str
    party: str
    start: datetime | None
    end: datetime | None


class CaucusRole(BaseModel):
    party: str
    parliament: int | None
    start: datetime | None
    end: datetime | None


class PositionRole(BaseModel):
    title: str
    start: datetime | None
    end: datetime | None


class CommitteeRole(BaseModel):
    committee: str
    role: str
    parliament: int | None
    session: int | None
    start: datetime | None
    end: datetime | None


class AssociationRole(BaseModel):
    organization: str
    role: str
    title: str | None


class ElectionRun(BaseModel):
    election_type: str
    election_date: datetime | None
    constituency: str
    province: str
    party: str
    result: str = Field(description="For example 'Elected', 'Re-Elected', 'Defeated'.")


class MemberRoles(BaseModel):
    person_id: int
    honorific: str | None
    first_name: str
    last_name: str
    seats: list[SeatRole]
    caucus_roles: list[CaucusRole]
    parliamentary_positions: list[PositionRole]
    committee_roles: list[CommitteeRole]
    associations: list[AssociationRole]
    election_history: list[ElectionRun]
    provenance: Provenance


class PartyStanding(BaseModel):
    province: str
    party: str
    seats: int


class PartyTotal(BaseModel):
    party: str
    seats: int


class PartyStandings(BaseModel):
    total_seats: int
    by_party: list[PartyTotal]
    by_province: list[PartyStanding]
    provenance: Provenance


class Minister(BaseModel):
    person_id: int
    order_of_precedence: int
    honorific: str | None
    first_name: str
    last_name: str
    title: str
    province: str
    start: datetime | None
    end: datetime | None


class Ministry(BaseModel):
    ministers: list[Minister]
    provenance: Provenance

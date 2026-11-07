"""Typed responses for the House of Commons open data module."""

from __future__ import annotations

from datetime import date, datetime

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
    seats: int = Field(
        description="Computed by MapleStats: the party's seats summed over by_province."
    )


class PartyStandings(BaseModel):
    total_seats: int = Field(
        description="Computed by MapleStats: the sum of every by_province seat count."
    )
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


class ExpenditureReport(BaseModel):
    fiscal_year: int = Field(description="The year the fiscal year ends: 2027 is 2026-2027.")
    fiscal_year_label: str = Field(description="'2026-2027'.")
    quarter: int = Field(description="1 is April to June, 4 is January to March.")
    period_start: date
    period_end: date
    url: str


class ExpenditureReports(BaseModel):
    total_reports: int
    reports: list[ExpenditureReport] = Field(description="Newest first.")
    provenance: Provenance


class MemberExpenditure(BaseModel):
    name: str = Field(description="'Last, First' as the report writes it, with 'Hon.'.")
    constituency: str
    caucus: str
    salaries: float = Field(description="Salaries of the member's employees, dollars.")
    travel: float
    hospitality: float
    contracts: float = Field(
        description="Service contracts, advertising, office leases and operations, gifts, training."
    )
    total: float = Field(description="Sum of the four categories.")


class ExpenditureTotals(BaseModel):
    salaries: float
    travel: float
    hospitality: float
    contracts: float
    total: float


class MemberExpenditures(BaseModel):
    fiscal_year: int
    quarter: int
    period_start: date
    period_end: date
    members_in_report: int
    total_matches: int
    totals: ExpenditureTotals = Field(description="Sums over every match, before limit.")
    members: list[MemberExpenditure]
    provenance: Provenance


class TravelLine(BaseModel):
    start_date: date | None
    end_date: date | None
    departure: str
    places_visited: str
    purpose: str
    traveller_name: str | None = Field(description="Blank for some designated travellers.")
    traveller_type: str = Field(description="Member, Designated Traveller, Dependant, Employee...")
    transportation: float
    accommodation: float
    meals_and_incidentals: float
    total: float = Field(description="Negative for a refund or correction of an earlier trip.")


class HospitalityLine(BaseModel):
    event_date: date | None
    location: str
    attendees: int | None
    purpose: str
    supplier: str
    amount: float = Field(description="This supplier's amount.")
    event_total: float = Field(
        description="The event's total; an event paid to several suppliers has one line each."
    )


class ContractLine(BaseModel):
    supplier: str
    description: str
    contract_date: date | None
    total: float


class MemberExpenditureDetails(BaseModel):
    name: str
    constituency: str
    caucus: str
    fiscal_year: int
    quarter: int
    period_start: date
    period_end: date
    travel_total: float = Field(description="As in the quarter's summary.")
    hospitality_total: float
    contracts_total: float
    travel: list[TravelLine] | None = Field(description="None when not asked for.")
    hospitality: list[HospitalityLine] | None
    contracts: list[ContractLine] | None
    provenance: Provenance

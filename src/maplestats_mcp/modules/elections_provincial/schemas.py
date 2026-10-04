"""Typed responses for the provincial election results module."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

# A plain string, not a Literal: a Literal rejected "QC" with raw pydantic
# text before the client's own lower-casing could run (seen live 2026-10-03).
# The client validates it and raises InvalidInput listing the codes.
ProvinceCode = Annotated[
    str,
    Field(
        description="Province code: qc, ab, bc, sk or mb (any case, e.g. QC).",
        examples=["qc", "ab", "bc", "sk", "mb"],
    ),
]


class ElectionInfo(BaseModel):
    province: str = Field(description="Province code: qc, ab, bc, sk or mb.")
    province_name: str
    date: str = Field(description="Polling day, YYYY-MM-DD.")
    seats: int = Field(description="Electoral districts (seats) contested.")
    detail: str = Field(
        description="What each row holds: 'candidate' (every candidate's votes) or 'party' "
        "(votes by party in each district, the winner's name only)."
    )
    source_url: str


class BlockedSource(BaseModel):
    province: str
    source: str
    url: str = Field(description="The page whose terms rule it out.")
    reason: str


class ElectionList(BaseModel):
    elections: list[ElectionInfo]
    blocked: list[BlockedSource]
    notes: list[str]
    provenance: Provenance


class ResultRow(BaseModel):
    province: str
    election_date: str
    district: str = Field(description="Electoral district (riding, electoral division) name.")
    district_number: str | None = Field(
        description="The source's district number or code (Quebec number, Alberta ED, "
        "BC abbreviation, Saskatchewan code); null for Manitoba."
    )
    candidate: str | None = Field(
        description="Candidate name as 'First Last'. Null for Alberta rows other than the "
        "winner, because Alberta's summary page lists parties, not candidates."
    )
    party: str | None = Field(description="Party name (Quebec: the abbreviation if no name).")
    party_code: str | None = Field(
        description="Party abbreviation as published (Quebec, Alberta, Saskatchewan, Manitoba); "
        "null for BC."
    )
    votes: int
    vote_share: float | None = Field(description="Percent of the district's valid votes.")
    elected: bool = Field(description="True for the candidate with the most votes in the district.")


class DistrictSummary(BaseModel):
    district: str
    electors: int | None = Field(description="Registered electors (Quebec, Manitoba).")
    valid_votes: int | None
    rejected_ballots: int | None = Field(
        description="Quebec, British Columbia, Saskatchewan, Manitoba."
    )
    turnout: float | None = Field(
        description="Percent of electors who voted (Quebec, Alberta, Manitoba)."
    )
    winner: str | None = Field(description="Winning candidate, or the winning party if unnamed.")


class ElectionResults(BaseModel):
    province: str
    election_date: str
    rows: list[ResultRow]
    districts: list[DistrictSummary] = Field(
        description="Summary of the districts on this page of rows."
    )
    total_rows: int = Field(description="Rows matching the filters, before offset and limit.")
    offset: int
    truncated: bool
    attribution: str
    provenance: Provenance


class PartySummary(BaseModel):
    party: str
    candidates: int = Field(description="Districts where the party had votes recorded.")
    seats: int
    votes: int
    vote_share: float = Field(description="Percent of all valid votes in the province.")


class SeatSummary(BaseModel):
    province: str
    election_date: str
    seats_contested: int
    seats_decided: int = Field(description="Districts with a winner; equals seats_contested.")
    total_valid_votes: int
    parties: list[PartySummary] = Field(description="By seats, then votes.")
    attribution: str
    provenance: Provenance


class VotingAreaRow(BaseModel):
    district: str
    voting_area: str = Field(
        description="Voting area number as published, or a special poll's label (advance, "
        "absentee, homebound, write-in ballots)."
    )
    voting_place: str | None = Field(description="Polling place; null where not given (2023).")
    candidate: str | None = Field(description="Candidate name as 'First Last'.")
    party: str | None
    party_code: str | None
    votes: int


class VotingAreaSummary(BaseModel):
    voting_area: str
    voting_place: str | None
    electors: int | None = Field(description="Registered voters; 0 or null for special polls.")
    valid_votes: int
    rejected_ballots: int
    declined_ballots: int


class VotingAreaResults(BaseModel):
    province: str
    election_date: str
    district: str
    rows: list[VotingAreaRow]
    areas: list[VotingAreaSummary] = Field(description="Every voting area of the district.")
    total_rows: int = Field(description="Rows matching the filters, before offset and limit.")
    offset: int
    truncated: bool
    district_valid_votes: int = Field(
        description="The district's valid votes in the official summary of votes received."
    )
    areas_valid_votes: int = Field(
        description="Valid votes summed over the voting areas; differs from "
        "district_valid_votes where the source's voting-area file does."
    )
    attribution: str
    provenance: Provenance

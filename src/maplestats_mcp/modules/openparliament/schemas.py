"""Typed responses for the OpenParliament.ca API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class BillSummary(BaseModel):
    session: str = Field(description="Parliament-session, e.g. '45-1'.")
    number: str = Field(description="Bill number, e.g. 'C-2'.")
    name: str
    introduced: dt.date | None = None
    url: str


class BillSearchResult(BaseModel):
    bills: list[BillSummary]
    total_matches: int
    returned_count: int
    provenance: Provenance


class VoteSummary(BaseModel):
    session: str
    number: int
    date: dt.date | None = None
    description: str
    result: str | None = None
    yea_total: int | None = None
    nay_total: int | None = None
    paired_total: int | None = None
    bill: str | None = Field(default=None, description="Bill number, when the vote is on a bill.")
    url: str


class Bill(BaseModel):
    session: str
    number: str
    name: str
    short_title: str | None = None
    introduced: dt.date | None = None
    status: str | None = None
    status_code: str | None = None
    home_chamber: str | None = None
    private_member_bill: bool | None = None
    became_law: bool | None = None
    sponsor: str | None = Field(default=None, description="Sponsor MP slug.")
    text_url: str | None = None
    legisinfo_url: str | None = None
    votes: list[VoteSummary]
    url: str
    provenance: Provenance


class VoteSearchResult(BaseModel):
    votes: list[VoteSummary] = Field(description="Most recent first.")
    returned_count: int
    has_more: bool
    provenance: Provenance


class PartyVote(BaseModel):
    party: str
    vote: str
    disagreement: float | None = Field(
        default=None, description="Share of the caucus that voted against its majority."
    )


class Ballot(BaseModel):
    politician: str = Field(description="MP slug, for parliament_get_politician.")
    ballot: str


class Vote(BaseModel):
    vote: VoteSummary
    party_votes: list[PartyVote]
    ballots: list[Ballot] = Field(description="Empty unless include_ballots.")
    provenance: Provenance


class PoliticianSummary(BaseModel):
    slug: str
    name: str
    party: str | None = None
    riding: str | None = None
    province: str | None = None
    current: bool


class PoliticianSearchResult(BaseModel):
    politicians: list[PoliticianSummary]
    total_matches: int
    returned_count: int
    provenance: Provenance


class Membership(BaseModel):
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    party: str | None = None
    riding: str | None = None
    province: str | None = None


class Politician(BaseModel):
    slug: str
    name: str
    email: str | None = None
    phone: str | None = None
    memberships: list[Membership] = Field(description="Most recent first.")
    links: list[str]
    url: str
    provenance: Provenance


class Speech(BaseModel):
    time: str | None = None
    speaker: str | None = None
    politician: str | None = Field(default=None, description="MP slug, when the speaker is an MP.")
    text: str = Field(description="Plain text, HTML removed.")
    procedural: bool | None = None
    document: str | None = Field(
        default=None, description="Debate or committee meeting, e.g. /debates/2026/9/23/."
    )
    url: str


class HansardHit(BaseModel):
    date: dt.date | None = None
    document_type: str | None = Field(
        default=None, description="'House debate' or 'Committee meeting'."
    )
    topic: str | None = None
    excerpt: str = Field(description="Matching passage, plain text.")
    speaker: str | None = None
    politician: str | None = Field(default=None, description="MP slug, when the speaker is an MP.")
    party: str | None = None
    url: str


class HansardSearchResult(BaseModel):
    query: str
    hits: list[HansardHit]
    total_matches: int | None = None
    page: int
    has_more: bool
    provenance: Provenance


class SpeechSearchResult(BaseModel):
    speeches: list[Speech]
    returned_count: int
    has_more: bool
    provenance: Provenance


class CommitteeSummary(BaseModel):
    slug: str = Field(description="Committee slug for other parliament_ committee tools.")
    name: str
    short_name: str | None = None
    parent: str | None = Field(default=None, description="Parent committee slug, if any.")
    url: str


class CommitteeListResult(BaseModel):
    session: str | None = Field(
        default=None, description="Session asked for; None means the current session."
    )
    committees: list[CommitteeSummary]
    returned_count: int
    provenance: Provenance


class CommitteeSession(BaseModel):
    session: str = Field(description="Parliament-session, e.g. '45-1'.")
    acronym: str | None = Field(default=None, description="House of Commons acronym, e.g. 'FINA'.")
    source_url: str | None = Field(
        default=None, description="Committee page on ourcommons.ca (noscommunes.ca for lang='fr')."
    )


class CommitteeMeetingSummary(BaseModel):
    committee: str = Field(description="Committee slug.")
    session: str
    number: int
    date: dt.date | None = None
    in_camera: bool | None = Field(default=None, description="Held in private (no transcript).")
    has_evidence: bool | None = Field(
        default=None, description="A transcript (evidence) is available."
    )
    url: str


class Committee(BaseModel):
    slug: str
    name: str
    short_name: str | None = None
    parent: str | None = Field(default=None, description="Parent committee slug, if any.")
    subcommittees: list[str] = Field(description="Subcommittee slugs.")
    sessions: list[CommitteeSession] = Field(description="Sessions it sat in, most recent first.")
    recent_meetings: list[CommitteeMeetingSummary] = Field(description="Most recent first.")
    url: str
    provenance: Provenance


class CommitteeMeetingSearchResult(BaseModel):
    meetings: list[CommitteeMeetingSummary] = Field(description="Most recent first.")
    returned_count: int
    has_more: bool
    provenance: Provenance


class Witness(BaseModel):
    name: str
    role: str | None = Field(
        default=None, description="Title and organization as given in the transcript."
    )


class CommitteeMeeting(BaseModel):
    meeting: CommitteeMeetingSummary
    start_time: str | None = None
    end_time: str | None = None
    minutes_url: str | None = Field(
        default=None, description="ourcommons.ca minutes (noscommunes.ca for lang='fr')."
    )
    notice_url: str | None = Field(
        default=None, description="ourcommons.ca notice (noscommunes.ca for lang='fr')."
    )
    webcast_url: str | None = Field(default=None, description="Webcast link as the API gives it.")
    witnesses: list[Witness] = Field(
        description="Non-MP witnesses who spoke, in order of first appearance."
    )
    total_speeches: int
    speeches: list[Speech] = Field(description="Transcript slice from offset, in spoken order.")
    offset: int
    has_more: bool
    provenance: Provenance

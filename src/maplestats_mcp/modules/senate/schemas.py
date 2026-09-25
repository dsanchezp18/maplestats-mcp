"""Typed responses for Senate of Canada votes."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class SenateVoteSummary(BaseModel):
    vote_id: int = Field(description="sencanada.ca vote id, for senate_get_vote.")
    session: str
    date: dt.date | None = None
    title: str
    bill: str | None = Field(default=None, description="Related bill number, e.g. 'C-6'.")
    result: str | None = None
    yeas: int | None = None
    nays: int | None = None
    abstentions: int | None = None
    url: str


class SenateVoteList(BaseModel):
    session: str
    votes: list[SenateVoteSummary] = Field(description="Most recent first.")
    total_matches: int
    returned_count: int
    sessions_available: list[str]
    provenance: Provenance


class SenatorBallot(BaseModel):
    senator: str = Field(description="'Last, First' as the Senate lists it.")
    affiliation: str | None = Field(default=None, description="Group, e.g. ISG, CSG, PSG, C.")
    province: str | None = None
    vote: str = Field(description="Yea, Nay, Abstention, or '' when not recorded.")


class SenateVote(BaseModel):
    vote_id: int
    session: str
    date_text: str | None = Field(default=None, description="As printed on the vote page.")
    title: str
    bill: str | None = None
    yeas: int
    nays: int
    abstentions: int
    ballots: list[SenatorBallot]
    url: str
    provenance: Provenance

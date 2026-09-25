"""Typed responses for IRCC's Express Entry rounds-of-invitations feed."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CrsScoreDistribution(BaseModel):
    """Candidate-pool counts by CRS score band, as of the round's own
    `pool_distribution_as_of` date.

    Band labels and the broad/detail split were confirmed live 2026-09-18
    by matching each round's dd1-dd18 feed fields against the score-range
    labels on the rendered rounds-invitations page, then checking that
    band_601_1200 + band_501_600 + band_451_500 + band_401_450 +
    band_351_400 + band_301_350 + band_0_300 == total for every round in
    the feed. band_451_500 and band_401_450 are broad-band totals; the
    *_491_500 through *_451_460 and *_441_450 through *_401_410 fields are
    their detailed sub-ranges, not independent bands to sum separately.
    """

    band_601_1200: int
    band_501_600: int
    band_451_500: int
    band_491_500: int
    band_481_490: int
    band_471_480: int
    band_461_470: int
    band_451_460: int
    band_401_450: int
    band_441_450: int
    band_431_440: int
    band_421_430: int
    band_411_420: int
    band_401_410: int
    band_351_400: int
    band_301_350: int
    band_0_300: int
    total: int


class ExpressEntryRound(BaseModel):
    """One Express Entry round of invitations.

    ``draw_number`` is a string, not an int: on 2026-09-18 the feed was
    confirmed to contain "91a" and "91b" for two rounds IRCC ran on the
    same day (2018-05-30, Federal Skilled Trades and Provincial Nominee
    Program respectively) instead of separate sequential numbers.
    """

    draw_number: str
    draw_date: date
    draw_name: str = Field(
        description="The round's full descriptive name, e.g. a category-based "
        "draw's category or 'No Program Specified' for early general draws."
    )
    program: str = Field(
        description="The invited program(s)/category, e.g. 'Canadian Experience Class'."
    )
    invitations_issued: int
    crs_cutoff: int
    pool_distribution_as_of: str = Field(
        description="Date the candidate-pool CRS distribution snapshot was "
        "taken, as published by IRCC (locale-formatted text, not parsed -- "
        "the source does not publish a machine-readable version of this field)."
    )
    eligibility_cutoff: str | None = Field(
        default=None,
        description="When profiles had to be submitted by to be eligible for "
        "this round, as published by IRCC (locale-formatted text with a UTC "
        "time; null for early rounds that did not publish one).",
    )
    crs_distribution: CrsScoreDistribution
    details_url: str = Field(description="The round's own page on canada.ca.")


class ExpressEntryRoundDetail(BaseModel):
    round: ExpressEntryRound
    provenance: Provenance


class ExpressEntryRoundsResult(BaseModel):
    rounds: list[ExpressEntryRound]
    total_matching: int = Field(
        description="Rounds matching `program`/`since`, before `limit` is applied."
    )
    returned_count: int
    limit: int
    program: str | None = None
    since: date | None = None
    provenance: Provenance

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Fishery = Literal["sea", "freshwater"]


class LandingsFile(BaseModel):
    year: int | None = Field(description="Year of a freshwater file; None for the sea file.")
    language: str
    url: str


class LandingsTable(BaseModel):
    fishery: Fishery
    title: str
    dataset_id: str
    dataset_url: str
    first_year: int | None
    last_year: int | None
    quantity_unit_published: str
    value_unit_published: str
    regions: str = Field(description="Provinces and territories the table covers.")
    files: list[LandingsFile]
    last_modified: str | None


class LandingsCatalogue(BaseModel):
    tables: list[LandingsTable]
    provenance: Provenance


class LandingsRow(BaseModel):
    year: int
    region: str = Field(
        description="Province or territory as published; also 'Atlantic' (sea, sum of the "
        "Atlantic provinces) and 'Canada'."
    )
    species_group: str | None = Field(
        description="Groundfish, Pelagics, Shellfish, Other or Grand total (sea only)."
    )
    species: str
    quantity_tonnes: float | None = Field(
        description="Live weight in tonnes (sea: DFO's kilograms divided by 1,000)."
    )
    value_dollars: float | None = Field(
        description="Landed value in Canadian dollars (freshwater: DFO's thousands of dollars "
        "times 1,000)."
    )
    suppressed: bool = Field(description="DFO's 'x': withheld for confidentiality.")
    is_total: bool = Field(description="A total row (group total, grand total or 'Total').")


class Landings(BaseModel):
    fishery: Fishery
    years: list[int]
    rows: list[LandingsRow]
    rows_matched: int
    notes: list[str] = Field(description="DFO's notes and footnotes from the files read.")
    provenance: Provenance

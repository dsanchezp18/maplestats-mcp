"""Typed responses for the CBSA Customs Tariff module."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Level = Literal["chapter", "heading", "subheading", "tariff_item", "classification", "other"]


class TariffEdition(BaseModel):
    edition: str = Field(description="CBSA's label without the T, e.g. '2026-2' or '2026'.")
    effective_date: date
    year: int
    access_zip_url: str = Field(description="The Microsoft Access file this module reads.")
    pdf_url: str | None = None
    html_url: str | None = Field(default=None, description="The tariff by chapter, as web pages.")


class TariffEditions(BaseModel):
    editions: list[TariffEdition] = Field(description="Newest first.")
    years: list[int] = Field(description="The years whose pages were read.")
    provenance: Provenance


class TariffRate(BaseModel):
    code: str = Field(description="Treatment code, e.g. MFN, GT, UST, CEUT, CPTPT.")
    name: str
    text: str = Field(description="The rate as CBSA wrote it: 'Free', '6.5 %', '35%', '$1.23/kg'.")
    percent: float | None = Field(
        default=None,
        description="The rate as a number when it is a plain percentage or free (0); None for "
        "specific, compound or conditional rates, which only `text` gives.",
    )


class TariffLine(BaseModel):
    tariff: str = Field(
        description="As printed: '01.01', '0101.21', '0101.21.00', '0101.21.00.00'."
    )
    digits: str = Field(description="The number without dots, as cimt_ tools take `hs_code`.")
    level: Level
    description: str
    description_truncated: bool = False
    sub_chapter: str | None = Field(default=None, description="Sub-chapter title, on headings.")
    unit_of_measure: str | None = Field(default=None, description="E.g. KGM, NMB, LTR.")
    footnote: str | None = None
    effective_date: date | None = Field(
        default=None, description="When this line last changed (CBSA's EFF_DATE)."
    )
    changed_in_edition: bool = Field(
        default=False, description="Whether CBSA flagged this line as changed in this edition."
    )
    mfn: str | None = Field(default=None, description="Most-Favoured-Nation rate, as written.")
    general: str | None = Field(default=None, description="General Tariff rate, as written.")
    rates: list[TariffRate] = Field(
        default_factory=list,
        description="Every treatment with a rate on this line, MFN and General first.",
    )


class TariffLookup(BaseModel):
    edition: TariffEdition
    query: str
    item: TariffLine | None = Field(
        default=None, description="The line itself, when the number exists as given."
    )
    ancestors: list[TariffLine] = Field(
        default_factory=list, description="Its heading and subheadings, broadest first."
    )
    children: list[TariffLine] = Field(
        default_factory=list, description="Lines under it (tariff items, classification numbers)."
    )
    total_children: int = 0
    note: str | None = None
    provenance: Provenance


class TariffSearch(BaseModel):
    edition: TariffEdition
    query: str
    chapter: str | None = None
    lines: list[TariffLine] = Field(default_factory=list)
    total_matches: int
    returned_count: int
    provenance: Provenance

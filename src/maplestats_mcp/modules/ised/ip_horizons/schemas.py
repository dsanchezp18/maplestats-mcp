"""Typed responses for CIPO's IP Horizons researcher datasets."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

IpType = Literal["patent", "industrial_design", "trademark"]


class IpHorizonsFile(BaseModel):
    ip_type: IpType
    table: str = Field(description="Table name without its prefix, e.g. 'main', 'claim'.")
    text_format: bool = Field(description="True for the '_txt_format' variant of a table.")
    number_from: int | None = Field(
        default=None, description="First patent number in this file, when the table is split."
    )
    number_to: int | None = Field(
        default=None, description="Last patent number in this file, when the table is split."
    )
    release_date: date | None = None
    name: str
    url: str


class IpHorizonsCatalogue(BaseModel):
    files: list[IpHorizonsFile] = Field(default_factory=list)
    returned_count: int
    tables: list[str] = Field(
        default_factory=list, description="Every table the package lists, in any release."
    )
    provenance: Provenance


class DictionaryField(BaseModel):
    table: str
    name_en: str
    name_fr: str | None = None
    type_en: str | None = None
    type_fr: str | None = None
    description_en: str | None = None
    description_fr: str | None = None


class IpHorizonsDictionary(BaseModel):
    ip_type: IpType
    fields: list[DictionaryField] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="Coverage, delimiter and encoding notes."
    )
    provenance: Provenance

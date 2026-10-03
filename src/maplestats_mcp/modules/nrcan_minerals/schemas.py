"""Typed responses for NRCan annual mineral production."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Symbol = Literal["preliminary", "confidential", "not_available", "final"]


class MineralRow(BaseModel):
    year: int
    group: str | None = Field(
        default=None, description="Metals, Non-metals, Aggregates..., or a total section."
    )
    commodity: str = Field(description="Name without the file's footnote markers.")
    province: str = Field(description="Province, territory or 'Canada'.")
    category: str = Field(
        description="Value of shipments, Quantity shipped, or (2019 on) Quantity produced."
    )
    units: str | None = Field(
        default=None, description="As published: thousands of dollars, tonnes, kilotonnes..."
    )
    value: float | None = Field(default=None, description="None when confidential or n/a.")
    symbol: Symbol = Field(
        description="preliminary (p), confidential (x), not_available (..), or final."
    )


class MineralProduction(BaseModel):
    year: int
    title: str = Field(description="The file's own title.")
    preliminary: bool
    rows: list[MineralRow] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    commodities: list[str] = Field(default_factory=list, description="Commodities in this year.")
    available_years: list[int] = Field(default_factory=list)
    provenance: Provenance


class MineralSeries(BaseModel):
    commodity: str
    province: str
    category: str
    points: list[MineralRow] = Field(default_factory=list)
    missing_years: list[int] = Field(
        default_factory=list, description="Years whose file has no row for this commodity."
    )
    note: str = Field(
        description="Units and commodity definitions changed over time; read each point's units."
    )
    provenance: Provenance

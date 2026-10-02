"""Typed responses for StatCan's Canadian International Merchandise Trade (CIMT) API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class CimtPeriods(BaseModel):
    first_period: str = Field(description="First month with data, YYYY-MM.")
    latest_period: str = Field(description="Latest month with data, YYYY-MM.")
    provenance: Provenance


class CommodityMatch(BaseModel):
    code: str
    level: str = Field(description="chapter, heading, hs6 or national.")
    description: str
    unit_code: str | None = Field(default=None, description="Unit of measure code (HS6 and below).")
    unit: str | None = Field(
        default=None, description="Unit of measure, in the requested language."
    )
    valid_from: str | None = Field(default=None, description="First month the code was used.")
    valid_to: str | None = Field(
        default=None, description="Last month the code was used; empty if current."
    )


class CommoditySearchResult(BaseModel):
    query: str
    direction: str
    level: str
    commodities: list[CommodityMatch] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class PartnerMatch(BaseModel):
    kind: str = Field(description="country, us_state or province.")
    code: int = Field(description="The CIMT identifier to use as a path parameter.")
    iso_code: str | None = Field(
        default=None, description="ISO-style country code, countries only."
    )
    name: str
    valid_from: str | None = None
    valid_to: str | None = None


class PartnerSearchResult(BaseModel):
    query: str
    kind: str
    partners: list[PartnerMatch] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    provenance: Provenance


class TradeRow(BaseModel):
    period: str = Field(description="YYYY-MM, or YYYY when annualized.")
    hs_code: str
    hs_description: str | None = None
    partner_code: int
    partner: str
    us_state_code: int | None = Field(
        default=None, description="US state when the row is split by state; empty otherwise."
    )
    us_state: str | None = None
    province_code: int
    province: str
    value_cad: float = Field(description="Canadian dollars, current prices.")
    quantity: float | None = None
    unit_code: str | None = None
    unit: str | None = None


class TradeResult(BaseModel):
    direction: str
    hs_level: str
    annualized: bool
    from_period: str
    to_period: str
    rows: list[TradeRow] = Field(default_factory=list)
    returned_count: int
    total_count: int = Field(description="Rows the query matches upstream, before the row limit.")
    truncated: bool = Field(
        description="True when the limit cut the result; the rows kept are then an "
        "arbitrary subset, so narrow the query instead of reading them as a ranking."
    )
    returned_value_cad: float = Field(description="Sum of value_cad over the returned rows.")
    provenance: Provenance


class RankedItem(BaseModel):
    rank: int
    code: str
    name: str
    value_cad: float
    share_of_total: float | None = Field(
        default=None, description="Share of the all-partner (or all-province) total, 0 to 1."
    )


class TopPartnersResult(BaseModel):
    direction: str
    period: str
    view: str = Field(description="country or us_state.")
    hs_chapter: str | None = None
    province: str
    total_value_cad: float
    partners: list[RankedItem] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance


class TopCommoditiesResult(BaseModel):
    direction: str
    period: str
    hs_level: str
    hs_chapter: str | None = None
    province: str
    partner: str
    commodities: list[RankedItem] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance


class ProvinceBreakdownResult(BaseModel):
    direction: str
    period: str
    partner: str
    hs_chapter: str | None = None
    domestic_value_cad: float = Field(
        description="Exports: domestic exports. Imports: all imports."
    )
    reexport_value_cad: float
    provinces: list[RankedItem] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance


class SeriesPoint(BaseModel):
    period: str = Field(description="YYYY-MM.")
    measure: str = Field(
        description="value, domestic_value, reexport_value, quantity, domestic_quantity "
        "or reexport_quantity."
    )
    value: float


class SeriesResult(BaseModel):
    direction: str
    hs_code: str
    partner: str
    province: str
    from_period: str
    to_period: str
    unit: str | None = Field(default=None, description="Unit of the quantity measures.")
    points: list[SeriesPoint] = Field(default_factory=list)
    returned_count: int
    provenance: Provenance

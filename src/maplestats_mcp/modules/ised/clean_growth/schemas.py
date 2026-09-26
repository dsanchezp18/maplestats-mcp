"""Typed response for federal cleantech investment."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class ValueRow(BaseModel):
    label: str
    value_cad: float | None = Field(default=None, description="Dollars (not billions).")
    share_percent: float | None = None


class Headline(BaseModel):
    period: str | None = None
    programs: int | None = None
    organizations: int | None = None
    committed_cad: float | None = None
    agreements: int | None = Field(default=None, description="Lower bound ('over 8,300').")
    median_agreement_cad: float | None = None
    for_profit_cad: float | None = Field(default=None, description="Approximate ('almost').")
    non_repayable_share_percent: float | None = None
    development_cad: float | None = None
    business_support_cad: float | None = None
    adoption_cad: float | None = None
    jobs_created_or_maintained: int | None = Field(
        default=None, description="From about 17% of projects; not representative."
    )


class FederalInvestment(BaseModel):
    headline: Headline
    by_year: list[ValueRow] = Field(default_factory=list)
    by_province: list[ValueRow] = Field(
        default_factory=list, description="Share of funding agreements signed, not dollars."
    )
    by_subsector: list[ValueRow] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    pdf_url: str
    records_dataset: str = Field(
        description="open.canada.ca dataset the projects were identified from."
    )
    records_resource_id: str = Field(
        description="Its DataStore table, for ckan_datastore_search(portal='federal')."
    )
    provenance: Provenance

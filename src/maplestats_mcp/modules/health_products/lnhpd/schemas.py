"""Typed responses for the Licensed Natural Health Products Database tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class NhpProductName(BaseModel):
    npn: str = Field(description="Natural Product Number (or DIN-HM / old DIN), 8 digits.")
    lnhpd_id: int = Field(description="LNHPD product id used by the detail endpoints.")
    product_name: str
    primary_name: bool = Field(description="False for an additional brand name of the licence.")
    company_name: str | None = None
    dosage_form: str | None = None
    active: bool = Field(description="Whether the licence is active.")
    status_code: int = Field(description="LNHPD product status flag: 1 active, others not active.")
    licence_date: str | None = None
    revised_date: str | None = None


class NhpSearchResult(BaseModel):
    products: list[NhpProductName] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    licences_matched: int = Field(description="Distinct NPNs among the matched names.")
    provenance: Provenance


class NhpMedicinalIngredient(BaseModel):
    name: str
    quantity: float | None = None
    quantity_unit: str | None = None
    potency: str | None = Field(default=None, description="Potency amount, unit and constituent.")
    extract_ratio: str | None = None
    dried_herb_equivalent: str | None = None
    source_material: str | None = None


class NhpDose(BaseModel):
    population: str | None = None
    age: str | None = None
    dose: str | None = None
    frequency: str | None = None


class NhpRisk(BaseModel):
    risk_type: str | None = None
    sub_type: str | None = None
    text: str


class NhpProductDetail(BaseModel):
    npn: str
    lnhpd_id: int
    names: list[NhpProductName] = Field(default_factory=list)
    submission_type: str | None = None
    attested_monograph: bool | None = None
    medicinal_ingredients: list[NhpMedicinalIngredient] = Field(default_factory=list)
    non_medicinal_ingredients: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    doses: list[NhpDose] = Field(default_factory=list)
    purposes: list[str] = Field(
        default_factory=list, description="Recommended uses, as the licence holder filed them."
    )
    risks: list[NhpRisk] = Field(default_factory=list)
    lnhpd_page: str
    provenance: Provenance

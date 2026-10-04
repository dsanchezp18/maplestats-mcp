"""Typed responses for the Drug Product Database tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

DrugStatus = Literal[
    "approved",
    "marketed",
    "cancelled_pre_market",
    "cancelled_post_market",
    "dormant",
    "cancelled_unreturned_annual",
    "cancelled_safety_issue",
    "authorized_interim_order",
    "interim_order_revoked",
    "restricted_access",
    "interim_order_expired",
    "cancelled_biocides",
]


class DrugProductSummary(BaseModel):
    drug_code: int = Field(description="DPD internal product code (pass to hc_drug_get_product).")
    din: str | None = Field(default=None, description="Drug Identification Number (8 digits).")
    brand_name: str | None = None
    descriptor: str | None = None
    company_name: str | None = None
    product_class: str | None = Field(
        default=None, description="Human, Veterinary, Disinfectant or Radiopharmaceutical."
    )
    number_of_active_ingredients: int | None = None
    ai_group_no: str | None = Field(
        default=None, description="Active ingredient group number (same ingredients and strengths)."
    )
    status: str | None = Field(default=None, description="Current status label.")
    status_code: int | None = None
    status_date: str | None = Field(default=None, description="Date of the current status.")
    last_update_date: str | None = None


class DrugProductList(BaseModel):
    products: list[DrugProductSummary] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Matched products per status label."
    )
    provenance: Provenance


class ActiveIngredient(BaseModel):
    name: str
    strength: str | None = None
    strength_unit: str | None = None
    dosage_value: str | None = None
    dosage_unit: str | None = Field(
        default=None, description="Per-dosage unit, e.g. strength per 5 ML."
    )


class DrugCompany(BaseModel):
    company_code: int | None = None
    name: str
    company_type: str | None = None
    street: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    postal_code: str | None = None


class TherapeuticClass(BaseModel):
    atc_code: str | None = None
    atc_description: str | None = None


class DrugProductDetail(BaseModel):
    product: DrugProductSummary
    original_market_date: str | None = None
    lot_number: str | None = Field(
        default=None, description="Last lot sold, for a product the company discontinued."
    )
    expiration_date: str | None = None
    active_ingredients: list[ActiveIngredient] = Field(default_factory=list)
    schedules: list[str] = Field(default_factory=list)
    dosage_forms: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    therapeutic_classes: list[TherapeuticClass] = Field(default_factory=list)
    packaging: list[str] = Field(
        default_factory=list, description="Package descriptions as filed (sizes and types)."
    )
    pharmaceutical_standard: str | None = None
    veterinary_species: list[str] = Field(default_factory=list)
    company: DrugCompany | None = Field(
        default=None, description="The DIN owner's address, matched by name in the company table."
    )
    dpd_page: str = Field(description="The public DPD search page.")
    provenance: Provenance


class IngredientMatch(BaseModel):
    name: str
    product_count: int = Field(description="Drug products (any status) listing this ingredient.")
    strengths: list[str] = Field(
        default_factory=list, description="Most common strengths, e.g. '500 MG'."
    )


class IngredientList(BaseModel):
    ingredients: list[IngredientMatch] = Field(default_factory=list)
    total_matched: int
    provenance: Provenance

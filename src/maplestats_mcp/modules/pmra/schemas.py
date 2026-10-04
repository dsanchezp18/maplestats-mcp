"""Typed responses for the PMRA pesticide registry."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class PesticideProduct(BaseModel):
    registration_number: str
    product_name: str = Field(description="Name in the requested language (English if none).")
    product_name_en: str
    product_name_fr: str | None = None
    registration_status: str | None = Field(
        default=None, description="e.g. Full Registration, Cancelled, Emergency Registration."
    )
    current: bool = Field(description="True when the product is currently registered.")
    expiry_date: str | None = None
    date_first_registered: str | None = None
    marketing_type: str | None = Field(
        default=None, description="COMMERCIAL, DOMESTIC, RESTRICTED, TECHNICAL ACTIVE, ..."
    )
    product_type: str | None = Field(default=None, description="e.g. HERBICIDE, INSECTICIDE.")
    registrant: str | None = None
    active_ingredients: list[str] = Field(default_factory=list)
    use_site_categories: str | None = None


class ActiveIngredient(BaseModel):
    name: str = Field(description="As written in the product record.")
    name_fr: str | None = None
    cas_number: str | None = None
    under_reevaluation: bool | None = Field(
        default=None, description="The ingredient extract's re-evaluation flag (YES/NO)."
    )
    mrl_chemical: str | None = Field(
        default=None, description="The chemical name its maximum residue limits are listed under."
    )
    mrl_count: int = Field(default=0, description="Commodities with an MRL for that chemical.")


class PesticideProductDetail(BaseModel):
    product: PesticideProduct
    ingredients: list[ActiveIngredient] = Field(default_factory=list)
    sites_of_use: list[str] = Field(default_factory=list)
    pests: list[str] = Field(default_factory=list)
    lists_truncated: bool = Field(
        default=False,
        description="True when the source cut sites of use or pests at 2,000 characters.",
    )
    provenance: Provenance


class PesticideProductList(BaseModel):
    products: list[PesticideProduct] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    by_product_type: dict[str, int] = Field(default_factory=dict)
    provenance: Provenance


class ResidueLimit(BaseModel):
    chemical: str
    commodity: str
    mrl_ppm: float | None = Field(default=None, description="Maximum residue limit, ppm.")
    comments: str | None = Field(default=None, description="e.g. 'except head lettuce'.")
    established_via: str | None = Field(
        default=None, description="The regulatory action, e.g. 'EMRL2008-02 (9 July 2008)'."
    )


class ResidueLimitList(BaseModel):
    limits: list[ResidueLimit] = Field(default_factory=list)
    returned_count: int
    total_matched: int
    chemicals: list[str] = Field(default_factory=list, description="Chemicals matched.")
    provenance: Provenance

"""Typed responses for NRCan's National Energy Use Database pages."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance


class Product(BaseModel):
    product: str = Field(description="Key for nrcan_energy_use_list_tables.")
    name: str


class ComprehensiveMenu(BaseModel):
    sector: str
    sector_name: str
    jurisdiction: str
    jurisdiction_name: str


class ProductList(BaseModel):
    surveys: list[Product]
    comprehensive: list[ComprehensiveMenu] = Field(
        description="Sector/jurisdiction pairs for product='comprehensive'."
    )
    provenance: Provenance


class TableRef(BaseModel):
    table_number: str
    title: str
    table_key: str = Field(description="Pass to nrcan_energy_use_get_table.")


class TableList(BaseModel):
    product: str
    tables: list[TableRef]
    menu_url: str
    provenance: Provenance


class EnergyTable(BaseModel):
    table_key: str
    title: str
    header_rows: list[list[str]]
    rows: list[list[str]] = Field(
        description="First cell is the row label. Survey tables follow each value "
        "with a data-quality letter explained in `notes`."
    )
    notes: list[str] = Field(default_factory=list)
    source_url: str
    provenance: Provenance

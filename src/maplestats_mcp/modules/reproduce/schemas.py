"""Typed response for reproduce_code."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from maplestats_mcp.shared.models import Provenance

Language = Literal["r", "python", "stata", "julia", "excel"]
LanguageChoice = Literal["all", "r", "python", "stata", "julia", "excel"]


class Script(BaseModel):
    language: Language
    code: str = Field(
        description="A complete script: header, setup, retrieval, checks, the tool's "
        "filters, then source-specific and standard cleaning. For excel, a Power Query M "
        "query to paste into Excel's Advanced Editor (Get Data > Blank Query)."
    )
    packages: list[str] = Field(description="Packages the code needs.")


class ReproductionCode(BaseModel):
    tool: str
    scripts: list[Script] = Field(description="One script per language that can fetch this source.")
    source_url: str = Field(description="The URL the scripts fetch.")
    method: str = Field(
        description="How the request was rebuilt: from the tool's arguments, from the "
        "request the tool made (recorded while it ran), or 'none' when no script can fetch it."
    )
    notes: list[str]
    provenance: Provenance


class ExcelWorkbook(BaseModel):
    file_name: str = Field(description="Suggested file name for the workbook (.xlsx).")
    media_type: str = Field(description="The workbook's media type.")
    size_bytes: int = Field(description="Size of the .xlsx file.")
    sheets: list[str] = Field(
        description="Sheet names in order: the data table, then Chart data and Chart when a "
        "chart fits, then Source (provenance, licence, the call that produced the rows)."
    )
    rows_written: int
    rows_available: int = Field(description="Rows the tool returned before max_rows applied.")
    truncated: bool = Field(description="Whether max_rows cut rows off.")
    chart: str | None = Field(description="The native Excel chart added, if any.")
    saved_path: str | None = Field(
        description="Where a local (stdio) server saved the workbook; null when it is returned "
        "as base64."
    )
    workbook_base64: str | None = Field(
        description="The .xlsx file, base64-encoded: decode and save it under file_name. Null "
        "when the workbook was saved to saved_path."
    )
    notes: list[str]
    provenance: Provenance

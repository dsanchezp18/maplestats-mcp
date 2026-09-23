"""MCP tools for EPCOR Edmonton water quality."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.epcor import client
from maple_data_mcp.modules.epcor.schemas import (
    DailyWaterQuality,
    Plant,
    System,
    WaterQualityReportList,
)

Lang = Literal["en", "fr"]


@tool
async def epcor_get_daily_water_quality(
    plant: Plant = "els", lang: Lang = "en"
) -> DailyWaterQuality:
    """Daily-average treated drinking-water readings for the last 7 days
    from one of Edmonton's two EPCOR water treatment plants: total
    hardness, pH, temperature, total chlorine (chloramine) residual,
    alkalinity, conductivity, and caustic soda dose.

    plant is "els" (E.L. Smith; mainly west, southwest, northwest, and
    the university area) or "rossdale" (mainly downtown, east,
    northeast, southeast). EPCOR marks these as unvalidated monitoring
    values; verified figures are in the monthly reports
    (epcor_list_water_quality_reports).
    Use for: how hard is Edmonton tap water, chlorine levels, recent
    water temperature or pH in Edmonton.
    Keywords: Edmonton, EPCOR, drinking water, water quality, hardness,
    pH, chlorine, chloramine, conductivity, alkalinity, treatment plant,
    Rossdale, E.L. Smith.
    Mots-clés: Edmonton, EPCOR, eau potable, qualité de l'eau, dureté,
    pH, chlore, chloramine, conductivité, alcalinité, usine de
    traitement, Rossdale.
    """
    return await client.get_daily_water_quality(plant, lang=lang)


@tool
async def epcor_list_water_quality_reports(
    year: int | None = None,
    month: int | None = None,
    system: System | None = None,
    kind: str | None = None,
    lang: Lang = "en",
) -> WaterQualityReportList:
    """List EPCOR's published Edmonton water-quality report PDFs (2019
    onward), newest first, with direct download URLs.

    system is "water" (drinking water) or "wastewater". kind is one of
    the normalized report types returned in kinds_available, e.g.
    "monthly-summary", "monthly-bacteriological-summary",
    "monthly-report" (detailed plant operations), "annual-report".
    Returns links only; the contents are PDF documents.
    Use for: finding the verified monthly water quality summary for a
    given month, wastewater effluent reports, annual compliance reports.
    Keywords: Edmonton, EPCOR, water quality report, monthly summary,
    bacteriological, wastewater, Gold Bar, annual report, compliance,
    drinking water, PDF.
    Mots-clés: Edmonton, EPCOR, rapport sur la qualité de l'eau, sommaire
    mensuel, bactériologique, eaux usées, rapport annuel, conformité,
    eau potable.
    """
    return await client.list_water_quality_reports(year, month, system, kind, lang=lang)

"""MCP tools for EPCOR Edmonton water quality."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.epcor import client
from maplestats_mcp.modules.epcor.schemas import DailyWaterQuality, Plant

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
    values; EPCOR's verified figures are in its monthly reports (PDF).
    The newest days can be blank or partly filled (today's row is listed
    before it is published; Rossdale's pH and chlorine lag a few days),
    and provenance.as_of is the newest day with at least one value.
    Use for: how hard is Edmonton tap water, chlorine levels, recent
    water temperature or pH in Edmonton.
    Keywords: Edmonton, EPCOR, drinking water, water quality, hardness,
    pH, chlorine, chloramine, conductivity, alkalinity, treatment plant,
    Rossdale, E.L. Smith.
    Mots-clés : Edmonton, EPCOR, eau potable, eau du robinet, qualité de
    l'eau, dureté de l'eau, pH, chlore résiduel, chloramine, température
    de l'eau, conductivité, alcalinité, soude caustique, usine de
    traitement de l'eau, Rossdale, E.L. Smith.
    """
    return await client.get_daily_water_quality(plant, lang=lang)

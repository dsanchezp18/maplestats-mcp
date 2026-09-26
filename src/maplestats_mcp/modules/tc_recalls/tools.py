"""MCP tools for Transport Canada's vehicle recall API."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.tc_recalls import client, constants
from maplestats_mcp.modules.tc_recalls.schemas import RecallDetail, RecallSearchResult

Lang = Literal["en", "fr"]


@tool
async def tc_recalls_search(
    make: str | None = None,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = constants.LIMIT_DEFAULT,
    page: int = 1,
    lang: Lang = "en",
) -> RecallSearchResult:
    """Search Transport Canada motor vehicle safety recalls by make, model, and model year.

    Use for: checking whether a vehicle has recalls, e.g. make="Honda",
    model="Civic", year_from=2019, year_to=2020. Results are oldest
    first, so give a model-year range or page through with `page`.
    Pass a recall number to tc_recalls_get for details.
    Keywords: vehicle recall, car recall, Transport Canada, safety
    recall, make, model, model year, defect, motor vehicle.
    Mots-clés : rappel de véhicule, rappel automobile, Transports
    Canada, rappel de sécurité, marque, modèle, année-modèle, défaut.
    """
    return await client.search(
        make=make,
        model=model,
        year_from=year_from,
        year_to=year_to,
        limit=limit,
        page=page,
        lang=lang,
    )


@tool
async def tc_recalls_get(recall_number: str, lang: Lang = "en") -> RecallDetail:
    """Get one Transport Canada vehicle recall: its description, units, and vehicles.

    Use for: the details behind a recall number from tc_recalls_search
    (e.g. "2021001"), including the affected makes, models and years.
    `description` is Transport Canada's single text covering the issue,
    the safety risk and the corrective action.
    `lang="fr"` returns the French category, system and description.
    Keywords: recall details, safety risk, corrective action, units
    affected, Transport Canada, vehicle defect, notification, recall.
    Mots-clés : détails du rappel, risque pour la sécurité, mesure
    corrective, unités touchées, Transports Canada, défaut du véhicule,
    rappel, véhicule.
    """
    return await client.get_recall(recall_number, lang)

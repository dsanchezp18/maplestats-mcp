"""MCP tools for Edmonton Police Service Community Safety Data Portal occurrences."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.eps import client
from maplestats_mcp.modules.eps.schemas import (
    Dataset,
    GroupBy,
    LoadDate,
    OccurrenceList,
    OccurrenceSummary,
)

Lang = Literal["en", "fr"]


@tool
async def eps_list_occurrences(
    dataset: Dataset = "current",
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
    limit: int = 50,
    offset: int = 0,
    lang: Lang = "en",
) -> OccurrenceList:
    """List individual Edmonton Police Service reported occurrences, newest
    first: reported date, category, group, type, nearest intersection,
    and WGS84 longitude/latitude.

    dataset is "current" (rolling ~12 months) or "2023" (calendar 2023
    only; nothing public covers 2024 to mid-September 2025). category
    (e.g. "Violent", "Non-Violent", "Disorder", "Drugs", "Weapons",
    "Traffic"), group, and type_group match exact upstream labels -- run
    eps_summarize_occurrences first to see them. start_date/end_date are
    inclusive YYYY-MM-DD. intersection_contains is a case-insensitive
    substring (e.g. "JASPER AV"). limit is 1-2000; page with offset.
    Use for: crime incidents near a street, recent assaults or break-ins
    in Edmonton, building a crime map.
    Keywords: Edmonton, police, EPS, crime, occurrences, incidents,
    assault, theft, break and enter, property crime, community safety,
    crime map, intersection.
    Mots-clés : Edmonton, police, SPE, criminalité, incidents,
    infractions, voies de fait, vol, introduction par effraction,
    sécurité communautaire, carte de la criminalité, intersection.
    """
    return await client.list_occurrences(
        dataset,
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
        limit=limit,
        offset=offset,
        lang=lang,
    )


@tool
async def eps_summarize_occurrences(
    dataset: Dataset = "current",
    group_by: GroupBy = "category",
    category: str | None = None,
    group: str | None = None,
    type_group: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    intersection_contains: str | None = None,
    top: int = 100,
    lang: Lang = "en",
) -> OccurrenceSummary:
    """Count Edmonton Police Service reported occurrences grouped by
    "category", "group", "type", "month", or "intersection", with the
    same filters as eps_list_occurrences. Counts are computed by the
    server over every matching row, not a sample.

    Months come back in date order; other groupings largest first, up
    to top groups (1-2000). Also the way to discover the exact category/
    group/type labels to filter on (upstream has near-duplicates such as
    "Drug Violation" vs "Drug Violations").
    Use for: crime trends by month, most common offence types, crime
    hotspots by intersection, Edmonton crime statistics.
    Keywords: Edmonton, police, EPS, crime statistics, crime trends,
    monthly crime, offence types, hotspots, counts, community safety,
    violent crime, property crime.
    Mots-clés : Edmonton, police, SPE, statistiques de criminalité,
    tendances, criminalité mensuelle, types d'infractions, points chauds,
    dénombrement, sécurité communautaire, crimes violents, crimes contre
    les biens.
    """
    return await client.summarize_occurrences(
        dataset,
        group_by,
        category=category,
        group=group,
        type_group=type_group,
        start_date=start_date,
        end_date=end_date,
        intersection_contains=intersection_contains,
        top=top,
        lang=lang,
    )


@tool
async def eps_get_last_load_date(lang: Lang = "en") -> LoadDate:
    """Return the date the Edmonton Police Service last refreshed its
    Community Safety Data Portal occurrence data (EPS's own load record).

    Use for: checking how current EPS crime data is before analysing it.
    Keywords: Edmonton, police, EPS, data freshness, last updated,
    refresh date, community safety, crime data, load date.
    Mots-clés : Edmonton, police, SPE, fraîcheur des données, dernière
    mise à jour, date d'actualisation, sécurité communautaire, données
    sur la criminalité.
    """
    return await client.get_last_load_date(lang=lang)

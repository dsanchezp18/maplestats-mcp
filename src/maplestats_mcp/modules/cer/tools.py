"""MCP tools for Canada Energy Regulator open data."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.cer import client, constants
from maplestats_mcp.modules.cer.schemas import CerDatasetList, CerRows

Lang = Literal["en", "fr"]


@tool
async def cer_list_datasets(query: str = "", limit: int = 10, lang: Lang = "en") -> CerDatasetList:
    """Find Canada Energy Regulator datasets and their CSV file URLs.

    Use for: locating CER data such as "throughput" (pipeline throughput
    and capacity per pipeline and key point), "exports" (crude oil,
    natural gas, NGL, LNG, refined products), "tolls", "incident",
    "refinery", or "energy future" (Canada's Energy Future scenarios).
    `lang="fr"` returns the French files and titles.
    Keywords: CER, Canada Energy Regulator, NEB, pipeline, throughput,
    capacity, oil exports, natural gas exports, LNG, tolls, incidents.
    Mots-clés : Régie de l'énergie du Canada (REC), Office national de
    l'énergie (ONE), pipelines, débit des pipelines, capacité,
    exportations de pétrole brut, exportations de gaz naturel, GNL,
    droits pipeliniers, incidents, raffineries, Avenir énergétique du
    Canada.
    """
    return await client.list_datasets(query, limit=limit, lang=lang)


@tool
async def cer_query_file(
    url: str,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> CerRows:
    """Read rows from one Canada Energy Regulator CSV file with filters and a date range.

    Use for: pipeline throughput vs capacity over time (e.g. filters
    {"Key Point": "International boundary at or near Haskett, Manitoba"}),
    export volumes by year, or tolls by pipeline. `url` comes from
    cer_list_datasets; `filters` match column values exactly
    (case-insensitive); `start`/`end` are YYYY, YYYY-MM or YYYY-MM-DD on
    the file's Date/Year column, both inclusive (end="2024" runs to
    December 31); the most recent `limit` rows come back.
    The file's own language decides the column names.
    Keywords: CER, pipeline throughput, capacity utilization, exports,
    volumes, tolls, time series, CSV, oil, natural gas.
    Mots-clés : Régie de l'énergie du Canada (REC), débit des pipelines,
    taux d'utilisation, capacité disponible, exportations, volumes,
    droits pipeliniers, séries chronologiques, pétrole brut, gaz naturel.
    """
    return await client.query_file(
        url, filters, columns=columns, start=start, end=end, limit=limit, lang=lang
    )

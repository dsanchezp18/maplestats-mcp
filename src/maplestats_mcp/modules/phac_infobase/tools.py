"""MCP tools for PHAC Health Infobase data files."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.phac_infobase import client, constants
from maplestats_mcp.modules.phac_infobase.schemas import (
    DatasetDescription,
    DatasetList,
    QueryResult,
)

Lang = Literal["en", "fr"]


@tool
async def phac_infobase_list_datasets(
    topic: str | None = None, query: str | None = None, lang: Lang = "en"
) -> DatasetList:
    """List PHAC Health Infobase surveillance datasets (dashboard data files), by topic.

    Use for: finding public health surveillance data from the Public
    Health Agency of Canada's Health Infobase dashboards: respiratory
    virus detections and FluWatch+ (influenza, COVID-19, RSV), wastewater
    viral load, opioid and stimulant deaths and hospitalizations,
    supervised consumption sites, substance use surveys, measles, mpox,
    tuberculosis, notifiable diseases, vaccine adverse events, chronic
    disease and cancer indicators, archived COVID-19 cases and vaccination.
    `topic` is one of respiratory, covid19, wastewater, vaccination,
    substance_use, infectious_disease, chronic_disease, health_status;
    `query` matches words in English or French titles. Returns dataset
    ids for phac_infobase_describe_dataset and phac_infobase_query. The
    Chronic Disease Surveillance System (CCDSS) data tool has no
    downloadable file.
    Keywords: PHAC, Health Infobase, public health surveillance, FluWatch,
    influenza, COVID-19, RSV, opioid overdose, wastewater, measles,
    tuberculosis, notifiable diseases.
    Mots-clés : ASPC, Santé Infobase, surveillance de la santé publique,
    ÉpiGrippe, grippe, COVID-19, VRS, surdoses d'opioïdes, eaux usées,
    rougeole, tuberculose, maladies à déclaration obligatoire.
    """
    return client.list_datasets(topic, query, lang)


@tool
async def phac_infobase_describe_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDescription:
    """Describe a PHAC Health Infobase dataset: columns, values, date coverage, last update.

    Use for: before querying, learning a surveillance file's columns and
    their most common values (for exact filters), its date range, the
    provinces or places it covers, when PHAC last updated it, and which
    suppression markers it uses ("Suppr.", "X", "n/a"). `dataset_id`
    comes from phac_infobase_list_datasets; `lang="fr"` reads the French
    file when PHAC publishes one (French column names and labels).
    Keywords: PHAC, Health Infobase, data dictionary, columns, coverage,
    last updated, surveillance data, suppressed values, metadata.
    Mots-clés : ASPC, Santé Infobase, dictionnaire de données, colonnes,
    période couverte, dernière mise à jour, données de surveillance,
    valeurs supprimées, métadonnées.
    """
    return await client.describe_dataset(dataset_id, lang)


@tool
async def phac_infobase_query(
    dataset_id: str,
    filters: dict[str, str] | None = None,
    geography: str | None = None,
    start: str | None = None,
    end: str | None = None,
    columns: list[str] | None = None,
    limit: int = constants.ROWS_DEFAULT,
    lang: Lang = "en",
) -> QueryResult:
    """Query rows of a PHAC Health Infobase dataset by column values, date range and province.

    Use for: weekly influenza, COVID-19 and RSV percent positive by
    province, apparent opioid toxicity deaths by province and year,
    wastewater viral load for a city, measles cases by province,
    tuberculosis incidence, and similar surveillance series. `filters`
    are exact, case-insensitive column matches, e.g. for
    opioid_stimulant_harms {"Source": "Deaths", "Specific_Measure":
    "Overall numbers", "Unit": "Number", "Time_Period": "By year"};
    `geography` accepts a province or territory name (English or
    French), abbreviation (ON, QC) or PRUID code; `start`/`end` are
    YYYY, YYYY-MM, YYYY-MM-DD or YYYY Qn on the dataset's date column.
    The most recent `limit` matching rows come back, oldest first.
    Values are returned as published; suppression markers are listed.
    Keywords: PHAC, Health Infobase, surveillance time series, weekly
    cases, percent positivity, overdose deaths, province, wastewater,
    rates per 100,000.
    Mots-clés : ASPC, Santé Infobase, séries chronologiques de
    surveillance, cas hebdomadaires, pourcentage de positivité, décès par
    surdose, province, eaux usées, taux pour 100 000.
    """
    return await client.query(
        dataset_id,
        filters=filters,
        geography=geography,
        start=start,
        end=end,
        columns=columns,
        limit=limit,
        lang=lang,
    )

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
    `query` matches words in English or French titles, ignoring case and
    accents. `lang="fr"` returns French titles and descriptions for every
    dataset; `languages` shows which ones also have a French data file
    (9 of them), the others are read from the English file. Returns
    dataset ids for phac_infobase_describe_dataset and
    phac_infobase_query. The Chronic Disease Surveillance System (CCDSS)
    data tool has no downloadable file.
    Keywords: PHAC, Health Infobase, public health surveillance, FluWatch,
    influenza, COVID-19, RSV, opioid overdose, wastewater, measles,
    tuberculosis, notifiable diseases.
    Mots-clés : ASPC, Agence de la santé publique du Canada, Infobase
    santé, surveillance de la santé publique,
    ÉpiGrippe, grippe, influenza, COVID-19, VRS, virus respiratoires,
    surdoses d'opioïdes, eaux usées, rougeole, tuberculose, maladies à
    déclaration obligatoire, vaccination.
    """
    return client.list_datasets(topic, query, lang)


@tool
async def phac_infobase_describe_dataset(dataset_id: str, lang: Lang = "en") -> DatasetDescription:
    """Describe a PHAC Health Infobase dataset: columns, values, date coverage, last update.

    Use for: before querying, learning a surveillance file's columns and
    their most common values (for exact filters), its date range, the
    provinces or places it covers, when PHAC last updated it, and which
    suppression markers it uses ("Suppr.", "X", "n/a"; "Mas." and "n.d."
    in French files). `dataset_id` comes from phac_infobase_list_datasets;
    `lang="fr"` reads the French file when PHAC publishes one (French
    column names and labels, sometimes decimal commas) and otherwise the
    English file; `file_language` says which.
    Keywords: PHAC, Health Infobase, data dictionary, columns, coverage,
    last updated, surveillance data, suppressed values, metadata.
    Mots-clés : ASPC, Infobase santé, dictionnaire de données, colonnes,
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
    French), abbreviation (ON, QC) or PRUID code, or part of a place
    name (wastewater sites); one that matches nothing is an error listing
    the places the dataset has. `start`/`end` are
    YYYY, YYYY-MM, YYYY-MM-DD or YYYY Qn (or Tn) on the dataset's date
    column.
    The most recent `limit` matching rows come back, oldest first.
    Values are returned as published; suppression markers are listed.
    `lang="fr"` reads the French file where one exists, whose column
    names and values are French (e.g. {"Source": "Mortalité", "Unité":
    "Nombre", "Période_Temps": "Par année"}; quarters "2025 T3"), so take
    filter names and values from phac_infobase_describe_dataset called
    with the same `lang`. Filters also ignore accents and apostrophe style.
    Keywords: PHAC, Health Infobase, surveillance time series, weekly
    cases, percent positivity, overdose deaths, province, wastewater,
    rates per 100,000.
    Mots-clés : ASPC, Infobase santé, séries chronologiques de
    surveillance, cas hebdomadaires, pourcentage de positivité, taux de
    positivité, décès par surdose, province, eaux usées, taux pour
    100 000.
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

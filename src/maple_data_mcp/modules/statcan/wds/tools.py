"""MCP tools for the StatCan Web Data Service (WDS).

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maple_data_mcp.modules.statcan.wds import client
from maple_data_mcp.modules.statcan.wds.schemas import (
    ChangedCubeList,
    ChangedSeriesList,
    CodeSets,
    CubeMetadata,
    CubeSummaryList,
    FullTableDownloadLink,
    SeriesInfo,
    VectorData,
)

Lang = Literal["en", "fr"]


@tool
async def wds_search_cubes(query: str, limit: int = 25, lang: Lang = "en") -> CubeSummaryList:
    """Search Statistics Canada's ~8,000 data tables (cubes) by title keyword.

    Use for: finding a StatCan table's productId when you only know a
    topic, discovering which tables cover a subject before requesting
    metadata or data.
    Keywords: statcan, statistics canada, table, cube, search, productId,
    discover, wds, catalogue, browse.
    Mots-clés: statcan, statistique canada, tableau, cube, recherche,
    productId, découverte, wds, catalogue, parcourir.
    """
    return await client.search_cubes(query, limit=limit)


@tool
async def wds_list_all_cubes(lite: bool = True, lang: Lang = "en") -> CubeSummaryList:
    """List every StatCan data table (cube) currently available via WDS.

    Use for: a full inventory scan, building a local index, checking
    total table count. Prefer wds_search_cubes for a topic search.
    Keywords: statcan, list, inventory, all cubes, catalogue, wds,
    productId, full list, tables.
    Mots-clés: statcan, liste, inventaire, tous les cubes, catalogue,
    wds, productId, liste complète, tableaux.
    """
    return await client.get_all_cubes_list(lite=lite)


@tool
async def wds_get_cube_metadata(product_id: int, lang: Lang = "en") -> CubeMetadata:
    """Get full metadata for one StatCan table: dimensions, member trees,
    frequency, date range, and footnotes.

    Use for: understanding a table's structure before requesting data,
    finding the coordinate/member IDs needed for a data query.
    Keywords: statcan, metadata, dimensions, members, productId, cube,
    structure, footnotes, wds.
    Mots-clés: statcan, métadonnées, dimensions, membres, productId,
    cube, structure, notes de bas de page, wds.
    """
    return await client.get_cube_metadata(product_id)


@tool
async def wds_get_series_info_from_vector(vector_id: int, lang: Lang = "en") -> SeriesInfo:
    """Resolve a StatCan vector ID to its productId and coordinate.

    Use for: figuring out which table and dimension-position a known
    vector belongs to.
    Keywords: statcan, vector, resolve, productId, coordinate, series
    info, wds.
    Mots-clés: statcan, vecteur, résoudre, conversion, productId,
    coordonnée, information de série, identifiant, wds.
    """
    return await client.get_series_info_from_vector(vector_id)


@tool
async def wds_get_series_info_from_cube_pid_coord(
    product_id: int, coordinate: str, lang: Lang = "en"
) -> SeriesInfo:
    """Resolve a productId + coordinate to its stable vector ID.

    Use for: converting a table/dimension-position pair (from
    wds_get_cube_metadata) into a vector ID for later reuse.
    Keywords: statcan, coordinate, vector, resolve, productId, series
    info, wds.
    Mots-clés: statcan, coordonnée, vecteur, résoudre, conversion,
    productId, information de série, identifiant, wds.
    """
    return await client.get_series_info_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_data_from_vectors(
    vector_ids: list[int], latest_n: int = 12, lang: Lang = "en"
) -> list[VectorData]:
    """Get the latest N observations for one or more StatCan vectors.

    Use for: fetching recent values of one or more known time series.
    Note: scalarFactorCode in each observation is NOT pre-applied to
    value — see statcan.wds.apply_scalar_factor if a scaled figure is
    needed.
    Keywords: statcan, vector, observations, latest, data, time series,
    wds, values.
    Mots-clés: statcan, vecteur, observations, dernières données,
    données, série chronologique, wds, valeurs.
    """
    return await client.get_data_from_vectors_and_latest_n_periods(vector_ids, latest_n)


@tool
async def wds_get_data_from_cube_coord(
    product_id: int, coordinate: str, latest_n: int = 12, lang: Lang = "en"
) -> VectorData:
    """Get the latest N observations for a table + coordinate pair.

    Use for: fetching data when you have a productId/coordinate but not
    yet the vector ID.
    Keywords: statcan, coordinate, observations, latest, data, wds,
    productId.
    Mots-clés: statcan, coordonnée, observations, dernières données,
    données, wds, productId, tableau.
    """
    return await client.get_data_from_cube_pid_coord_and_latest_n_periods(
        product_id, coordinate, latest_n
    )


@tool
async def wds_get_bulk_vector_data_by_range(
    vector_ids: list[int],
    start_release_datetime: str,
    end_release_datetime: str,
    lang: Lang = "en",
) -> list[VectorData]:
    """Get observations for multiple vectors released within a date range.

    Use for: bulk historical retrieval across several series at once,
    filtered by release date (not reference period).
    `start_release_datetime`/`end_release_datetime` must be full
    "YYYY-MM-DDTHH:MM" (e.g. "2024-01-01T08:30") — WDS rejects a bare
    date with HTTP 406.
    Keywords: statcan, bulk, vectors, date range, release date, history,
    wds.
    Mots-clés: statcan, en masse, vecteurs, vecteurs multiples, plage de
    dates, date de diffusion, historique, wds.
    """
    return await client.get_bulk_vector_data_by_range(
        vector_ids, start_release_datetime, end_release_datetime
    )


@tool
async def wds_get_data_by_reference_period_range(
    vector_ids: list[int], start_ref_period: str, end_ref_period: str, lang: Lang = "en"
) -> list[VectorData]:
    """Get observations for vectors within a reference-period range.

    Use for: retrieving a specific historical window (e.g. 2015-01-01 to
    2020-12-01) rather than "latest N." `start_ref_period`/`end_ref_period`
    must be full "YYYY-MM-DD" — WDS rejects an abbreviated "YYYY-MM"
    with HTTP 406.
    Keywords: statcan, reference period, range, history, vectors, wds,
    date range.
    Mots-clés: statcan, période de référence, plage, plage de dates,
    historique, vecteurs, données historiques, wds.
    """
    return await client.get_data_from_vector_by_reference_period_range(
        vector_ids, start_ref_period, end_ref_period
    )


@tool
async def wds_get_changed_series_list(lang: Lang = "en") -> ChangedSeriesList:
    """List StatCan series that changed (new release) today.

    Use for: detecting updated series for a scheduled refresh. WDS
    documents this method as always reflecting today's changes — it
    does not accept a date parameter (unlike wds_get_changed_cube_list).
    Keywords: statcan, changed, updated, series, release, today, wds,
    refresh.
    Mots-clés: statcan, modifié, mis à jour, série, diffusion,
    aujourd'hui, wds, actualisation.
    """
    return await client.get_changed_series_list()


@tool
async def wds_get_changed_cube_list(date: str | None = None, lang: Lang = "en") -> ChangedCubeList:
    """List StatCan tables (cubes) that changed on a given date.

    Use for: detecting which tables were updated, e.g. after the daily
    8:30am ET release.
    Keywords: statcan, changed, updated, cube, table, release, today,
    wds.
    Mots-clés: statcan, modifié, mis à jour, cube, tableau, diffusion,
    aujourd'hui, wds.
    """
    return await client.get_changed_cube_list(date)


@tool
async def wds_get_changed_series_data_from_vector(vector_id: int, lang: Lang = "en") -> VectorData:
    """Get just the newly-changed data points for a vector.

    Use for: fetching only what changed rather than the full latest-N
    window, after wds_get_changed_series_list flags a vector.
    Keywords: statcan, changed, vector, delta, updated data, wds.
    Mots-clés: statcan, modifié, vecteur, écart, données mises à jour,
    série, changements, wds.
    """
    return await client.get_changed_series_data_from_vector(vector_id)


@tool
async def wds_get_changed_series_data_from_cube_coord(
    product_id: int, coordinate: str, lang: Lang = "en"
) -> VectorData:
    """Get just the newly-changed data points for a table + coordinate.

    Use for: fetching only what changed for a specific series identified
    by productId/coordinate rather than vector ID.
    Keywords: statcan, changed, coordinate, delta, updated data, wds.
    Mots-clés: statcan, modifié, coordonnée, écart, données mises à
    jour, changements, tableau, wds.
    """
    return await client.get_changed_series_data_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_full_table_download_csv(
    product_id: int, lang: Lang = "en"
) -> FullTableDownloadLink:
    """Get the download URL for a full StatCan table as CSV.

    Use for: bulk/offline analysis of an entire table rather than
    individual series — hands back a URL, does not fetch the file.
    Keywords: statcan, csv, download, full table, bulk, export, wds.
    Mots-clés: statcan, csv, téléchargement, tableau complet, en masse,
    exportation, wds, données complètes.
    """
    return await client.get_full_table_download_csv(product_id, lang)


@tool
async def wds_get_full_table_download_sdmx(
    product_id: int, lang: Lang = "en"
) -> FullTableDownloadLink:
    """Get the download URL for a full StatCan table as SDMX/XML.

    Use for: bulk retrieval in SDMX format rather than CSV — hands back
    a URL, does not fetch the file.
    Keywords: statcan, sdmx, xml, download, full table, bulk, export,
    wds.
    Mots-clés: statcan, sdmx, xml, téléchargement, tableau complet, en
    masse, exportation, wds.
    """
    return await client.get_full_table_download_sdmx(product_id)


@tool
async def wds_get_code_sets(lang: Lang = "en") -> CodeSets:
    """Get StatCan's code-set descriptions: scalar factors, frequency,
    symbol, status, unit of measure, survey, subject, classification
    type, security level, and terminated codes.

    Use for: decoding any numeric code returned by another WDS tool,
    e.g. applying a scalarFactorCode multiplier to a raw value.
    Keywords: statcan, code sets, decode, scalar factor, frequency,
    symbol, status, uom, wds, lookup.
    Mots-clés: statcan, ensembles de codes, décoder, facteur d'échelle,
    fréquence, symbole, statut, unité de mesure, wds, référence.
    """
    return await client.get_code_sets()

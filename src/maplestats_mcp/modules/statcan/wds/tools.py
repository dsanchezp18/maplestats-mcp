"""MCP tools for the StatCan Web Data Service (WDS).

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.modules.statcan.wds.schemas import (
    ChangedCubeList,
    ChangedSeriesList,
    CodeSets,
    CubeMetadata,
    CubeSummaryList,
    FullTableDownloadLink,
    SeriesInfo,
    VectorData,
)
from maplestats_mcp.shared.envelope import raise_error
from maplestats_mcp.shared.errors import InvalidInput

Lang = Literal["en", "fr"]


@tool
async def wds_search_cubes(
    query: str | None = None,
    limit: int | None = None,
    lite: bool = True,
    lang: Lang = "en",
) -> CubeSummaryList:
    """Search Statistics Canada's ~8,000 data tables (cubes) by title
    keyword, or list every table when `query` is omitted.

    Use for: finding a StatCan table's productId when you only know a
    topic (find a table on GDP by industry), discovering which tables cover a subject before requesting
    metadata or data; with no `query`, a full inventory scan, building a
    local index, or checking the total table count.
    With `query`: case-insensitive title match, `limit` defaults to 25.
    Without `query`: the full list (`lite=False` for the non-lite
    inventory); `limit` optionally truncates it. `lite=False` is only
    valid without `query`. Revision history: 19 statistics also have a
    real-time (vintage) table; statcan_delta_list_real_time_tables pairs
    each with its regular table.
    Keywords: statcan, statistics canada, table, cube, search, productId,
    discover, wds, catalogue, browse, list, inventory, all cubes, full
    list, tables, labour force, unemployment rate, employment, GDP by
    industry, CPI, population estimates, retail trade, wages, trade,
    interprovincial migration, time series.
    Mots-clés : statcan, statistique canada, tableau, cube, recherche,
    productId, découverte, wds, catalogue, parcourir, liste, inventaire,
    tous les cubes, liste complète, tableaux, population active, taux de
    chômage, emploi, PIB par industrie, IPC, estimations de population,
    commerce de détail, salaires, commerce, migration interprovinciale,
    séries chronologiques.
    """
    if query is not None:
        if not lite:
            raise_error(
                InvalidInput,
                "error.invalid_input",
                lang,
                detail="wds_search_cubes: lite=False is only valid when query is omitted.",
            )
        return await client.search_cubes(query, limit=25 if limit is None else limit)
    result = await client.get_all_cubes_list(lite=lite)
    if limit is not None:
        cubes = result.cubes[:limit]
        return result.model_copy(update={"cubes": cubes, "total_count": len(cubes)})
    return result


@tool
async def wds_get_cube_metadata(product_id: int, lang: Lang = "en") -> CubeMetadata:
    """Get full metadata for one StatCan table: dimensions, member trees,
    frequency, date range, and footnotes.

    Use for: understanding a table's structure before requesting data,
    finding the coordinate/member IDs needed for a data query.
    Keywords: statcan, metadata, dimensions, members, productId, cube,
    structure, footnotes, wds.
    Mots-clés : statcan, métadonnées, dimensions, membres, productId,
    cube, structure, notes de bas de page, wds.
    """
    return await client.get_cube_metadata(product_id)


def _vector_or_coord(
    tool_name: str,
    vector_id: int | None,
    product_id: int | None,
    coordinate: str | None,
    lang: str,
) -> None:
    """Require exactly one of `vector_id` or (`product_id` + `coordinate`)."""
    has_vector = vector_id is not None
    has_coord = product_id is not None or coordinate is not None
    if has_vector == has_coord or (has_coord and (product_id is None or coordinate is None)):
        raise_error(
            InvalidInput,
            "error.invalid_input",
            lang,
            detail=(
                f"{tool_name}: pass exactly one of vector_id, or product_id together "
                "with coordinate."
            ),
        )


@tool
async def wds_get_series_info(
    vector_id: int | None = None,
    product_id: int | None = None,
    coordinate: str | None = None,
    lang: Lang = "en",
) -> SeriesInfo:
    """Resolve a StatCan series either way: a vector ID to its productId
    and coordinate, or a productId + coordinate to its stable vector ID.

    Use for: figuring out which table and dimension-position a known
    vector belongs to, or converting a table/dimension-position pair
    (from wds_get_cube_metadata) into a vector ID for later reuse. Pass
    exactly one form: `vector_id`, or `product_id` + `coordinate`.
    Keywords: statcan, vector, coordinate, resolve, productId, series
    info, wds, Statistics Canada, conversion, identifier.
    Mots-clés : statcan, vecteur, coordonnée, résoudre, conversion,
    productId, information de série, identifiant, wds.
    """
    _vector_or_coord("wds_get_series_info", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        return await client.get_series_info_from_vector(vector_id)
    assert product_id is not None and coordinate is not None
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
    Mots-clés : statcan, vecteur, observations, dernières données,
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
    productId, Statistics Canada.
    Mots-clés : statcan, coordonnée, observations, dernières données,
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
    wds, Statistics Canada.
    Mots-clés : statcan, en masse, vecteurs, vecteurs multiples, plage de
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
    Keywords: statcan, reference period, range, history, vectors, wds, date
    range, Statistics Canada.
    Mots-clés : statcan, période de référence, plage, plage de dates,
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
    Mots-clés : statcan, modifié, mis à jour, série, diffusion,
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
    Mots-clés : statcan, modifié, mis à jour, cube, tableau, diffusion,
    aujourd'hui, wds.
    """
    return await client.get_changed_cube_list(date)


@tool
async def wds_get_changed_series_data(
    vector_id: int | None = None,
    product_id: int | None = None,
    coordinate: str | None = None,
    lang: Lang = "en",
) -> VectorData:
    """Get just the newly-changed data points for one series, identified
    by vector ID or by table + coordinate.

    Use for: fetching only what changed rather than the full latest-N
    window, after wds_get_changed_series_list flags a vector. Pass
    exactly one form: `vector_id`, or `product_id` + `coordinate`.
    Keywords: statcan, changed, vector, coordinate, delta, updated data,
    wds, Statistics Canada, revisions.
    Mots-clés : statcan, modifié, vecteur, coordonnée, écart, données
    mises à jour, série, changements, tableau, wds.
    """
    _vector_or_coord("wds_get_changed_series_data", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        return await client.get_changed_series_data_from_vector(vector_id)
    assert product_id is not None and coordinate is not None
    return await client.get_changed_series_data_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_full_table_download(
    product_id: int,
    format: Literal["csv", "sdmx"] = "csv",
    lang: Lang = "en",
) -> FullTableDownloadLink:
    """Get the download URL for a full StatCan table as CSV (default) or
    SDMX/XML (`format="sdmx"`).

    Use for: bulk/offline analysis of an entire table rather than
    individual series, in CSV or SDMX format — hands back a URL, does
    not fetch the file. `lang` picks the CSV language edition.
    Keywords: statcan, csv, sdmx, xml, download, full table, bulk,
    export, wds, Statistics Canada.
    Mots-clés : statcan, csv, sdmx, xml, téléchargement, tableau complet,
    en masse, exportation, wds, données complètes.
    """
    if format == "sdmx":
        return await client.get_full_table_download_sdmx(product_id)
    return await client.get_full_table_download_csv(product_id, lang)


@tool
async def wds_get_code_sets(lang: Lang = "en") -> CodeSets:
    """Get StatCan's code-set descriptions: scalar factors, frequency,
    symbol, status, unit of measure, survey, subject, classification
    type, security level, and terminated codes.

    Use for: decoding any numeric code returned by another WDS tool,
    e.g. applying a scalarFactorCode multiplier to a raw value.
    Keywords: statcan, code sets, decode, scalar factor, frequency,
    symbol, status, uom, wds, lookup.
    Mots-clés : statcan, ensembles de codes, décoder, facteur d'échelle,
    fréquence, symbole, statut, unité de mesure, wds, référence.
    """
    return await client.get_code_sets()

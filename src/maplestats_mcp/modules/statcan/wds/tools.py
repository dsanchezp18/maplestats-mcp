"""MCP tools for the StatCan Web Data Service (WDS).

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.
"""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.wds import client, constants
from maplestats_mcp.modules.statcan.wds.client import CodeSetCategory
from maplestats_mcp.modules.statcan.wds.schemas import (
    ChangedCubeList,
    ChangedSeriesList,
    CodeSets,
    CubeMetadata,
    CubeSummaryList,
    FullTableDownloadLink,
    SeriesInfo,
    VectorData,
    VectorDataSet,
)
from maplestats_mcp.shared.envelope import raise_error
from maplestats_mcp.shared.errors import InvalidInput

Lang = Literal["en", "fr"]
# An 8-digit productId, or the table number as StatCan prints it.
ProductId = int | str


@tool
async def wds_search_cubes(
    query: str | None = None,
    limit: int = constants.SEARCH_LIMIT_DEFAULT,
    offset: int = 0,
    lite: bool = True,
    lang: Lang = "en",
) -> CubeSummaryList:
    """Search Statistics Canada's ~8,000 data tables (cubes) by title
    keyword or table number, or list every table when `query` is omitted.

    Use for: finding a StatCan table's productId when you only know a
    topic (GDP by industry, CPI) or a number such as "18-10-0004",
    discovering which StatCan tables cover a subject before requesting
    metadata or data. Every word must
    be in a title, else the best partial matches come back. `limit`
    (default 25, max 500) and `offset` page the tables; total_count is
    the number matching. `real_time` marks real-time (revision-history)
    tables.
    Keywords: statcan, statistics canada, table, cube, search, productId,
    discover, wds, catalogue, browse, list, inventory, all cubes, full
    list, tables, labour force, monthly unemployment rate, employment,
    GDP by industry, CPI, consumer price index, population estimates
    quarterly, retail trade, wages, trade, interprovincial migration,
    time series, real-time table.
    Mots-clés : statcan, statistique canada, tableau, cube, recherche,
    productId, numéro de tableau, découverte, wds, catalogue, parcourir,
    liste, inventaire, population active, taux de chômage mensuel,
    emploi, PIB par industrie, IPC, indice des prix à la consommation,
    estimations de population trimestrielles, commerce de détail,
    salaires, commerce, migration interprovinciale, séries
    chronologiques, tableau en temps réel, révisions.
    """
    client.use_lang(lang)
    if query is not None and query.strip() and not lite:
        raise_error(
            InvalidInput,
            "error.invalid_input",
            lang,
            detail="wds_search_cubes: lite=False is only valid when query is omitted.",
        )
    return await client.search_cubes(query, limit=limit, offset=offset, lite=lite)


@tool
async def wds_get_cube_metadata(
    product_id: ProductId,
    dimension: int | None = None,
    member_query: str | None = None,
    member_limit: int = constants.MEMBER_LIMIT_DEFAULT,
    member_offset: int = 0,
    footnote_limit: int = constants.FOOTNOTE_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> CubeMetadata:
    """Get metadata for one StatCan table: dimensions, member trees,
    frequency, date range, and footnotes.

    Use for: understanding a table's structure before requesting data,
    finding the member IDs that make up a coordinate. `product_id` is
    the 8-digit productId or the table number (18-10-0004,
    18-10-0004-01). Large tables have thousands of members, so each
    dimension returns at most `member_limit` members (default 100) and
    footnotes are capped at `footnote_limit`; provenance.limits says what
    was cut. Narrow with `dimension` (a position, e.g. 1 for geography),
    `member_query` (words in a member name) and `member_offset`.
    Keywords: statcan, metadata, dimensions, members, productId, cube,
    structure, footnotes, wds, coordinate, table number.
    Mots-clés : statcan, métadonnées, dimensions, membres, productId,
    cube, structure, notes de bas de page, wds, coordonnée, numéro de
    tableau.
    """
    client.use_lang(lang)
    return await client.get_cube_metadata(
        product_id,
        dimension=dimension,
        member_query=member_query,
        member_limit=member_limit,
        member_offset=member_offset,
        footnote_limit=footnote_limit,
    )


def _vector_or_coord(
    tool_name: str,
    vector_id: int | None,
    product_id: ProductId | None,
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
    product_id: ProductId | None = None,
    coordinate: str | None = None,
    lang: Lang = "en",
) -> SeriesInfo:
    """Resolve a StatCan series either way: a vector ID to its productId
    and coordinate, or a productId + coordinate to its stable vector ID.

    Use for: figuring out which table and dimension-position a known
    vector belongs to, or converting a table/dimension-position pair
    (from wds_get_cube_metadata) into a vector ID for later reuse. Pass
    exactly one form: `vector_id`, or `product_id` + `coordinate`. Also
    returns the series title, frequency, decimals, scalar factor and
    unit-of-measure codes.
    Keywords: statcan, vector, coordinate, resolve, productId, series
    info, wds, Statistics Canada, conversion, identifier.
    Mots-clés : statcan, vecteur, coordonnée, résoudre, conversion,
    productId, information de série, identifiant, wds.
    """
    client.use_lang(lang)
    _vector_or_coord("wds_get_series_info", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        return await client.get_series_info_from_vector(vector_id)
    assert product_id is not None and coordinate is not None
    return await client.get_series_info_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_data_from_vectors(
    vector_ids: list[int], latest_n: int = 12, lang: Lang = "en"
) -> VectorDataSet:
    """Get the latest N observations for one or more StatCan vectors.

    Use for: fetching recent values of one or more known time series.
    Vectors WDS cannot serve are listed in `failed`; the others still
    come back. Note: scalarFactorCode in each observation is NOT
    pre-applied to value: multiply `value` by the observation's
    `scale_multiplier` if a scaled figure is needed.
    Keywords: statcan, vector, observations, latest, data, time series,
    wds, values.
    Mots-clés : statcan, vecteur, observations, dernières données,
    données, série chronologique, wds, valeurs.
    """
    client.use_lang(lang)
    return await client.get_data_from_vectors_and_latest_n_periods(vector_ids, latest_n)


@tool
async def wds_get_data_from_cube_coord(
    product_id: ProductId, coordinate: str, latest_n: int = 12, lang: Lang = "en"
) -> VectorData:
    """Get the latest N observations for a table + coordinate pair.

    Use for: fetching data when you have a productId/coordinate but not
    yet the vector ID.
    Keywords: statcan, coordinate, observations, latest, data, wds,
    productId, Statistics Canada.
    Mots-clés : statcan, coordonnée, observations, dernières données,
    données, wds, productId, tableau.
    """
    client.use_lang(lang)
    return await client.get_data_from_cube_pid_coord_and_latest_n_periods(
        product_id, coordinate, latest_n
    )


@tool
async def wds_get_bulk_vector_data_by_range(
    vector_ids: list[int],
    start_release_datetime: str,
    end_release_datetime: str,
    lang: Lang = "en",
) -> VectorDataSet:
    """Get observations for multiple vectors released within a date range.

    Use for: bulk historical retrieval across several series at once,
    filtered by release date (not reference period).
    `start_release_datetime`/`end_release_datetime` are
    "YYYY-MM-DDTHH:MM" (e.g. "2024-01-01T08:30"); a bare date is widened
    to the start/end of that day. Vectors WDS cannot serve are listed in
    `failed`.
    Keywords: statcan, bulk, vectors, date range, release date, history,
    wds, Statistics Canada.
    Mots-clés : statcan, en masse, vecteurs, vecteurs multiples, plage de
    dates, date de diffusion, historique, wds.
    """
    client.use_lang(lang)
    return await client.get_bulk_vector_data_by_range(
        vector_ids, start_release_datetime, end_release_datetime
    )


@tool
async def wds_get_data_by_reference_period_range(
    vector_ids: list[int], start_ref_period: str, end_ref_period: str, lang: Lang = "en"
) -> VectorDataSet:
    """Get observations for vectors between two dates (a time series for a
    vector over a reference-period range).

    Use for: retrieving a specific historical window (e.g. 2015-01-01 to
    2020-12-01) rather than "latest N." `start_ref_period`/`end_ref_period`
    are "YYYY-MM-DD"; a "YYYY-MM" month is widened to its first/last
    day. Vectors WDS cannot serve are listed in `failed`.
    Keywords: statcan, reference period, range, between two dates, time
    series for a vector, history, vectors, wds, date range, Statistics
    Canada.
    Mots-clés : statcan, période de référence, plage, plage de dates,
    historique, vecteurs, données historiques, série chronologique
    entre deux dates, wds.
    """
    client.use_lang(lang)
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
    client.use_lang(lang)
    return await client.get_changed_series_list()


@tool
async def wds_get_changed_cube_list(date: str | None = None, lang: Lang = "en") -> ChangedCubeList:
    """List StatCan tables (cubes) that changed on a given date.

    Use for: detecting which tables were updated, e.g. after the daily
    8:30am ET release. `date` is YYYY-MM-DD (default: today, Eastern).
    Keywords: statcan, changed, updated, cube, table, release, today,
    wds.
    Mots-clés : statcan, modifié, mis à jour, cube, tableau, diffusion,
    aujourd'hui, wds.
    """
    client.use_lang(lang)
    return await client.get_changed_cube_list(date)


@tool
async def wds_get_changed_series_data(
    vector_id: int | None = None,
    product_id: ProductId | None = None,
    coordinate: str | None = None,
    lang: Lang = "en",
) -> VectorData:
    """Get just the newly-changed data points for one series, identified
    by vector ID or by table + coordinate.

    Use for: fetching only what changed rather than the full latest-N
    window, after wds_get_changed_series_list flags a vector. Pass
    exactly one form: `vector_id`, or `product_id` + `coordinate` (resolved
    to its vector first, so the series always belongs to that table). A
    series that did not change today gives a "nothing found" error.
    Keywords: statcan, changed, vector, coordinate, delta, updated data,
    wds, Statistics Canada, revisions.
    Mots-clés : statcan, modifié, vecteur, coordonnée, écart, données
    mises à jour, série, changements, tableau, wds.
    """
    client.use_lang(lang)
    _vector_or_coord("wds_get_changed_series_data", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        return await client.get_changed_series_data_from_vector(vector_id)
    assert product_id is not None and coordinate is not None
    return await client.get_changed_series_data_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_full_table_download(
    product_id: ProductId,
    format: Literal["csv", "sdmx"] = "csv",
    lang: Lang = "en",
) -> FullTableDownloadLink:
    """Get the download URL for a full StatCan table as CSV (default) or
    SDMX/XML (`format="sdmx"`).

    Use for: bulk/offline analysis of an entire table rather than
    individual series, in CSV or SDMX format — hands back a URL, does
    not fetch the file. `lang` picks the CSV language edition. An
    unknown table number is an error, not a dead link.
    Keywords: statcan, csv, sdmx, xml, download, full table, bulk,
    export, wds, Statistics Canada.
    Mots-clés : statcan, csv, sdmx, xml, téléchargement, tableau complet,
    en masse, exportation, wds, données complètes.
    """
    client.use_lang(lang)
    if format == "sdmx":
        return await client.get_full_table_download_sdmx(product_id)
    return await client.get_full_table_download_csv(product_id, lang)


@tool
async def wds_get_code_sets(
    category: CodeSetCategory | None = None,
    query: str | None = None,
    limit: int = constants.CODE_SET_LIMIT_DEFAULT,
    lang: Lang = "en",
) -> CodeSets:
    """Get StatCan's code-set descriptions: scalar factors, frequency,
    symbol, status, unit of measure, survey, subject, classification
    type, security level, and terminated codes.

    Use for: decoding any numeric code returned by another WDS tool,
    e.g. a scalarFactorCode, frequencyCode or subject code. The full set
    is ~300 kB, so each category returns at most `limit` entries (default
    100); pick one `category` and/or filter descriptions with `query`.
    `counts` gives each category's full size.
    Keywords: statcan, code sets, decode, scalar factor, frequency,
    symbol, status, uom, subject, survey, wds, lookup.
    Mots-clés : statcan, ensembles de codes, décoder, facteur d'échelle,
    fréquence, symbole, statut, unité de mesure, sujet, enquête, wds,
    référence.
    """
    client.use_lang(lang)
    return await client.get_code_sets(category=category, query=query, limit=limit)

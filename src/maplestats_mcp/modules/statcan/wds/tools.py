"""MCP tools for the StatCan Web Data Service (WDS).

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.wds import client, constants, transforms, vintage
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
    VintageSeries,
)
from maplestats_mcp.shared.envelope import raise_error
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.transform import Aggregation, Frequency, Transform

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
    topic (GDP by industry, the consumer price index (CPI), the monthly
    unemployment rate for Alberta, population estimates by province) or a
    number such as "18-10-0004",
    discovering which StatCan tables cover a subject before requesting
    metadata or data. Every word must
    be in a title, else the best partial matches come back. `limit`
    (default 25, max 500) and `offset` page the tables; total_count is
    the number matching. `real_time` marks real-time (revision-history)
    tables; statcan_delta_list_real_time_tables pairs the 19 with their regular tables.
    Keywords: statcan, find a StatCan table, statistics canada, table, cube, search, productId,
    discover, wds, catalogue, browse, list, inventory, all cubes, full
    list, tables, labour force, monthly unemployment rate, employment,
    GDP by industry, CPI, consumer price index monthly, population estimates
    quarterly, retail trade, wages, trade, interprovincial migration,
    time series, real-time table, Alberta, by province, which table has.
    Mots-clés : Statistique Canada, StatCan, chercher un tableau, trouver un
    tableau, quel tableau, tableau de données, recherche, tableaux,
    numéro de tableau, découverte, catalogue, parcourir, liste, inventaire,
    population active, taux de chômage mensuel, emploi, PIB par industrie,
    PIB industrie, produit intérieur brut, IPC, indice des prix à la consommation, permis
    de bâtir, permis de construire, estimations de population
    trimestrielles, commerce de détail, salaires, commerce, migration
    interprovinciale, séries chronologiques, tableau en temps réel,
    révisions, espérance de vie, mortalité.
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
    Mots-clés : Statistique Canada, métadonnées, dimensions, membres,
    structure du tableau, notes de bas de page, coordonnée, numéro de
    tableau, description du tableau.
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
    Mots-clés : Statistique Canada, vecteur, coordonnée, résoudre,
    conversion, information de série, identifiant de série, numéro de
    tableau, numéro de vecteur.
    """
    client.use_lang(lang)
    _vector_or_coord("wds_get_series_info", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        return await client.get_series_info_from_vector(vector_id)
    assert product_id is not None and coordinate is not None
    return await client.get_series_info_from_cube_pid_coord(product_id, coordinate)


@tool
async def wds_get_data_from_vectors(
    vector_ids: list[int],
    latest_n: int = 12,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    lang: Lang = "en",
) -> VectorDataSet:
    """Get the latest N observations for one or more StatCan vectors,
    optionally as a computed change (year-over-year, period-to-period),
    growth rate, index or quarterly/annual aggregate.

    Use for: getting the data for one or more StatCan vectors (recent
    values of known time series), and
    year-over-year inflation from the CPI, monthly or annualized growth,
    or a quarterly average of a monthly series. Results come back
    inline, so this suits a handful of series; for a whole table or
    hundreds of vectors use wds_get_full_table_download. Vectors WDS
    cannot serve are listed in `failed`; the others still come back.
    scalarFactorCode is NOT pre-applied to value: multiply `value` by
    the observation's `scale_multiplier` for a scaled figure. `status`,
    `symbol` and `security_level` decode the codes (e.g. "use with
    caution", "preliminary"). `latest_n` counts periods at the output
    frequency.
    `transform` (diff, pct_change, yoy_diff, yoy_pct_change,
    annualized_pct_change, index) and `frequency` with `aggregation`
    compute from the published levels; a series already in percent gets
    percentage-point changes. `transformed` holds the computed values
    with their formula.
    Keywords: statcan, vector, observations, latest, data, time series,
    wds, values, year-over-year, yoy, inflation rate, percent change,
    growth rate, annualized, quarterly average, annual average, index.
    Mots-clés : Statistique Canada, vecteur, observations, dernières
    données, données récentes, série chronologique, valeurs, dernières
    périodes, variation annuelle, glissement annuel, taux d'inflation,
    variation en pourcentage, taux de croissance, moyenne trimestrielle,
    moyenne annuelle, indice.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base)
    if not request.active:
        return await client.get_data_from_vectors_and_latest_n_periods(vector_ids, latest_n)
    if latest_n < 1:
        raise_error(InvalidInput, "error.invalid_input", lang, detail="latest_n must be 1 or more.")
    infos = await transforms.series_infos(vector_ids)
    fetch_n = transforms.latest_n_to_fetch(latest_n, request, transforms.ppys(list(infos.values())))
    data = await client.get_data_from_vectors_and_latest_n_periods(vector_ids, fetch_n)
    series = [
        await transforms.apply(s, infos.get(s.vector_id), request, latest_n=latest_n)
        for s in data.series
    ]
    provenance = data.provenance.model_copy(
        update={"coverage": transforms.coverage_note(f"latestN={fetch_n}")}
    )
    return data.model_copy(update={"series": series, "provenance": provenance})


@tool
async def wds_get_data_from_cube_coord(
    product_id: ProductId,
    coordinate: str,
    latest_n: int = 12,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    lang: Lang = "en",
) -> VectorData:
    """Get the latest N observations for a table + coordinate pair,
    optionally as a computed change, growth rate, index or aggregate.

    Use for: fetching data when you have a productId/coordinate but not
    yet the vector ID, including year-over-year or period-to-period
    changes. `status`, `symbol` and `security_level` decode the codes.
    `latest_n` counts periods at the output frequency.
    `transform` computes a change from the published levels: diff
    (x_t - x_{t-1}), pct_change, yoy_diff, yoy_pct_change (year-over-year,
    against the same period a year earlier: 12-month CPI inflation),
    annualized_pct_change, or index (100 at `index_base`, e.g. "2020").
    `frequency` ("monthly", "quarterly", "annual") first aggregates with
    `aggregation` (average, sum, end_of_period). A percent change of a
    series already in percent or a rate (unemployment rate, bank rate)
    comes back as the change in percentage points, and says so. Enough
    history is fetched for the lag; `observations` keep the published
    values and `transformed` holds the computed ones with their formula
    and unit.
    Keywords: statcan, coordinate, observations, latest, data, wds,
    productId, Statistics Canada, year-over-year, percent change, growth
    rate, quarterly average, annual average.
    Mots-clés : Statistique Canada, coordonnée, observations, dernières
    données, données récentes, numéro de tableau, tableau, dernières
    périodes, variation annuelle, variation en pourcentage, taux de
    croissance, moyenne trimestrielle.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base)
    if not request.active:
        return await client.get_data_from_cube_pid_coord_and_latest_n_periods(
            product_id, coordinate, latest_n
        )
    if latest_n < 1:
        raise_error(InvalidInput, "error.invalid_input", lang, detail="latest_n must be 1 or more.")
    info = await client.get_series_info_from_cube_pid_coord(product_id, coordinate)
    fetch_n = transforms.latest_n_to_fetch(latest_n, request, transforms.ppys([info]))
    data = await client.get_data_from_cube_pid_coord_and_latest_n_periods(
        product_id, coordinate, fetch_n
    )
    result = await transforms.apply(data, info, request, latest_n=latest_n)
    provenance = data.provenance.model_copy(
        update={"coverage": transforms.coverage_note(f"latestN={fetch_n}")}
    )
    return data.model_copy(
        update={
            "observations": result.observations,
            "transformed": result.transformed,
            "provenance": provenance,
        }
    )


@tool
async def wds_get_series_as_of(
    as_of: str,
    vector_id: int | None = None,
    product_id: ProductId | None = None,
    coordinate: str | None = None,
    latest_n: int = 12,
    lang: Lang = "en",
) -> VintageSeries:
    """Get a StatCan series as it was published on a past date, before
    later revisions (a vintage), from StatCan's real-time tables.

    Use for: what was known at the time, such as the GDP, CPI core
    inflation, employment, retail or trade figures an analyst or the Bank
    of Canada saw on a given date; comparing a first estimate with the
    revised value; real-time forecasting evaluation. Pass the series of
    the regular table (`vector_id`, or `product_id` + `coordinate`) and
    `as_of` ("YYYY-MM-DD"): the values come from the latest release on or
    before that date, with `release_date` saying which. Only the 16
    regular tables WDS pairs with a real-time table have this history
    (statcan_delta_list_real_time_tables lists them); any other table is
    an error, not current data. Values are unscaled, as in every WDS
    tool.
    Keywords: vintage, real-time data, as of date, first estimate,
    revision history, as originally published, past release, unrevised
    data, historical releases, Statistics Canada.
    Mots-clés : millésime, données en temps réel, à une date donnée,
    première estimation, historique des révisions, tel que publié à
    l'origine, diffusion antérieure, données non révisées.
    """
    client.use_lang(lang)
    _vector_or_coord("wds_get_series_as_of", vector_id, product_id, coordinate, lang)
    if vector_id is not None:
        info = await client.get_series_info_from_vector(vector_id)
        product_id, coordinate = info.product_id, info.coordinate
    assert product_id is not None and coordinate is not None
    return await vintage.get_series_as_of(product_id, coordinate, as_of, latest_n)


@tool
async def wds_get_bulk_vector_data_by_range(
    vector_ids: list[int],
    start_release_datetime: str,
    end_release_datetime: str,
    lang: Lang = "en",
) -> VectorDataSet:
    """Get observations for multiple vectors released within a date range.

    Use for: bulk historical retrieval across several series at once,
    filtered by release date (not reference period). Results come back
    inline; for hundreds of series use wds_get_full_table_download.
    `start_release_datetime`/`end_release_datetime` are
    "YYYY-MM-DDTHH:MM" (e.g. "2024-01-01T08:30"); a bare date is widened
    to the start/end of that day. Vectors WDS cannot serve are listed in
    `failed`.
    Keywords: statcan, bulk, vectors, date range, release date, history,
    wds, Statistics Canada.
    Mots-clés : Statistique Canada, extraction en bloc, vecteurs, plusieurs
    vecteurs, plage de dates, date de diffusion, historique, séries
    chronologiques.
    """
    client.use_lang(lang)
    return await client.get_bulk_vector_data_by_range(
        vector_ids, start_release_datetime, end_release_datetime
    )


@tool
async def wds_get_data_by_reference_period_range(
    vector_ids: list[int],
    start_ref_period: str,
    end_ref_period: str,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    lang: Lang = "en",
) -> VectorDataSet:
    """Get observations for vectors between two dates (a time series for a
    vector over a reference-period range), optionally as a computed
    change, growth rate, index or quarterly/annual aggregate.

    Use for: retrieving a specific historical window (e.g. 2015-01-01 to
    2020-12-01) rather than "latest N", and year-over-year inflation or
    growth over that window. `start_ref_period`/`end_ref_period`
    are "YYYY-MM-DD"; a "YYYY-MM" month is widened to its first/last
    day. Results come back inline, so this suits a handful of series;
    for hundreds use wds_get_full_table_download. Vectors WDS cannot
    serve are listed in `failed`.
    `transform` computes a change from the published levels: diff
    (x_t - x_{t-1}), pct_change, yoy_diff, yoy_pct_change (year-over-year,
    against the same period a year earlier: 12-month CPI inflation),
    annualized_pct_change, or index (100 at `index_base`, e.g. "2020").
    `frequency` ("monthly", "quarterly", "annual") first aggregates with
    `aggregation` (average, sum, end_of_period). A percent change of a
    series already in percent or a rate (unemployment rate, bank rate)
    comes back as the change in percentage points, and says so. Enough
    history is fetched for the lag; `observations` keep the published
    values and `transformed` holds the computed ones with their formula
    and unit.
    Keywords: statcan, reference period, range, between two dates, time
    series for a vector, history, vectors, wds, date range, Statistics
    Canada, year-over-year, inflation, percent change, growth rate,
    annual average.
    Mots-clés : Statistique Canada, période de référence, plage, plage de
    dates, historique, vecteurs, données historiques, série chronologique
    entre deux dates, variation annuelle, glissement annuel, taux
    d'inflation, taux de croissance, moyenne annuelle.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base)
    if not request.active:
        return await client.get_data_from_vector_by_reference_period_range(
            vector_ids, start_ref_period, end_ref_period
        )
    start = date.fromisoformat(client._ref_period(start_ref_period, "start_ref_period", end=False))
    end = date.fromisoformat(client._ref_period(end_ref_period, "end_ref_period", end=True))
    infos = await transforms.series_infos(vector_ids)
    fetch_start = transforms.start_to_fetch(start, request, transforms.ppys(list(infos.values())))
    data = await client.get_data_from_vector_by_reference_period_range(
        vector_ids, fetch_start.isoformat(), end.isoformat()
    )
    series = [
        await transforms.apply(
            s, infos.get(s.vector_id), request, window_start=start, window_end=end
        )
        for s in data.series
    ]
    provenance = data.provenance.model_copy(
        update={"coverage": transforms.coverage_note(f"{fetch_start.isoformat()} to {end}")}
    )
    return data.model_copy(update={"series": series, "provenance": provenance})


@tool
async def wds_get_changed_series_list(lang: Lang = "en") -> ChangedSeriesList:
    """List StatCan series that changed (new release) today.

    Use for: detecting updated series for a scheduled refresh. WDS
    documents this method as always reflecting today's changes — it
    does not accept a date parameter (unlike wds_get_changed_cube_list).
    Keywords: statcan, changed, updated, series, release, today, wds,
    refresh.
    Mots-clés : Statistique Canada, séries modifiées, mises à jour, série,
    diffusion, aujourd'hui, actualisation, nouvelles données.
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
    Mots-clés : Statistique Canada, tableaux modifiés, mises à jour,
    tableau, diffusion, aujourd'hui, actualisation, nouvelles données.
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
    Mots-clés : Statistique Canada, données modifiées, vecteur, coordonnée,
    écart, données mises à jour, série, changements, tableau, révisions.
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
    not fetch the file. Also the way to get hundreds of series, or to
    reconcile a workbook of vector IDs against a published table: the
    CSV has a VECTOR column to join on, where the vector tools return
    every observation inline. `lang` picks the CSV language edition. An
    unknown table number is an error, not a dead link.
    Keywords: statcan, csv, sdmx, xml, download, full table, bulk,
    export, wds, Statistics Canada, vector column, join, reconcile,
    hundreds of series, offline.
    Mots-clés : Statistique Canada, CSV, SDMX, XML, téléchargement, tableau
    complet, téléchargement en bloc, exportation, données complètes, fichier
    du tableau, colonne VECTOR, jointure, rapprochement, centaines de séries.
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
    Mots-clés : Statistique Canada, ensembles de codes, décoder, facteur
    d'échelle, fréquence, symbole, statut, unité de mesure, sujet, enquête,
    référence.
    """
    client.use_lang(lang)
    return await client.get_code_sets(category=category, query=query, limit=limit)

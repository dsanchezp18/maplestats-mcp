"""MCP tools for the StatCan Web Data Service (WDS).

Every tool returns a typed Pydantic model (see schemas.py) — FastMCP
derives outputSchema/structuredContent from the return-type annotation
automatically. A raised exception (see shared/errors.py) becomes a real
MCP isError:true result; tools never return an error-shaped dict.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.wds import (
    client,
    constants,
    context,
    fallback,
    leaves,
    query,
    table_query,
    transforms,
    vintage,
)
from maplestats_mcp.modules.statcan.wds.client import CodeSetCategory
from maplestats_mcp.modules.statcan.wds.fallback_types import Wanted
from maplestats_mcp.modules.statcan.wds.schemas import (
    ChangedCubeList,
    ChangedSeriesList,
    CodeSets,
    CubeMetadata,
    CubeSummaryList,
    FullTableDownloadLink,
    LeafMembers,
    SeriesInfo,
    SeriesQueryResult,
    TableQueryResult,
    VectorData,
    VectorDataSet,
    VintageSeries,
)
from maplestats_mcp.shared import substitution
from maplestats_mcp.shared.envelope import raise_error
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.limits import join_limits
from maplestats_mcp.shared.newer_data import newer_data_note
from maplestats_mcp.shared.transform import Aggregation, Frequency, Transform

Lang = Literal["en", "fr"]
# An 8-digit productId, or the table number as StatCan prints it.
ProductId = int | str


async def _described[R: (VectorData, VectorDataSet)](result: R) -> R:
    """`result` with each series' context (table, title, unit, members, notes) filled."""
    if isinstance(result, VectorDataSet) or result.series is not None:
        series, note = await context.describe(list(result.series or []))
        update: dict[str, object] = {"series": series}
    else:
        described, note = await context.describe([result])
        update = {"context": described[0].context}
    if note:
        update["provenance"] = result.provenance.model_copy(
            update={"limits": join_limits(result.provenance.limits, note)}
        )
    return result.model_copy(update=update)


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
    topic (monthly GDP by industry, the consumer price index (CPI), the
    Labour Force Survey monthly unemployment rate for Alberta or a CMA,
    average hourly wages by
    occupation, population estimates by province) or a number such as
    "18-10-0004",
    discovering which StatCan tables cover a subject before requesting
    metadata or data. Every word must
    be in a title, else the best partial matches come back; active tables
    come before archived ones. `limit`
    (default 25, max 500) and `offset` page the tables; total_count is
    the number matching. `real_time` marks real-time (revision-history)
    tables; statcan_delta_list_real_time_tables pairs the 19 with their regular tables.
    Keywords: statcan, find a StatCan table, statistics canada, table, cube, search, productId,
    discover, wds, catalogue, browse, list, inventory, all cubes, full
    list, tables, labour force, Labour Force Survey, monthly
    unemployment rate, employment,
    GDP by industry monthly, CPI, consumer price index monthly, population estimates
    quarterly, retail trade, wages, trade, interprovincial migration,
    time series, real-time table, Alberta, by province, which table has,
    LFS, SEPH, MBM, low income, CMA, Toronto, monthly GDP, wages by
    occupation, nurses.
    Mots-clés : Statistique Canada, StatCan, chercher un tableau, trouver un
    tableau, quel tableau, tableau de données, recherche, tableaux,
    numéro de tableau, découverte, catalogue, parcourir, liste, inventaire,
    Enquête sur la population active, EPA, taux de chômage mensuel, emploi, PIB par industrie,
    PIB industrie, produit intérieur brut, IPC, indice des prix à la consommation, permis
    de bâtir, permis de construire, estimations de population
    trimestrielles, commerce de détail, ventes au détail, salaires, commerce, migration
    interprovinciale, séries chronologiques, tableau en temps réel,
    révisions, espérance de vie, mortalité, RMR, PIB mensuel, salaire
    selon la profession, infirmières.
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
    at most `footnote_limit` distinct footnotes come back (default 10; a
    note WDS repeats under several ids comes once, with `same_text_ids`);
    provenance.limits says what was cut. Narrow with `dimension` (a position, e.g. 1 for geography),
    `member_query` (words in a member name) and `member_offset`.
    Keywords: statcan, metadata, dimensions, members, productId, cube,
    structure, footnotes, wds, coordinate, table number.
    Mots-clés : Statistique Canada, métadonnées, dimensions, membres,
    structure du tableau, notes de bas de page, coordonnée, numéro de
    tableau, description du tableau.
    """
    client.use_lang(lang)
    try:
        return await client.get_cube_metadata(
            product_id,
            dimension=dimension,
            member_query=member_query,
            member_limit=member_limit,
            member_offset=member_offset,
            footnote_limit=footnote_limit,
        )
    except substitution.TRIGGERS as exc:
        if not substitution.enabled():
            raise
        # No other source carries WDS's member ids, the numbers a coordinate is built from.
        raise await fallback.refuse(
            exc,
            lang,
            product_id=client.normalize_product_id(product_id),
            why=_m(
                "WDS table metadata (the member ids a coordinate is built from) is carried by "
                "no other source.",
                "Les métadonnées de tableau du SDW (les identifiants de membre dont se forme "
                "une coordonnée) ne sont détenues par aucune autre source.",
                lang,
            ),
        ) from exc


@tool
async def wds_get_leaf_members(
    product_id: ProductId,
    dimension: int | str,
    under_member_id: int | None = None,
    member_query: str | None = None,
    include_flagged: bool = False,
    limit: int = constants.LEAF_LIMIT_DEFAULT,
    offset: int = 0,
    lang: Lang = "en",
) -> LeafMembers:
    """List only the lowest-level (leaf) members of one dimension of a
    StatCan table, so a sum or ranking does not double-count totals and
    subtotals.

    Use for: adding up or ranking across provinces, industries or
    product groups without the totals ("All industries", "All-items",
    "Canada") and subtotals mixed in. A leaf is a member that is no
    other member's parent. `dimension` is the position (1 is usually
    Geography) or the dimension's name ("Geography", "Products"). `under_member_id` keeps the leaves below one member (a
    NAICS sector, the CPI's "Food", a province), the reliable way to
    take a branch: children rarely repeat the parent's name.
    `member_query` filters leaf names. Leaves that may still double-count
    go to flagged_leaves: names like totals, StatCan's T-coded special
    aggregates ("Goods-producing industries", "Energy sector"), and
    leaves outside the top-level member holding most leaves (CPI "All-
    items excluding food"); include_flagged=True keeps them. Geography:
    leaves are the lowest level present, so provinces are leaves of
    Canada in the Labour Force Survey tables, but in the monthly CPI
    table the leaves are cities, the provinces being their parents
    (Whitehorse sits directly under Canada); geo_levels counts the levels,
    and city leaves need not add up to a province. A dimension with no
    parent links (age groups) makes every member a leaf. Returns
    member_ids, a comma list, an SDMX '+' key fragment and full key for
    sdmx_get_data (one call), and example coordinates for
    wds_get_data_from_cube_coord. sdmx_get_key_for_dimension gives an
    unfiltered leaf key only.
    Keywords: statcan, leaf members, lowest level, avoid double counting,
    exclude totals, subtotals, sum across provinces, rank industries,
    NAICS detail, CPI components, hierarchy, dimension members, sdmx key,
    coordinate.
    Mots-clés : Statistique Canada, membres terminaux, niveau le plus fin,
    éviter le double comptage, exclure les totaux, sous-totaux, somme des
    provinces, classement des industries, détail SCIAN, composantes de
    l'IPC, hiérarchie, membres de dimension, clé SDMX, coordonnée.
    """
    client.use_lang(lang)
    return await leaves.get_leaf_members(
        product_id,
        dimension,
        under_member_id=under_member_id,
        member_query=member_query,
        include_flagged=include_flagged,
        limit=limit,
        offset=offset,
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
    A challenged WDS gets a labelled stand-in.
    Keywords: statcan, vector, coordinate, resolve, productId, series
    info, wds, Statistics Canada, conversion, identifier.
    Mots-clés : Statistique Canada, vecteur, coordonnée, résoudre,
    conversion, information de série, identifiant de série, numéro de
    tableau, numéro de vecteur.
    """
    client.use_lang(lang)
    _vector_or_coord("wds_get_series_info", vector_id, product_id, coordinate, lang)
    try:
        if vector_id is not None:
            return await client.get_series_info_from_vector(vector_id)
        assert product_id is not None and coordinate is not None
        return await client.get_series_info_from_cube_pid_coord(product_id, coordinate)
    except substitution.TRIGGERS as exc:
        if not substitution.enabled():
            raise
        wanted = (
            Wanted(vector_id=vector_id)
            if vector_id is not None
            else Wanted(
                product_id=client.normalize_product_id(product_id or 0),
                coordinate=client._pad_coordinate(coordinate or ""),
            )
        )
        return await fallback.series_info(exc, wanted, lang)


@tool
async def wds_get_data_from_vectors(
    vector_ids: list[int],
    latest_n: int = 12,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    window: int | None = None,
    lang: Lang = "en",
) -> VectorDataSet:
    """Get the latest N observations for one or more StatCan vectors,
    optionally as a computed change (year-over-year, period-to-period),
    growth rate, index or quarterly/annual aggregate.

    Use for: getting the data for one or more StatCan vectors (recent
    values of known time series, such as a Labour Force Survey
    unemployment rate or employment vector), and
    year-over-year inflation from the CPI (the latest Canadian inflation
    rate, Canada or a province), monthly or annualized growth,
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
    annualized_pct_change, index, moving_average: trailing average over
    `window` periods; `window` with a change averages the change) and
    `frequency` with `aggregation`
    compute from the published levels; a series already in percent gets
    percentage-point changes. `transformed` holds the computed values
    with their formula.
    A challenged WDS gets a labelled stand-in.
    Keywords: statcan, vector, observations, latest, data, time series,
    wds, values, year-over-year, yoy, inflation rate, CPI inflation, percent change,
    growth rate, annualized, quarterly average, annual average, index,
    moving average, rolling average.
    Mots-clés : Statistique Canada, vecteur, observations, dernières
    données, données récentes, série chronologique, valeurs, dernières
    périodes, variation annuelle, glissement annuel, taux d'inflation, inflation de l'IPC,
    variation en pourcentage, taux de croissance, moyenne trimestrielle,
    moyenne annuelle, indice, moyenne mobile.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base, window)
    request.check(lang)
    client._check_vector_ids(vector_ids)
    try:
        return await _vectors_from_wds(vector_ids, latest_n, request, lang)
    except substitution.TRIGGERS as exc:
        if not substitution.enabled():
            raise
        if request.active:
            raise await fallback.refuse(exc, lang, why=_levels_only(lang)) from exc
        return await fallback.vectors(exc, vector_ids, latest_n, lang)


def _m(en: str, fr: str, lang: str) -> str:
    return fr if lang == "fr" else en


def _levels_only(lang: str) -> str:
    return _m(
        "A transform or frequency needs WDS's unit codes, and the substitute sources serve "
        "published levels only: ask again without transform and frequency.",
        "Une transformation ou une fréquence a besoin des codes d'unité du SDW, et les sources "
        "de remplacement ne servent que les niveaux publiés : redemandez sans transform ni "
        "frequency.",
        lang,
    )


async def _vectors_from_wds(
    vector_ids: list[int], latest_n: int, request: transforms.TransformRequest, lang: str
) -> VectorDataSet:
    if not request.active:
        data, _ = await asyncio.gather(
            client.get_data_from_vectors_and_latest_n_periods(vector_ids, latest_n),
            context.prefetch(vector_ids),
        )
        return await _described(data)
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
    return await _described(data.model_copy(update={"series": series, "provenance": provenance}))


async def _cube_frequency_ppy(pid: int, coordinate: str) -> int | None:
    """Periods per year of a table's series, from its cached cube metadata.

    getCubeMetadata (cached a day, and read anyway for the series context) carries
    the table's frequencyCode, so a transform needs no getSeriesInfoFromCubePidCoord
    request just to learn it. When the metadata cannot be read, that request is
    the fallback, and it explains a coordinate the table does not have.
    """
    try:
        cube, _ = await client.cube_metadata_raw(pid)
        return transforms.FREQUENCY_PPY.get(int(cube.get("frequencyCode") or 0))
    except (*context._SOFT_ERRORS, KeyError, ValueError, TypeError):
        info = await client.get_series_info_from_cube_pid_coord(pid, coordinate)
        return transforms.ppys([info])[0]


@tool
async def wds_get_data_from_cube_coord(
    product_id: ProductId,
    coordinate: str | None = None,
    latest_n: int = 12,
    transform: Transform = "level",
    frequency: Frequency | None = None,
    aggregation: Aggregation = "average",
    index_base: str | None = None,
    window: int | None = None,
    lang: Lang = "en",
    coordinates: list[str] | None = None,
) -> VectorData:
    """Get the latest N observations for one or more coordinates of a
    StatCan table, optionally as a computed change, growth rate, index or
    aggregate.

    Use for: fetching data when you have a productId/coordinate but not
    yet the vector ID, including year-over-year or period-to-period
    changes. For several series of one table (every province, several
    components), pass them all at once in `coordinates` (up to 300, one
    request) instead of one call per coordinate; each comes back in
    `series`, in the order given, and any WDS cannot serve is listed in
    `failed` with the reason. With one `coordinate` the series is at the
    top level, as before.
    `status`, `symbol` and `security_level` decode the codes.
    `latest_n` counts periods at the output frequency.
    `transform` computes a change from the published levels: diff
    (x_t - x_{t-1}), pct_change, yoy_diff, yoy_pct_change (year-over-year,
    against the same period a year earlier: 12-month CPI inflation),
    annualized_pct_change, index (100 at `index_base`, e.g. "2020"), or
    moving_average (trailing average over `window` periods); `window`
    with a change averages the change.
    `frequency` ("monthly", "quarterly", "annual") first aggregates with
    `aggregation` (average, sum, end_of_period). A percent change of a
    series already in percent or a rate (unemployment rate, bank rate)
    comes back as the change in percentage points, and says so. Enough
    history is fetched for the lag; `observations` keep the published
    values and `transformed` holds the computed ones with their formula
    and unit.
    A challenged WDS gets a labelled stand-in.
    Keywords: statcan, coordinate, coordinates, table series, every
    province, observations, latest, data, wds, productId, Statistics
    Canada, year-over-year, percent change, growth rate, quarterly
    average, annual average, moving average, rolling average.
    Mots-clés : Statistique Canada, coordonnée, plusieurs coordonnées,
    plusieurs séries, toutes les provinces, observations, dernières
    données, données récentes, numéro de tableau, tableau, dernières
    périodes, variation annuelle, variation en pourcentage, taux de
    croissance, moyenne trimestrielle, moyenne mobile.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base, window)
    request.check(lang)
    asked = ([coordinate] if coordinate else []) + list(coordinates or [])
    pid = client.normalize_product_id(product_id)
    padded = client.check_coordinates(asked, latest_n)
    try:
        return await _coordinates_from_wds(pid, padded, latest_n, request)
    except substitution.TRIGGERS as exc:
        if not substitution.enabled():
            raise
        if request.active:
            raise await fallback.refuse(exc, lang, product_id=pid, why=_levels_only(lang)) from exc
        return await fallback.coordinates(exc, pid, padded, latest_n, lang)


async def _coordinates_from_wds(
    pid: int, padded: list[str], latest_n: int, request: transforms.TransformRequest
) -> VectorData:
    if not request.active:
        data, _ = await asyncio.gather(
            client.get_data_from_cube_pid_coords_and_latest_n_periods(pid, padded, latest_n),
            context.prefetch([], [pid]),
        )
        return await _described(data)
    fetch_n = transforms.latest_n_to_fetch(
        latest_n, request, [await _cube_frequency_ppy(pid, padded[0])]
    )
    data = await client.get_data_from_cube_pid_coords_and_latest_n_periods(pid, padded, fetch_n)
    fetched = data.series if data.series is not None else [data]
    try:
        raw = await context.series_info_raw(sorted({s.vector_id for s in fetched}))
    except context._SOFT_ERRORS:
        raw = {}
    infos = {v: client._series_info(obj, "getSeriesInfoFromVector") for v, obj in raw.items()}
    computed = [
        await transforms.apply(s, infos.get(s.vector_id), request, latest_n=latest_n)
        for s in fetched
    ]
    provenance = data.provenance.model_copy(
        update={"coverage": transforms.coverage_note(f"latestN={fetch_n}")}
    )
    if data.series is not None:
        update: dict[str, object] = {
            "series": computed,
            "provenance": provenance,
        }
    else:
        update = {
            "observations": computed[0].observations,
            "transformed": computed[0].transformed,
            "provenance": provenance,
        }
    return await _described(data.model_copy(update=update))


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
    before that date, with `release_date` saying which. Only these 16
    tables have this history: 12-10-0163, 14-10-0220, 14-10-0223,
    16-10-0012, 16-10-0013, 18-10-0256, 20-10-0003, 20-10-0056,
    20-10-0067, 20-10-0076, 34-10-0035, 34-10-0036, 36-10-0018,
    36-10-0103, 36-10-0104, 36-10-0434; any other table is an error,
    not current data.
    Values are unscaled, as in every WDS tool.
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
    return await _described(
        await client.get_bulk_vector_data_by_range(
            vector_ids, start_release_datetime, end_release_datetime
        )
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
    window: int | None = None,
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
    annualized_pct_change, index (100 at `index_base`, e.g. "2020"), or
    moving_average (trailing average over `window` periods); `window`
    with a change averages the change.
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
    annual average, moving average, rolling average.
    Mots-clés : Statistique Canada, période de référence, plage, plage de
    dates, historique, vecteurs, données historiques, série chronologique
    entre deux dates, variation annuelle, glissement annuel, taux
    d'inflation, taux de croissance, moyenne annuelle, moyenne mobile.
    """
    client.use_lang(lang)
    request = transforms.TransformRequest(transform, frequency, aggregation, index_base, window)
    request.check(lang)
    client._check_vector_ids(vector_ids)
    if not request.active:
        data, _ = await asyncio.gather(
            client.get_data_from_vector_by_reference_period_range(
                vector_ids, start_ref_period, end_ref_period
            ),
            context.prefetch(vector_ids),
        )
        return _with_newer_data_note(await _described(data), end_ref_period, lang)
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
    return _with_newer_data_note(
        await _described(data.model_copy(update={"series": series, "provenance": provenance})),
        end_ref_period,
        lang,
    )


def _with_newer_data_note(result: VectorDataSet, end_ref_period: str, lang: str) -> VectorDataSet:
    """`result`, its limits led by a note when a series has data after the range."""
    end = date.fromisoformat(client._ref_period(end_ref_period, "end_ref_period", end=True))
    contexts = [s.context for s in result.series if s.context and s.context.last_period]
    if not contexts:
        return result
    newest = max(contexts, key=lambda c: c.last_period or end)
    released = (newest.table_release_time or "")[:10] or None
    note = newer_data_note(
        requested_end=end,
        latest=newest.last_period,
        latest_args=(
            "latest_n à wds_get_data_from_vectors"
            if lang == "fr"
            else "latest_n to wds_get_data_from_vectors"
        ),
        released=released,
        lang=lang,
    )
    if note is None:
        return result
    provenance = result.provenance.model_copy(
        update={"limits": join_limits(note, result.provenance.limits)}
    )
    return result.model_copy(update={"provenance": provenance})


# Left undefined when MAPLE_QUERY_SERIES=0, so discovery never lists it. The hosted
# server sets it to 0 until each query runs in a memory-capped process: one query
# could otherwise exhaust the instance's memory (security review, 2026-11-03).
if config.get_query_series_enabled():

    @tool
    async def wds_query_series(
        vector_ids: list[int],
        sql: str,
        start_ref_period: str | None = None,
        end_ref_period: str | None = None,
        latest_n: int | None = None,
        lang: Lang = "en",
    ) -> SeriesQueryResult:
        """Run one read-only SQL query over a few StatCan series on the server
        and get back only its result: a sum, an average by year, a ranking, a
        peak, a comparison between series, instead of every observation.

        Use for: computing from StatCan vectors without adding up hundreds of
        values yourself, e.g. the annual average CPI or unemployment rate, the
        month with the highest value, provinces ranked by growth, the gap
        between two series, a count of months above a threshold. The server
        fetches up to 20 `vector_ids` for a window (`start_ref_period` and
        `end_ref_period` as "YYYY-MM-DD" or "YYYY-MM", or `latest_n` periods,
        default 12), loads them into a table `obs` and runs `sql` with DuckDB.
        `obs` columns: vector_id, product_id, table_id, coordinate, ref_period
        (DATE), value (unscaled: times scale_multiplier for the full figure),
        scale_multiplier, decimals, status, symbol, release_time, series_title,
        table_title, unit, scale, frequency, geography, adjustment, quality
        (E/F/x). Example: SELECT vector_id, year(ref_period) AS year,
        avg(value) FROM obs GROUP BY ALL ORDER BY ALL. A query that mixes units
        or adjustments, or sums a total with its own parts, is refused with
        the reason. One read-only SELECT runs in a sandbox (no files, URLs or
        extensions; time and memory limits); at most 500 rows come back. Quote
        the `series` citations and any `warnings` with the result.
        Keywords: statcan, SQL, query, compute, calculate, aggregate, sum,
        average, annual average, mean, group by, ranking, rank, top, maximum,
        minimum, peak, compare series, DuckDB, analysis, vectors, server-side.
        Mots-clés : Statistique Canada, requête SQL, calculer, calcul, agréger,
        somme, moyenne, moyenne annuelle, regrouper, classement, classer,
        maximum, minimum, sommet, comparer des séries, analyse, vecteurs,
        calcul côté serveur.
        """
        client.use_lang(lang)
        return await query.query_series(
            vector_ids,
            sql,
            start_ref_period=start_ref_period,
            end_ref_period=end_ref_period,
            latest_n=latest_n,
        )


if config.get_query_series_enabled():

    @tool
    async def wds_query_table(
        product_id: ProductId,
        sql: str,
        members: dict[str, list[str]] | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        lang: Lang = "en",
    ) -> TableQueryResult:
        """Run one read-only SQL query over a whole StatCan table, or a slice of
        it, on the server, and get back only its result.

        Use for: questions across many series of one table that
        wds_query_series (20 vectors) cannot hold: every province by
        industry, all age groups, a ranking across a table's breadth. The
        server reads the table's full-table CSV as it downloads (tables up to
        200 MB zipped), keeps the rows of `members` ({"Geography":
        ["Alberta"]}, names as in wds_get_cube_metadata) and of
        `start_period` to `end_period` (REF_DATE's form: 2020, 2020-01), and
        runs `sql` with DuckDB over them as the table `obs`: the columns of
        wds_query_series plus one per dimension (`dimension_columns` names
        them, e.g. labour_force_characteristics). A query that mixes units
        or adjustments, or sums a total with its own parts, is refused with
        the reason. At most 300,000 rows load and 500 come back. Quote the
        `citation` and any `warnings` with the result.
        Keywords: statcan, SQL, whole table, full table, query table,
        aggregate, group by, ranking, slice, DuckDB, all members, breadth.
        Mots-clés : Statistique Canada, requête SQL, tableau complet, tableau
        entier, agréger, regrouper, classement, tranche, tous les membres.
        """
        client.use_lang(lang)
        return await table_query.query_table(
            product_id, sql, members=members, start_period=start_period, end_period=end_period
        )


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
        return await _described(await client.get_changed_series_data_from_vector(vector_id))
    assert product_id is not None and coordinate is not None
    return await _described(
        await client.get_changed_series_data_from_cube_pid_coord(product_id, coordinate)
    )


@tool
async def wds_get_full_table_download(
    product_id: ProductId,
    format: Literal["csv", "sdmx"] = "csv",
    members: dict[str, list[str]] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    lang: Lang = "en",
) -> FullTableDownloadLink:
    """Get a whole StatCan table: its file link, and (CSV) a Python script
    that rebuilds the same CSV through WDS.

    Use for: an entire table, or hundreds of its series, for offline
    analysis; or reconciling a workbook of vector IDs against a published
    table (the CSV has a VECTOR column to join on). StatCan serves the file
    to most scripts, but since November 2026 answers some networks with a
    captcha only a person in a browser can pass; `file_check` says which it
    answered just now. For CSV the tool also returns a Python script that
    rebuilds the table through WDS, which StatCan serves everywhere: the
    same columns, order and values as StatCan's file, written to data/raw/.
    reproduce_code writes R, Python and Stata scripts that download the
    file and rebuild through WDS only at the captcha. `members` ({"Geography": ["Canada", "Ontario"]}, dimension
    and member names as in wds_get_cube_metadata) and `start_period` /
    `end_period` (REF_DATE's form: 2020, 2020-01) keep part of the table.
    `rebuild` gives its size in WDS calls; past the limit there is no
    script and the notes say to narrow it. Offer the script; run it only if
    the user agrees. An unknown table, dimension or member is an error.
    Keywords: statcan, csv, sdmx, download, full table, bulk, export, wds,
    Statistics Canada, rebuild table, vector column, join, reconcile,
    hundreds of series, offline, large table.
    Mots-clés : Statistique Canada, CSV, SDMX, téléchargement, tableau
    complet, téléchargement en bloc, exportation, reconstruire le tableau,
    colonne VECTOR, jointure, rapprochement, centaines de séries, grand
    tableau.
    """
    client.use_lang(lang)
    if format == "sdmx":
        if members or start_period or end_period:
            raise_error(
                InvalidInput,
                "error.invalid_input",
                lang,
                detail=(
                    "wds_get_full_table_download: members, start_period and end_period shape "
                    'the WDS rebuild script of the CSV; format="sdmx" returns the link only.'
                ),
            )
        return await client.get_full_table_download_sdmx(product_id)
    return await client.get_full_table_download_csv(
        product_id, lang, members, start_period, end_period
    )


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

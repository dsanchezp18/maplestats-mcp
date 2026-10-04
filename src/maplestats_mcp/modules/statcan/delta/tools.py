"""MCP tools for StatCan's Delta File bulk daily-update archive."""

from __future__ import annotations

from typing import Literal

from fastmcp.tools import tool

from maplestats_mcp.modules.statcan.delta import archive, client, realtime
from maplestats_mcp.modules.statcan.delta.archive_schemas import (
    DeltaFileList,
    DeltaTableData,
    DeltaTableList,
    RealTimeTableList,
)
from maplestats_mcp.modules.statcan.delta.schemas import DeltaFileLink

Lang = Literal["en", "fr"]


@tool
async def statcan_delta_get_file_link(date: str, lang: Lang = "en") -> DeltaFileLink:
    """Get the Delta File download link for one date, confirming it exists.

    Use for: bulk-downloading every table/vector data and metadata
    update StatCan released on one business day, as a single ZIP --
    the preferred mechanism (per StatCan's own developer guidance) for
    large updates, rather than re-fetching individual tables one at a
    time. date is "YYYY-MM-DD". A Delta File only exists for business
    days that had a release (weekends and holidays will report
    exists=False); check exists before treating the url as
    downloadable. Files can be very large (20261001.zip is 3.9 GB):
    read size_bytes before downloading. The ZIP carries both English and French metadata, so
    `lang` has no effect. Keywords: StatCan, delta file, bulk update, daily
    update, all tables, full refresh, changed data, download.
    Mots-clés : Statistique Canada, fichier delta, mise à jour en bloc, mise
    à jour quotidienne, tous les tableaux, actualisation complète, données
    modifiées, téléchargement.
    """
    del lang
    return await client.get_file_link(date)


@tool
async def statcan_delta_list_tables(
    date: str,
    product_id: int | None = None,
    query: str | None = None,
    detail: bool = False,
    max_tables: int = 200,
    lang: Lang = "en",
) -> DeltaTableList:
    """List the cubes released or changed in one day's Delta File, reading
    only its metadata by range requests.

    Use for: "what was published on this date", checking whether a cube
    changed that day before fetching it, release-day monitoring. Each
    entry: productId, CANSIM number, English and French titles, frequency,
    release time, series count, archive status, corrections and
    dimensions (with members and correction notes when `detail` is True and
    `product_id` is given). Cheap even for the 3.9 GB day: about 1 MB is
    fetched. date is "YYYY-MM-DD", a business day among the roughly 47
    kept (statcan_delta_list_files shows which). `query` filters by a word
    in either title. Rows are read with statcan_delta_read_table. The list
    is not WDS getChangedCubeList for the same date: WDS lists the cubes
    whose releaseTime falls on that date, while a day's file holds every
    cube processed since the previous file (built before 8:30 ET), with its
    own releaseTime. So a release after 8:30 lands in the next business
    day's file (42100107, released 2026-09-29 at 14:20, is in the 20261001
    file with that releaseTime: 51 tables against WDS's 50; it was also in
    the 20260929 file marked 08:30), and metadata-only changes to old
    cubes keep their old releaseTime (four 2024-10-03 cubes in 20260925:
    23 against 19). Compare release_time with the date to tell them apart.
    Keywords: delta file, released today, what changed, changed cubes,
    release calendar, daily release, new cubes, cube metadata, corrections,
    product id.
    Mots-clés : fichier delta, publié aujourd'hui, quoi de neuf, tableaux
    modifiés, calendrier de diffusion, diffusion quotidienne, nouveaux
    tableaux, métadonnées de tableau, corrections, numéro de tableau.
    """
    return await archive.list_tables(
        date,
        product_id=product_id,
        query=query,
        detail=detail,
        max_tables=max_tables,
        lang=lang,
    )


@tool
async def statcan_delta_read_table(
    date: str,
    product_id: int,
    vector_ids: list[int] | None = None,
    max_rows: int = 1000,
    lang: Lang = "en",
) -> DeltaTableData:
    """Read the data points one cube received in one day's Delta File,
    streaming only as much of the zip as needed (never the whole file).

    Use for: the exact values released or revised for one productId on one
    date, checking a release-day revision, pulling a handful of vectors
    from a large update. Rows carry vectorId, coordinate, reference
    period, value, symbol/status/security/scalar-factor/frequency codes
    (decoded in `legend` from the file's codeSet.xml) and release time.
    Values are raw: the scalar factor is not applied. Rows are never
    deleted; a correction arrives in the next day's file. The CSV is
    sorted by productId and must be inflated from its start, so a cube
    early in a big file is quick, and one deep in a multi-gigabyte file
    (20261001: 3.9 GB) takes several calls: each call reads up to 400 MB
    or 75 s (about 5 MB/s), then errors with how far it got and saves
    resume points, so calling again with the same arguments continues
    from there. Once a day's file has been scanned past a table, later
    reads of it on this server start next to it (scan_started_at_byte).
    For a single deep table, wds_get_changed_series_data or
    wds_get_full_table_download is faster. block_complete is False when
    the ceiling stopped inside the table's own rows. `vector_ids` keeps
    only those series; `max_rows` (1 to 10,000) caps the answer. date is
    "YYYY-MM-DD"; the productId must be in statcan_delta_list_tables for
    that date.
    Keywords: delta file, revisions, changed data points, vector values,
    release day, bulk update, symbol status codes, scalar factor, delta
    rows.
    Mots-clés : fichier delta, révisions, points de données modifiés,
    valeurs de vecteur, jour de diffusion, mise à jour en bloc, codes de
    symbole et de statut, facteur d'échelle, lignes delta.
    """
    return await archive.read_table(
        date, product_id, vector_ids=vector_ids, max_rows=max_rows, lang=lang
    )


@tool
async def statcan_delta_list_files(
    date: str | None = None, include_sizes: bool = False, lang: Lang = "en"
) -> DeltaFileList:
    """List the Delta Files kept (about 47 business days), from StatCan's
    Delta File page, and say why a given date has none.

    Use for: which dates can be read, the newest release, retention, and
    "is there a file for 2026-09-30?" (`date`): the answer is available,
    no release that day (weekend or holiday), past retention, or not yet
    published. `include_sizes` adds a HEAD request per file for size,
    ETag and Last-Modified (about 46 requests). Files appear on business
    days about 8:30 ET; the page's own user guide says 5 releases, which is
    out of date. Then use statcan_delta_list_tables or
    statcan_delta_read_table with a listed date.
    Keywords: delta file, available dates, retention, release schedule,
    holidays, business days, file sizes, etag, last modified, archive.
    Mots-clés : fichier delta, dates disponibles, période de conservation,
    calendrier de diffusion, jours fériés, jours ouvrables, taille des
    fichiers, date de modification, archives.
    """
    return await archive.list_files(date=date, include_sizes=include_sizes, lang=lang)


@tool
async def statcan_delta_list_real_time_tables(
    query: str | None = None, lang: Lang = "en"
) -> RealTimeTableList:
    """List StatCan's 19 real-time (vintage) cubes, each paired with its
    regular cube, to find the revision history of a statistic.

    Use for: how a figure was revised over time, "what did it say when
    first released", vintage analysis and evaluating projections. A regular
    cube always shows the latest revision; its real-time twin adds a
    release-date (vintage) dimension, published about a week later.
    Returns both product ids and titles in English and French; `query`
    filters by a word or a product id. Three of the 19 are listed by
    StatCan but not served by WDS (flagged wds_available False). Read the
    cube itself with wds_get_cube_metadata, wds_get_data_from_cube_coord or
    wds_get_full_table_download.
    Keywords: real-time tables, vintage, revision history, data revisions,
    historical releases, first release, real time data, revisions,
    vintages of releases.
    Mots-clés : tableaux en temps réel, versions, historique des révisions,
    révisions de données, diffusions historiques, première diffusion,
    données en temps réel, versions de diffusions.
    """
    del lang
    return realtime.list_real_time_tables(query)

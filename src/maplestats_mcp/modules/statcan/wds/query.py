"""One read-only SQL query over fetched WDS observations (wds_query_series).

An assistant asked for an annual average, a sum or a ranking over a few
series otherwise receives every observation and does the arithmetic in its
head, which is slow, costs context, and goes wrong. Here the server fetches
the observations with the same client functions as the WDS data tools, loads
them into a DuckDB table named `obs`, runs one SELECT, and returns only its
result. The idea comes from other Canadian data servers (mcp-statcan's
query_sdmx, CanData's use of DuckDB); this is MapleStats' own implementation.

The query is sandboxed, each rule checked by hand against duckdb 2.0.0:

- One statement, of type SELECT (WITH ... SELECT, FROM-first and DESCRIBE
  parse as SELECT): duckdb.extract_statements classifies DROP, INSERT, COPY,
  ATTACH, SET, PRAGMA and the rest, so no keyword list is needed.
- A fresh in-memory connection per call. After `obs` is loaded,
  enable_external_access=false makes read_csv, read_text, glob, 'https://...'
  and 's3://...' raise PermissionException, extension autoload/autoinstall are
  off (LOAD httpfs raises), and lock_configuration=true stops a statement from
  turning any of it back on.
- The query runs in a worker thread and is interrupted after
  query_time_limit() seconds, so a runaway cross join cannot hold the server.
- At most QUERY_ROW_CAP rows are read back.
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import anyio

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.wds import client, constants, context
from maplestats_mcp.modules.statcan.wds.schemas import (
    QueryCell,
    QuerySeries,
    SeriesQueryResult,
    VectorDataSet,
    VectorSeries,
)
from maplestats_mcp.shared import duck
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.limits import join_limits

# (name, DuckDB type, description). The order is the table's column order.
OBS_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("vector_id", "BIGINT", "StatCan vector id, without the v"),
    ("product_id", "BIGINT", "8-digit table productId"),
    ("table_id", "VARCHAR", "table number, e.g. 18-10-0004-01"),
    ("coordinate", "VARCHAR", "member ids by dimension"),
    ("ref_period", "DATE", "reference period (first day of the month, quarter or year)"),
    ("value", "DOUBLE", "value as published, unscaled; null when suppressed"),
    ("scale_multiplier", "BIGINT", "multiply value by this for the full figure"),
    ("decimals", "INTEGER", "decimals StatCan publishes"),
    ("status", "VARCHAR", "status code text, e.g. 'use with caution'"),
    ("symbol", "VARCHAR", "symbol code text, e.g. 'preliminary'"),
    ("release_time", "TIMESTAMP", "when the value was released (UTC)"),
    ("series_title", "VARCHAR", "StatCan's series title"),
    ("table_title", "VARCHAR", "table title"),
    ("unit", "VARCHAR", "unit of measure, e.g. 'Percent', '2002=100'"),
    ("scale", "VARCHAR", "scalar factor text, e.g. 'thousands'"),
    ("frequency", "VARCHAR", "e.g. 'Monthly'"),
    ("geography", "VARCHAR", "Geography member, when the table has one"),
)

OBS_COLUMN_NAMES = ", ".join(name for name, _, _ in OBS_COLUMNS)

_EXAMPLE = (
    "SELECT vector_id, year(ref_period) AS year, avg(value) AS annual_average "
    "FROM obs GROUP BY ALL ORDER BY vector_id, year"
)

# Applied after `obs` is loaded and before the caller's SQL runs. The lock
# must come last: once set, no statement can change a setting.
_SANDBOX = (
    "SET enable_progress_bar = false",
    "SET autoinstall_known_extensions = false",
    "SET autoload_known_extensions = false",
    "SET allow_community_extensions = false",
    "SET enable_external_access = false",
    "SET lock_configuration = true",
)


def query_time_limit() -> float:
    """Seconds the SQL may run, kept well inside the server's tool timeout.

    The fetch before it shares the same tool deadline, so the query gets at
    most QUERY_MAX_SECONDS and never more than the tool timeout less 30 s
    (the margin statcan_delta's scan uses too).
    """
    return min(constants.QUERY_MAX_SECONDS, max(1.0, config.get_tool_timeout_seconds() - 30.0))


def _fix_hint() -> str:
    return client._m(
        f"Query the table `obs`, whose columns are: {OBS_COLUMN_NAMES}. Example: {_EXAMPLE}",
        f"Interrogez la table `obs`, dont les colonnes sont : {OBS_COLUMN_NAMES}. "
        f"Exemple : {_EXAMPLE}",
    )


def check_sql(sql: str) -> str:
    """The SQL to run, or InvalidInput when it is not exactly one SELECT."""
    import duckdb

    text = (sql or "").strip()
    if not text:
        raise InvalidInput(
            client._m(
                f"sql must not be empty. {_fix_hint()}", f"sql ne doit pas être vide. {_fix_hint()}"
            )
        )
    if len(text) > constants.QUERY_MAX_SQL_CHARS:
        raise InvalidInput(
            client._m(
                f"sql is {len(text)} characters; the limit is {constants.QUERY_MAX_SQL_CHARS}.",
                f"sql compte {len(text)} caractères ; la limite est "
                f"{constants.QUERY_MAX_SQL_CHARS}.",
            )
        )
    allowed = client._m(
        "Only one read-only query is allowed: a single SELECT, or WITH ... SELECT, over `obs`.",
        "Une seule requête en lecture est permise : un SELECT, ou WITH ... SELECT, sur `obs`.",
    )
    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as exc:
        raise InvalidInput(
            client._m(
                f"The SQL does not parse: {exc}. {_fix_hint()}",
                f"Le SQL n'est pas valide : {exc}. {_fix_hint()}",
            )
        ) from exc
    if len(statements) != 1:
        raise InvalidInput(
            client._m(
                f"sql holds {len(statements)} statements. {allowed}",
                f"sql contient {len(statements)} instructions. {allowed}",
            )
        )
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        name = str(getattr(kind, "name", kind))
        raise InvalidInput(
            client._m(
                f"sql is a {name} statement. {allowed} No DROP, INSERT, UPDATE, COPY, ATTACH, "
                "SET, PRAGMA or other statement runs.",
                f"sql est une instruction {name}. {allowed} Aucun DROP, INSERT, UPDATE, COPY, "
                "ATTACH, SET, PRAGMA ni autre instruction ne s'exécute.",
            )
        )
    return text


def citation(series: VectorSeries) -> str:
    """The context's ready-made citation when it has one, else table and vector."""
    ctx = series.context
    ready = getattr(ctx, "citation", None) if ctx is not None else None
    if isinstance(ready, str) and ready:
        return ready
    number = context.table_number(series.product_id)
    title = ctx.table_title if ctx is not None else None
    return client._m(
        f"Statistics Canada. Table {number}"
        + (f", {title}" if title else "")
        + f". Vector v{series.vector_id}.",
        f"Statistique Canada. Tableau {number}"
        + (f", {title}" if title else "")
        + f". Vecteur v{series.vector_id}.",
    )


def _columns(series: list[VectorSeries]) -> list[list[Any]]:
    """`obs` as one list per column, in OBS_COLUMNS order."""
    columns: list[list[Any]] = [[] for _ in OBS_COLUMNS]
    for s in series:
        ctx = s.context
        table_id = ctx.table_id if ctx else context.table_number(s.product_id)
        for o in s.observations:
            release = o.release_time.replace(tzinfo=None) if o.release_time else None
            row = (
                s.vector_id,
                s.product_id,
                table_id,
                s.coordinate,
                o.ref_period,
                o.value,
                o.scale_multiplier,
                o.decimals,
                o.status,
                o.symbol,
                release,
                ctx.series_title if ctx else None,
                ctx.table_title if ctx else None,
                ctx.unit if ctx else None,
                ctx.scale if ctx else None,
                ctx.frequency if ctx else None,
                ctx.geography if ctx else None,
            )
            for column, value in zip(columns, row, strict=True):
                column.append(value)
    return columns


def _cell(value: Any) -> QueryCell:
    """A JSON-safe cell: dates as ISO text, decimals as floats, NaN as null."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _run(
    series: list[VectorSeries], sql: str, row_cap: int, seconds: float
) -> tuple[list[str], list[str], list[list[QueryCell]], bool]:
    """Load `obs`, lock the connection down, run `sql`; blocking, so run it in a thread."""
    import duckdb

    with duck.connect() as connection:
        schema = ", ".join(f"{name} {kind}" for name, kind, _ in OBS_COLUMNS)
        connection.execute(f"CREATE TABLE obs ({schema})")
        # One INSERT of unnested column lists: executemany took 53 s for 30,000
        # rows (duckdb 2.0.0, 2026-11-03), this takes 0.1 s.
        unnest = ", ".join(
            f"unnest(${i + 1}::{kind}[])" for i, (_, kind, _) in enumerate(OBS_COLUMNS)
        )
        connection.execute(f"INSERT INTO obs SELECT {unnest}", _columns(series))
        for statement in _SANDBOX:
            connection.execute(statement)
        timer = threading.Timer(seconds, connection.interrupt)
        timer.start()
        try:
            cursor = connection.execute(sql)
            fetched = cursor.fetchmany(row_cap + 1)
            description = cursor.description or []
        except duckdb.InterruptException as exc:
            raise InvalidInput(
                client._m(
                    f"The SQL ran past the {seconds:.0f} s limit and was stopped. Aggregate "
                    "earlier, avoid cross joins, or narrow the vectors or periods.",
                    f"Le SQL a dépassé la limite de {seconds:.0f} s et a été arrêté. Agrégez "
                    "plus tôt, évitez les produits cartésiens, ou réduisez vecteurs ou périodes.",
                )
            ) from exc
        except duckdb.PermissionException as exc:
            raise InvalidInput(
                client._m(
                    f"The SQL tried to reach a file, URL or extension, which is disabled: {exc}. "
                    f"Only the table `obs` can be read. {_fix_hint()}",
                    f"Le SQL a tenté d'accéder à un fichier, une URL ou une extension, ce qui est "
                    f"désactivé : {exc}. Seule la table `obs` est lisible. {_fix_hint()}",
                )
            ) from exc
        except duckdb.Error as exc:
            raise InvalidInput(
                client._m(
                    f"The SQL failed in DuckDB: {exc}. {_fix_hint()}",
                    f"Le SQL a échoué dans DuckDB : {exc}. {_fix_hint()}",
                )
            ) from exc
        finally:
            timer.cancel()
    names = [str(d[0]) for d in description]
    types = [str(d[1]) for d in description]
    truncated = len(fetched) > row_cap
    rows = [[_cell(v) for v in row] for row in fetched[:row_cap]]
    return names, types, rows, truncated


async def query_series(
    vector_ids: list[int],
    sql: str,
    *,
    start_ref_period: str | None = None,
    end_ref_period: str | None = None,
    latest_n: int | None = None,
) -> SeriesQueryResult:
    """Fetch the vectors' observations, run `sql` over them as `obs`, return the result."""
    text = check_sql(sql)
    ids = list(dict.fromkeys(vector_ids))
    if not ids:
        raise InvalidInput(
            client._m("vector_ids must not be empty.", "vector_ids ne doit pas être vide.")
        )
    if len(ids) > constants.QUERY_MAX_VECTORS:
        raise InvalidInput(
            client._m(
                f"{len(ids)} vectors asked for; the limit is {constants.QUERY_MAX_VECTORS}. For "
                "a whole table use wds_get_full_table_download.",
                f"{len(ids)} vecteurs demandés ; la limite est {constants.QUERY_MAX_VECTORS}. "
                "Pour un tableau entier, utilisez wds_get_full_table_download.",
            )
        )
    has_range = start_ref_period is not None or end_ref_period is not None
    if has_range and (start_ref_period is None or end_ref_period is None):
        raise InvalidInput(
            client._m(
                "Pass both start_ref_period and end_ref_period, or neither (then latest_n).",
                "Passez start_ref_period et end_ref_period ensemble, ou aucun des deux "
                "(alors latest_n).",
            )
        )
    if has_range and latest_n is not None:
        raise InvalidInput(
            client._m(
                "Pass either start_ref_period/end_ref_period or latest_n, not both.",
                "Passez start_ref_period/end_ref_period ou latest_n, pas les deux.",
            )
        )
    if has_range:
        assert start_ref_period is not None and end_ref_period is not None
        data: VectorDataSet = await client.get_data_from_vector_by_reference_period_range(
            ids, start_ref_period, end_ref_period
        )
        window = f"{start_ref_period} to {end_ref_period}"
    else:
        n = 12 if latest_n is None else latest_n
        if not 1 <= n <= constants.QUERY_MAX_LATEST_N:
            raise InvalidInput(
                client._m(
                    f"latest_n must be between 1 and {constants.QUERY_MAX_LATEST_N}, got {n}.",
                    f"latest_n doit être entre 1 et {constants.QUERY_MAX_LATEST_N}, reçu {n}.",
                )
            )
        data = await client.get_data_from_vectors_and_latest_n_periods(ids, n)
        window = f"latest {n} periods"
    described, context_note = await context.describe(list(data.series))
    seconds = query_time_limit()
    row_cap = constants.QUERY_ROW_CAP
    names, types, rows, truncated = await anyio.to_thread.run_sync(
        _run, described, text, row_cap, seconds
    )
    input_rows = sum(len(s.observations) for s in described)
    cap_note = client._m(
        f"result rows capped at {row_cap}"
        + (" (more were returned and cut)" if truncated else "")
        + f"; query time limit {seconds:.0f} s; at most {constants.QUERY_MAX_VECTORS} vectors; "
        "SQL is read-only (one SELECT) with no file, network or extension access",
        f"résultat limité à {row_cap} lignes"
        + (" (d'autres ont été coupées)" if truncated else "")
        + f" ; durée maximale de la requête {seconds:.0f} s ; au plus "
        f"{constants.QUERY_MAX_VECTORS} vecteurs ; SQL en lecture seule (un SELECT), sans "
        "accès aux fichiers, au réseau ni aux extensions",
    )
    provenance = make_provenance(
        source="statcan-wds",
        url=data.provenance.url,
        cached=data.provenance.cached,
        schema_name="statcan.wds.SeriesQueryResult",
        coverage=client._m(
            f"{input_rows} observations of {len(described)} series ({window}) loaded into obs",
            f"{input_rows} observations de {len(described)} séries ({window}) chargées dans obs",
        ),
        limits=join_limits(cap_note, data.provenance.limits, context_note),
        lang=client._LANG.get(),
    )
    return SeriesQueryResult(
        sql=text,
        columns=names,
        column_types=types,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        input_rows=input_rows,
        series=[
            QuerySeries(
                vector_id=s.vector_id,
                product_id=s.product_id,
                coordinate=s.coordinate,
                observation_count=len(s.observations),
                citation=citation(s),
                context=s.context,
            )
            for s in described
        ],
        failed=data.failed,
        provenance=provenance,
    )

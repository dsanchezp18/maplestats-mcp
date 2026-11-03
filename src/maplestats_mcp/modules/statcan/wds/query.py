"""One read-only SQL query over fetched WDS observations (wds_query_series).

An assistant asked for an annual average, a sum or a ranking over a few
series otherwise receives every observation and does the arithmetic in its
head, which is slow, costs context, and goes wrong. Here the server fetches
the observations with the same client functions as the WDS data tools, loads
them into a DuckDB table named `obs`, runs one SELECT, and returns only its
result. The idea comes from other Canadian data servers (mcp-statcan's
query_sdmx, CanData's use of DuckDB); this is MapleStats' own implementation.

The query is sandboxed, each rule checked by hand against duckdb 2.0.0:

- One statement, a pure SELECT (WITH ... SELECT, FROM-first and DESCRIBE
  parse as SELECT), classified on a locked connection: extract_statements
  names DROP, INSERT, COPY, ATTACH, SET, PRAGMA and the rest, and a walk of
  json_serialize_sql's tree rejects a SELECT holding a data-modifying CTE
  (`WITH x AS (DELETE FROM obs RETURNING *) SELECT ...`), which
  extract_statements calls a SELECT.
- It runs in a child process (shared/duck_sandbox.py, shared/duck_worker.py):
  one thread, an address-space cap (Linux), killed at query_time_limit() plus
  a startup allowance. In-process, DuckDB's memory_limit did not bound scalar
  functions (`SELECT len(range(1000000000))` had the server killed) and the
  interrupt did not stop them.
- The child's connection has no file, network or extension access and its
  configuration is locked, and it cannot spill to disk.
- At most QUERY_ROW_CAP rows, QUERY_MAX_RESULT_CHARS characters of rows, and
  QUERY_MAX_CELL_CHARS characters in one text cell come back.
- DuckDB's messages are cut to their first line, with file paths removed.
"""

from __future__ import annotations

from typing import Any

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.wds import client, constants, context
from maplestats_mcp.modules.statcan.wds.schemas import (
    QueryCell,
    QuerySeries,
    SeriesQueryResult,
    VectorDataSet,
    VectorSeries,
)
from maplestats_mcp.shared import duck_sandbox
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
    """The SQL to run, or InvalidInput when it is not exactly one pure SELECT."""
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
    problem = duck_sandbox.select_problem(text)
    if problem is not None:
        raise InvalidInput(_problem_message(*problem))
    return text


def _problem_message(kind: str, detail: str) -> str:
    allowed = client._m(
        "Only one read-only query is allowed: a single SELECT, or WITH ... SELECT, over `obs`.",
        "Une seule requête en lecture est permise : un SELECT, ou WITH ... SELECT, sur `obs`.",
    )
    if kind == "parse":
        return client._m(
            f"The SQL does not parse: {detail}. {_fix_hint()}",
            f"Le SQL n'est pas valide : {detail}. {_fix_hint()}",
        )
    if kind == "count":
        return client._m(
            f"sql holds {detail} statements. {allowed}",
            f"sql contient {detail} instructions. {allowed}",
        )
    if kind == "modifying":
        return client._m(
            f"sql changes data: it holds a data-modifying {detail} statement (in a WITH clause or subquery). "
            f"{allowed} "
            "Remove the INSERT, UPDATE, DELETE or MERGE and select from `obs` instead.",
            f"sql modifie des données : il contient une instruction {detail} (dans une clause "
            f"WITH ou une sous-requête). {allowed} Retirez l'INSERT, l'UPDATE, le DELETE ou le MERGE et "
            "sélectionnez plutôt dans `obs`.",
        )
    return client._m(
        f"sql is a {detail} statement. {allowed} No DROP, INSERT, UPDATE, COPY, ATTACH, "
        "SET, PRAGMA or other statement runs.",
        f"sql est une instruction {detail}. {allowed} Aucun DROP, INSERT, UPDATE, COPY, "
        "ATTACH, SET, PRAGMA ni autre instruction ne s'exécute.",
    )


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


def _sandbox_error(error: duck_sandbox.SandboxError, seconds: float) -> InvalidInput:
    """The child's failure as an InvalidInput that says what to change."""
    kind, detail = error.kind, error.detail
    memory_mb = config.get_query_memory_mb()
    if kind == "timeout":
        return InvalidInput(
            client._m(
                f"The SQL ran past the {seconds:.0f} s limit and was stopped. Aggregate "
                "earlier, avoid cross joins, or narrow the vectors or periods.",
                f"Le SQL a dépassé la limite de {seconds:.0f} s et a été arrêté. Agrégez "
                "plus tôt, évitez les produits cartésiens, ou réduisez vecteurs ou périodes.",
            )
        )
    if kind in ("memory", "crashed"):
        return InvalidInput(
            client._m(
                f"The SQL needed more than the {memory_mb} MB a query may use and was stopped. "
                "Do not build large lists or strings (range(), repeat(), list aggregates over "
                "big inputs); aggregate the rows of `obs` instead.",
                f"Le SQL a demandé plus que les {memory_mb} Mo permis à une requête et a été "
                "arrêté. Ne construisez pas de grandes listes ni de longues chaînes (range(), "
                "repeat(), agrégats de listes sur de gros volumes) ; agrégez plutôt les lignes "
                "de `obs`.",
            )
        )
    if kind == "too_large":
        limit = constants.QUERY_MAX_RESULT_CHARS
        limit_fr = f"{limit:,}".replace(",", " ")
        return InvalidInput(
            client._m(
                f"The result passed {limit:,} characters and was stopped. Select fewer or "
                "shorter columns, aggregate, or add a LIMIT.",
                f"Le résultat a dépassé {limit_fr} caractères et a été arrêté. Sélectionnez "
                "moins de colonnes ou des colonnes plus courtes, agrégez, ou ajoutez un LIMIT.",
            )
        )
    if kind == "cell_too_large":
        limit = constants.QUERY_MAX_CELL_CHARS
        return InvalidInput(
            client._m(
                f"Column {detail!r} holds a value longer than {limit} characters. Return "
                "shorter values: aggregate to numbers, or cut text with left(x, n).",
                f"La colonne {detail!r} contient une valeur de plus de {limit} caractères. "
                "Renvoyez des valeurs plus courtes : agrégez en nombres, ou coupez le texte "
                "avec left(x, n).",
            )
        )
    if kind == "permission":
        return InvalidInput(
            client._m(
                f"The SQL tried to reach a file, URL or extension, which is disabled: {detail}. "
                f"Only the table `obs` can be read. {_fix_hint()}",
                f"Le SQL a tenté d'accéder à un fichier, une URL ou une extension, ce qui est "
                f"désactivé : {detail}. Seule la table `obs` est lisible. {_fix_hint()}",
            )
        )
    if kind == "statement":
        problem, _, what = detail.partition(": ")
        return InvalidInput(_problem_message(problem, what))
    if kind == "sql":
        return InvalidInput(
            client._m(
                f"The SQL failed in DuckDB: {detail}. {_fix_hint()}",
                f"Le SQL a échoué dans DuckDB : {detail}. {_fix_hint()}",
            )
        )
    return InvalidInput(
        client._m(
            f"The query process failed ({kind}: {detail}). Retry once; if it fails again, "
            "simplify the SQL.",
            f"Le processus de requête a échoué ({kind} : {detail}). Réessayez une fois ; en "
            "cas de nouvel échec, simplifiez le SQL.",
        )
    )


async def _run(
    series: list[VectorSeries], sql: str, row_cap: int, seconds: float
) -> tuple[list[str], list[str], list[list[QueryCell]], bool]:
    """Load `obs` and run `sql` in a capped child process (shared/duck_sandbox.py)."""
    table = duck_sandbox.Table(
        name="obs",
        columns=[(name, kind) for name, kind, _ in OBS_COLUMNS],
        values=_columns(series),
    )
    try:
        result = await duck_sandbox.run_query(
            [table],
            sql,
            seconds=seconds,
            row_cap=row_cap,
            max_chars=constants.QUERY_MAX_RESULT_CHARS,
            max_cell_chars=constants.QUERY_MAX_CELL_CHARS,
        )
    except duck_sandbox.SandboxError as exc:
        raise _sandbox_error(exc, seconds) from exc
    return result.columns, result.types, result.rows, result.truncated


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
    names, types, rows, truncated = await _run(described, text, row_cap, seconds)
    input_rows = sum(len(s.observations) for s in described)
    cap_note = client._m(
        f"result rows capped at {row_cap}"
        + (" (more were returned and cut)" if truncated else "")
        + f" and {constants.QUERY_MAX_RESULT_CHARS:,} characters; query time limit "
        f"{seconds:.0f} s and memory {config.get_query_memory_mb()} MB; at most "
        f"{constants.QUERY_MAX_VECTORS} vectors; SQL is read-only (one SELECT) with no file, "
        "network or extension access",
        f"résultat limité à {row_cap} lignes"
        + (" (d'autres ont été coupées)" if truncated else "")
        + f" et {constants.QUERY_MAX_RESULT_CHARS:,} caractères".replace(",", " ")
        + f" ; durée maximale de la requête {seconds:.0f} s et mémoire "
        f"{config.get_query_memory_mb()} Mo ; au plus "
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

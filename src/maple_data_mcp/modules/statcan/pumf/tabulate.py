"""Weighted tables from PUMF microdata, computed server-side with DuckDB.

The data file is downloaded once into config.get_pumf_cache_dir() and
extracted from its ZIP; later calls reuse it. A download that outlives
the tool timeout keeps running in the background (asyncio.shield), so a
retry finds it finished rather than starting over.

CSV members are read as text with a header; fixed-width members (.dat,
.txt) are read one line per row and sliced with the codebook's column
positions. Everything is read as VARCHAR and cast explicitly, so a code
like "02" and the number 2 compare correctly.

Standard errors are not computed: each survey documents its own
replicate or bootstrap variance method, and none has been verified here
yet. Results say so and list the replicate weights found.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Literal

import duckdb

from maple_data_mcp import config
from maple_data_mcp.modules.statcan.pumf import client, constants
from maple_data_mcp.modules.statcan.pumf.schemas import (
    PumfVariable,
    TableCell,
    TableGroup,
    WeightedTable,
)
from maple_data_mcp.shared import remote_zip
from maple_data_mcp.shared.envelope import make_provenance
from maple_data_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maple_data_mcp.shared.http import new_client

Statistic = Literal["total", "share", "mean"]

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DATA_EXT = (".csv", ".dat", ".txt")
_NOT_DATA = ("bsw", "readme", "lisez", "layout", "frq", "codebook", "record", "_i.", "_o.")
_downloads: dict[str, asyncio.Task[Path]] = {}
_client = new_client(timeout=600.0, follow_redirects=True)


def _pick_member(
    members: list[remote_zip.ZipMember], data_file: str | None
) -> remote_zip.ZipMember:
    files = [m for m in members if not m.name.endswith("/")]
    if data_file:
        wanted = data_file.strip().lower()
        for member in files:
            if member.name.lower() == wanted or member.name.lower().endswith("/" + wanted):
                return member
        raise InvalidInput(f"No file {data_file!r} in the ZIP; see statcan_pumf_list_zip.")
    candidates = [
        m
        for m in files
        if m.name.lower().endswith(_DATA_EXT)
        and not any(marker in m.name.lower() for marker in _NOT_DATA)
        and m.size > 100_000
    ]
    csvs = [m for m in candidates if m.name.lower().endswith(".csv")]
    pool = csvs or candidates
    if len(pool) == 1:
        return pool[0]
    if not pool:
        raise NotFound(
            "No microdata file found in the ZIP; pass data_file (see statcan_pumf_list_zip)."
        )
    listing = ", ".join(f"{m.name} ({m.size / 1e6:.0f} MB)" for m in pool[:15])
    raise InvalidInput(f"The ZIP has several data files; pass data_file as one of: {listing}")


def _enforce_cache_cap(root: Path, keep: Path) -> None:
    files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= config.get_pumf_cache_max_bytes():
            break
        if path != keep:
            total -= path.stat().st_size
            path.unlink(missing_ok=True)


async def _download(url: str, member: remote_zip.ZipMember, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    zip_path = target.parent / "archive.zip.part"
    try:
        async with _client.stream("GET", url) as response:
            response.raise_for_status()
            with zip_path.open("wb") as handle:
                async for chunk in response.aiter_bytes(1 << 20):
                    handle.write(chunk)
    except Exception as exc:
        zip_path.unlink(missing_ok=True)
        raise UpstreamUnavailable(f"statcan_pumf: download of {url} failed: {exc}") from exc

    def extract() -> None:
        part = target.with_suffix(target.suffix + ".part")
        with (
            zipfile.ZipFile(zip_path) as archive,
            archive.open(member.name) as source,
            part.open("wb") as sink,
        ):
            shutil.copyfileobj(source, sink, 1 << 20)
        target.with_suffix(target.suffix + ".part").replace(target)
        zip_path.unlink(missing_ok=True)
        _enforce_cache_cap(config.get_pumf_cache_dir(), target)

    await asyncio.to_thread(extract)
    return target


async def local_data_file(url: str, member: remote_zip.ZipMember) -> Path:
    key = hashlib.sha1(f"{url}|{member.name}".encode()).hexdigest()[:16]
    target = config.get_pumf_cache_dir() / key / Path(member.name).name
    if target.exists():
        target.touch()
        return target
    task = _downloads.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_download(url, member, target))
        _downloads[key] = task
    # shield: if the tool call times out, the download still finishes for a retry.
    return await asyncio.shield(task)


def _labels(variable: PumfVariable) -> dict[str, str]:
    labels: dict[str, str] = {}
    for value in variable.values:
        labels[value.code] = value.label
        try:
            labels[str(int(float(value.code)))] = value.label
        except ValueError:
            pass
    return labels


def _run_query(
    path: Path,
    fixed_width: bool,
    columns: dict[str, PumfVariable],
    group_by: list[str],
    weight: str,
    statistic: Statistic,
    value_variable: str | None,
    filters: dict[str, list[str]],
) -> tuple[list[tuple[Any, ...]], int, float]:
    def column(name: str) -> str:
        if fixed_width:
            var = columns[name]
            return f"TRIM(SUBSTR(line, {int(var.position or 0)}, {int(var.width or 0)}))"
        return f'TRIM("{name}")'

    literal = "'" + str(path).replace("'", "''") + "'"
    source = (
        # One VARCHAR column per line: \x01 never occurs in StatCan's text files.
        f"read_csv({literal}, header = false, columns = {{'line': 'VARCHAR'}}, "
        "delim = '\x01', quote = '', escape = '', auto_detect = false)"
        if fixed_width
        else f"read_csv({literal}, header = true, all_varchar = true, sample_size = -1)"
    )
    where: list[str] = []
    params: list[Any] = []
    for name, codes in filters.items():
        numeric = all(re.fullmatch(r"-?\d+(\.\d+)?", c.strip()) for c in codes)
        placeholders = ", ".join("?" for _ in codes)
        if numeric:
            where.append(f"TRY_CAST({column(name)} AS DOUBLE) IN ({placeholders})")
            params.extend(float(c) for c in codes)
        else:
            where.append(f"{column(name)} IN ({placeholders})")
            params.extend(c.strip() for c in codes)
    weight_expr = f"TRY_CAST({column(weight)} AS DOUBLE)"
    groups = [f"{column(name)} AS g{i}" for i, name in enumerate(group_by)]
    if statistic == "mean" and value_variable:
        value_expr = f"TRY_CAST({column(value_variable)} AS DOUBLE)"
        where.append(f"{value_expr} IS NOT NULL")
        estimate = f"SUM({weight_expr} * {value_expr}) / NULLIF(SUM({weight_expr}), 0)"
    else:
        estimate = f"SUM({weight_expr})"
    group_list = ", ".join(f"g{i}" for i in range(len(group_by)))
    sql = (
        f"SELECT {', '.join(groups + [estimate + ' AS estimate', 'COUNT(*) AS n'])} "
        f"FROM {source} "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + (f"GROUP BY {group_list} ORDER BY {group_list}" if group_by else "")
    )
    totals_sql = f"SELECT COUNT(*), SUM({weight_expr}) FROM {source}" + (
        f" WHERE {' AND '.join(where)}" if where else ""
    )
    with duckdb.connect() as connection:
        rows = connection.execute(sql, params).fetchall()
        total_n, total_weight = connection.execute(totals_sql, params).fetchone() or (0, 0.0)
    return rows, int(total_n or 0), float(total_weight or 0.0)


async def tabulate(
    url: str,
    *,
    rows: list[str],
    statistic: Statistic = "total",
    value_variable: str | None = None,
    filters: dict[str, list[str]] | None = None,
    weight: str | None = None,
    data_file: str | None = None,
    min_count: int = 30,
    lang: str = "en",
) -> WeightedTable:
    if len(rows) > 3:
        raise InvalidInput("Group by at most 3 variables.")
    if statistic == "mean" and not value_variable:
        raise InvalidInput("statistic 'mean' needs value_variable.")
    variables, _, _ = await client.load_codebook(url, lang)
    by_name = {v.name: v for v in variables}
    weights = client.weight_names(variables)
    chosen_weight = (weight or next((w for w in weights if not re.search(r"\d$", w)), "")).upper()
    if not chosen_weight:
        raise InvalidInput(f"No weight variable found; pass weight (candidates: {weights}).")
    wanted = [*rows, chosen_weight, *(filters or {}), *([value_variable] if value_variable else [])]
    for name in wanted:
        if not _NAME.match(name) or name.upper() not in by_name:
            raise InvalidInput(f"{name!r} is not a variable in this PUMF's codebook.")
    upper_rows = [r.upper() for r in rows]
    upper_filters = {k.upper(): [str(c) for c in v] for k, v in (filters or {}).items()}

    members, _, _ = await client._members(url)
    member = _pick_member(members, data_file)
    fixed_width = not member.name.lower().endswith(".csv")
    if fixed_width:
        missing = [
            n for n in wanted if not by_name[n.upper()].position or not by_name[n.upper()].width
        ]
        if missing:
            raise UpstreamError(f"The codebook gives no column positions for {missing}.")
    path = await local_data_file(url, member)

    result_rows, total_n, total_weight = await asyncio.to_thread(
        _run_query,
        path,
        fixed_width,
        by_name,
        upper_rows,
        chosen_weight,
        statistic,
        value_variable.upper() if value_variable else None,
        upper_filters,
    )
    labels = {name: _labels(by_name[name]) for name in upper_rows}
    cells: list[TableCell] = []
    # Shares are within each combination of all but the last grouping variable.
    parent_totals: dict[tuple[Any, ...], float] = {}
    if statistic == "share":
        for row in result_rows:
            key = tuple(row[: len(upper_rows) - 1])
            parent_totals[key] = parent_totals.get(key, 0.0) + float(row[-2] or 0.0)
    for row in result_rows[: constants.TABLE_ROWS_MAX]:
        codes = [str(c) if c is not None else "" for c in row[: len(upper_rows)]]
        estimate = float(row[-2]) if row[-2] is not None else None
        if statistic == "share" and estimate is not None:
            denominator = parent_totals.get(tuple(row[: len(upper_rows) - 1]), 0.0)
            estimate = 100 * estimate / denominator if denominator else None
        cells.append(
            TableCell(
                groups=[
                    TableGroup(variable=name, code=code, label=labels[name].get(code))
                    for name, code in zip(upper_rows, codes, strict=True)
                ],
                estimate=estimate,
                unweighted_n=int(row[-1]),
                low_count=int(row[-1]) < min_count,
            )
        )
    replicates = [w for w in weights if w != chosen_weight]
    return WeightedTable(
        url=url,
        data_file=member.name,
        statistic=statistic,
        weight=chosen_weight,
        value_variable=value_variable.upper() if value_variable else None,
        filters=upper_filters,
        cells=cells,
        truncated=len(result_rows) > constants.TABLE_ROWS_MAX,
        unweighted_n=total_n,
        weighted_total=total_weight,
        notes=[
            "Standard errors are not computed yet: use the survey's replicate/bootstrap "
            "weights and the variance method in its user guide"
            + (f" (replicate weights here: {', '.join(replicates[:5])}...)" if replicates else "")
            + ".",
            (
                f"Cells with fewer than {min_count} respondents are flagged low_count; StatCan "
                "guidelines usually suppress or qualify them."
            ),
            "Special codes (valid skip, don't know, not stated) are included unless filtered out.",
            (
                "Some variables carry implied decimals (LFS HRLYEARN is in cents); check the "
                "codebook or user guide before reporting means."
            ),
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_pumf.WeightedTable",
            limits="computed from the PUMF microdata by this server with DuckDB",
        ),
    )

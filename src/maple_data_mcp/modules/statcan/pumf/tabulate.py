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
import math
import re
import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb

from maple_data_mcp import config
from maple_data_mcp.modules.statcan.pumf import client, codebooks, constants
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


@dataclass(frozen=True)
class DataSource:
    """One file to read: a CSV with a header, or fixed-width lines."""

    path: Path
    fixed_width: bool
    columns: dict[str, PumfVariable]

    def relation(self) -> str:
        literal = "'" + str(self.path).replace("'", "''") + "'"
        if self.fixed_width:
            # One VARCHAR column per line: \x01 never occurs in StatCan's text files.
            return (
                f"read_csv({literal}, header = false, columns = {{'line': 'VARCHAR'}}, "
                "delim = '\x01', quote = '', escape = '', auto_detect = false)"
            )
        return f"read_csv({literal}, header = true, all_varchar = true, sample_size = -1)"

    def column(self, name: str) -> str:
        if self.fixed_width:
            var = self.columns[name]
            return f"TRIM(SUBSTR(line, {int(var.position or 0)}, {int(var.width or 0)}))"
        return f'TRIM("{name}")'

    def select(self, names: list[str]) -> str:
        columns = ", ".join(f'{self.column(n)} AS "{n}"' for n in names)
        return f"SELECT {columns} FROM {self.relation()}"


def _run_query(
    main: DataSource,
    group_by: list[str],
    weights: list[str],
    statistic: Statistic,
    value_variable: str | None,
    filters: dict[str, list[str]],
    replicates: DataSource | None = None,
    id_variable: str | None = None,
) -> tuple[list[tuple[Any, ...]], int, float]:
    """Rows of (group codes..., n, then numerator and denominator per weight).

    The numerator is SUM(w) for totals and shares, SUM(w * x) for means;
    the denominator is SUM(w) (used by means). weights[0] is the main
    weight; the rest are replicates, read from `replicates` (a separate
    bootstrap file joined on id_variable) when they are not in `main`.
    """
    from_main = [w for w in weights if w in main.columns or not replicates]
    from_replicates = [w for w in weights if w not in from_main]
    needed = list(
        dict.fromkeys(
            [*group_by, *filters, *([value_variable] if value_variable else []), *from_main]
        )
    )
    relation = (
        f"({main.select(needed + ([id_variable] if from_replicates and id_variable else []))}) AS m"
    )
    if from_replicates and replicates is not None and id_variable:
        relation += (
            f" JOIN ({replicates.select([id_variable, *from_replicates])}) AS r "
            f'ON m."{id_variable}" = r."{id_variable}"'
        )

    def col(name: str) -> str:
        return f'"{name}"' if name not in (id_variable,) else f'm."{name}"'

    where: list[str] = []
    params: list[Any] = []
    for name, codes in filters.items():
        numeric = all(re.fullmatch(r"-?\d+(\.\d+)?", c.strip()) for c in codes)
        placeholders = ", ".join("?" for _ in codes)
        if numeric:
            where.append(f"TRY_CAST({col(name)} AS DOUBLE) IN ({placeholders})")
            params.extend(float(c) for c in codes)
        else:
            where.append(f"{col(name)} IN ({placeholders})")
            params.extend(c.strip() for c in codes)
    groups = [f"{col(name)} AS g{i}" for i, name in enumerate(group_by)]
    value_expr = None
    if statistic == "mean" and value_variable:
        value_expr = f"TRY_CAST({col(value_variable)} AS DOUBLE)"
        where.append(f"{value_expr} IS NOT NULL")
    sums: list[str] = []
    for weight in weights:
        weight_expr = f"TRY_CAST({col(weight)} AS DOUBLE)"
        sums.append(f"SUM({weight_expr} * {value_expr})" if value_expr else f"SUM({weight_expr})")
        sums.append(f"SUM({weight_expr})")
    weight_expr = f"TRY_CAST({col(weights[0])} AS DOUBLE)"
    group_list = ", ".join(f"g{i}" for i in range(len(group_by)))
    condition = f"WHERE {' AND '.join(where)} " if where else ""
    sql = f"SELECT {', '.join([*groups, 'COUNT(*) AS n', *sums])} FROM {relation} {condition}" + (
        f"GROUP BY {group_list} ORDER BY {group_list}" if group_by else ""
    )
    totals_sql = f"SELECT COUNT(*), SUM({weight_expr}) FROM {relation} {condition}"
    # DuckDB draws a terminal progress bar on long queries, on by default
    # (seen 2026-09-24 on the 1,000-replicate joins); over the stdio transport
    # anything printed to stdout corrupts the MCP stream and drops the client.
    with duckdb.connect() as connection:
        connection.execute("SET enable_progress_bar = false")
        rows = connection.execute(sql, params).fetchall()
        total_n, total_weight = connection.execute(totals_sql, params).fetchone() or (0, 0.0)
    return rows, int(total_n or 0), float(total_weight or 0.0)


@dataclass(frozen=True)
class VarianceMethod:
    """A survey's documented replicate-weight variance formula."""

    url_marker: str
    main_weight: str
    replicates: tuple[str, ...]
    divisor: float
    # "mean": deviations from the replicates' mean (Census random groups);
    # "estimate": from the full-sample estimate (StatCan bootstrap guides).
    centre: Literal["mean", "estimate"]
    description: str
    replicate_file: str | None = None  # substring of the separate bootstrap file's name
    id_variable: str | None = None

    def standard_error(
        self, estimate: float | None, replicate_estimates: Sequence[float | None]
    ) -> float | None:
        values = [v for v in replicate_estimates if v is not None]
        if len(values) != len(self.replicates) or estimate is None:
            return None
        centre = sum(values) / len(values) if self.centre == "mean" else estimate
        return math.sqrt(sum((v - centre) ** 2 for v in values) / self.divisor)


_BOOTSTRAP_NOTE = (
    "The PUMF bootstrap weights are perturbed for confidentiality, so the standard error "
    "is comparable to, not the same as, StatCan's official one."
)

# Each entry is copied from the survey's own user guide; add a PUMF only
# after checking its guide, never by analogy with another survey.
VARIANCE_METHODS: tuple[VarianceMethod, ...] = (
    VarianceMethod(
        url_marker="cen21_ind_",
        main_weight="WEIGHT",
        replicates=tuple(f"WT{i}" for i in range(1, 17)),
        # "Divide the number obtained in (3) by 35": (240/35) * (1/240), a
        # Fay adjustment over 16 groups x 15 (2021 Census Individuals PUMF
        # User Guide, chapter 3, section C.2, checked 2026-09-24).
        divisor=35.0,
        centre="mean",
        description=(
            "dependent random groups with Fay adjustment (2021 Census Individuals PUMF User "
            "Guide, ch. 3, C.2): the estimate under each of WT1-WT16, then "
            "sqrt(sum of squared deviations from their mean / 35). StatCan notes it "
            "overestimates the error for small estimates."
        ),
    ),
    VarianceMethod(
        # EICS 2024 User Guide, section 10.1, equation (1), checked 2026-09-24.
        url_marker="/89m0025x/2022001/2024.zip",
        main_weight="WTPM",
        replicates=tuple(f"WRPM{i}" for i in range(1, 1001)),
        divisor=1000.0,
        centre="estimate",
        description=(
            "bootstrap (EICS 2024 User Guide, s. 10.1, eq. 1): the estimate under each of "
            "WRPM1-WRPM1000, then sqrt(sum of squared deviations from the full-sample "
            f"estimate / 1000). {_BOOTSTRAP_NOTE}"
        ),
        replicate_file="pumf_bsw.txt",
        id_variable="PUMFID",
    ),
    VarianceMethod(
        # CSWC 2024-2025 User Guide, section 10.1, equation (1), checked 2026-09-24.
        url_marker="/14-25-0001/2026001/2024-2025.zip",
        main_weight="CSWCWT",
        replicates=tuple(f"BSW{i}" for i in range(1, 1001)),
        divisor=1000.0,
        centre="estimate",
        description=(
            "bootstrap (CSWC 2024-2025 User Guide, s. 10.1, eq. 1): the estimate under each "
            "of BSW1-BSW1000, then sqrt(sum of squared deviations from the full-sample "
            f"estimate / 1000). {_BOOTSTRAP_NOTE}"
        ),
        replicate_file="pumf_bsw.txt",
        id_variable="PUMFID",
    ),
)


async def _replicate_source(
    url: str, members: list[remote_zip.ZipMember], file_marker: str
) -> DataSource:
    """The separate bootstrap-weight file, with its layout from its own .dct."""
    data = next((m for m in members if m.name.lower().endswith(file_marker)), None)
    layout = next(
        (m for m in members if "bsw" in m.name.lower() and m.name.lower().endswith(".dct")), None
    )
    if data is None or layout is None:
        raise NotFound(
            f"The bootstrap weight file ({file_marker}) or its layout is not in the ZIP."
        )
    dct = await remote_zip.read_member(url, layout)
    columns = codebooks.parse_stata_dct(dct.decode("cp1252", errors="replace"))
    path = await local_data_file(url, data)
    return DataSource(path, fixed_width=True, columns=columns)


def variance_method(url: str) -> VarianceMethod | None:
    return next((m for m in VARIANCE_METHODS if m.url_marker in url), None)


def _estimates(
    row: tuple[Any, ...], width: int, weight_count: int, statistic: Statistic
) -> list[float | None]:
    """One estimate per weight: totals and share numerators, or ratio means."""
    values: list[float | None] = []
    for i in range(weight_count):
        numerator, denominator = row[width + 1 + 2 * i], row[width + 2 + 2 * i]
        if numerator is None:
            values.append(None)
        elif statistic == "mean":
            values.append(float(numerator) / float(denominator) if denominator else None)
        else:
            values.append(float(numerator))
    return values


def _to_shares(
    rows: list[tuple[Any, ...]], estimates: list[list[float | None]], width: int
) -> list[list[float | None]]:
    """Percent within each combination of all but the last grouping variable, per weight."""
    parents: dict[tuple[Any, ...], list[float]] = {}
    for row, values in zip(rows, estimates, strict=True):
        totals = parents.setdefault(tuple(row[: width - 1]), [0.0] * len(values))
        for i, value in enumerate(values):
            totals[i] += value or 0.0
    shares: list[list[float | None]] = []
    for row, values in zip(rows, estimates, strict=True):
        totals = parents[tuple(row[: width - 1])]
        shares.append(
            [
                100 * v / t if v is not None and t else None
                for v, t in zip(values, totals, strict=True)
            ]
        )
    return shares


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
    chosen_weight = (weight or client.main_weight(variables) or "").upper()
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

    method = variance_method(url)
    if method and chosen_weight != method.main_weight:
        method = None
    all_weights = [chosen_weight, *(method.replicates if method else [])]
    replicate_source = None
    if method and method.replicate_file:
        replicate_source = await _replicate_source(url, members, method.replicate_file)
    known = {**by_name, **(replicate_source.columns if replicate_source else {})}
    missing_replicates = [w for w in all_weights if w not in known]
    if missing_replicates:
        raise UpstreamError(f"Replicate weights {missing_replicates[:3]} are not in the codebook.")

    result_rows, total_n, total_weight = await asyncio.to_thread(
        _run_query,
        DataSource(path, fixed_width, by_name),
        upper_rows,
        all_weights,
        statistic,
        value_variable.upper() if value_variable else None,
        upper_filters,
        replicate_source,
        method.id_variable if method else None,
    )
    width = len(upper_rows)
    labels = {name: _labels(by_name[name]) for name in upper_rows}
    estimates = [_estimates(row, width, len(all_weights), statistic) for row in result_rows]
    if statistic == "share":
        estimates = _to_shares(result_rows, estimates, width)
    cells: list[TableCell] = []
    for row, per_weight in list(zip(result_rows, estimates, strict=True))[
        : constants.TABLE_ROWS_MAX
    ]:
        codes = [str(c) if c is not None else "" for c in row[:width]]
        estimate = per_weight[0]
        standard_error = method.standard_error(estimate, per_weight[1:]) if method else None
        cells.append(
            TableCell(
                groups=[
                    TableGroup(variable=name, code=code, label=labels[name].get(code))
                    for name, code in zip(upper_rows, codes, strict=True)
                ],
                estimate=estimate,
                standard_error=standard_error,
                cv=(
                    abs(standard_error / estimate)
                    if standard_error is not None and estimate
                    else None
                ),
                unweighted_n=int(row[width]),
                low_count=int(row[width]) < min_count,
            )
        )
    replicates = [w for w in weights if w != chosen_weight]
    bootstrap_files = [
        m.name
        for m in members
        if "bsw" in m.name.lower()
        and m.name.lower().endswith(".txt")
        and "layout" not in m.name.lower()
    ]
    variance_note = (
        f"Standard errors: {method.description}"
        if method
        else "Standard errors are not computed for this PUMF: its variance method has not been "
        "verified from its user guide"
        + (f"; replicate weights: {', '.join(replicates[:5])}..." if replicates else "")
        + (
            f"; bootstrap weights ship in {bootstrap_files[0]} (joined on the record id)"
            if bootstrap_files
            else ""
        )
        + "."
    )
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
        variance_method=method.description if method else None,
        notes=[
            variance_note,
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

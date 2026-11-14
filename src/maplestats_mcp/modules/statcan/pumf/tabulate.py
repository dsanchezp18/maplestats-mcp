"""Weighted tables from PUMF microdata, computed server-side with DuckDB.

The data file is downloaded once into config.get_pumf_cache_dir() and
extracted from its ZIP; later calls reuse it. A download that outlives
the tool timeout keeps running in the background (asyncio.shield), so a
retry finds it finished rather than starting over.

CSV members are read as text with a header; fixed-width members (.dat,
.txt) are read one line per row and sliced with the codebook's column
positions. Everything is read as VARCHAR and cast explicitly, so a code
like "02" and the number 2 compare correctly. A ZIP with neither has its
SAS, SPSS or Stata file converted once to such a CSV (statfiles.py).

Standard errors come from the survey's own documented method where it has
been checked against the user guide (VARIANCE_METHODS): replicate weights
shipped with the file (Census, EICS, CSWC) or, for the LFS, which ships
none, the calibrated Poisson bootstrap its guide prescribes, generated here.
Other PUMFs get none, and results say so.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from maplestats_mcp import config
from maplestats_mcp.modules.statcan.lang import say, use_lang
from maplestats_mcp.modules.statcan.pumf import client, codebooks, constants, statfiles
from maplestats_mcp.modules.statcan.pumf.schemas import (
    PumfVariable,
    TableCell,
    TableGroup,
    WeightedTable,
)
from maplestats_mcp.shared import duck, remote_zip
from maplestats_mcp.shared.capped_io import FileTooLarge, check_size, copy_capped
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.executor import run_in_pool
from maplestats_mcp.shared.http import new_client, request_headers

Statistic = Literal["total", "share", "mean"]

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_DATA_EXT = (".csv", ".dat", ".txt", *statfiles.EXTENSIONS)
_NOT_DATA = ("bsw", "readme", "lisez", "layout", "frq", "codebook", "record", "_i.", "_o.")
_downloads: dict[str, asyncio.Task[Path]] = {}
_client = new_client(timeout=600.0, follow_redirects=True)
# Every redirect hop is checked like shared/remote_zip.py's range reads of the
# same ZIPs: following any Location let a link hand the download to any host.
_client.event_hooks = {
    "request": _client.event_hooks["request"],
    "response": [*_client.event_hooks["response"], remote_zip.check_redirect_response],
}
_log = logging.getLogger(__name__)


def _pick_member(
    members: list[remote_zip.ZipMember], data_file: str | None
) -> remote_zip.ZipMember:
    files = [m for m in members if not m.name.endswith("/")]
    if data_file:
        wanted = data_file.strip().lower()
        for member in files:
            if member.name.lower() == wanted or member.name.lower().endswith("/" + wanted):
                return member
        raise InvalidInput(
            say(
                f"No file {data_file!r} in the ZIP; see statcan_pumf_list_zip.",
                f"Aucun fichier {data_file!r} dans le ZIP ; voir statcan_pumf_list_zip.",
            )
        )
    candidates = [
        m
        for m in files
        if m.name.lower().endswith(_DATA_EXT)
        and not any(marker in m.name.lower() for marker in _NOT_DATA)
        and m.size > 100_000
    ]
    # CSV first, then fixed-width text; a SAS, SPSS or Stata file only when the
    # ZIP has neither (CCPI 34-25-0001), since it must be converted first.
    csvs = [m for m in candidates if m.name.lower().endswith(".csv")]
    text = [m for m in candidates if not statfiles.is_stat_file(m.name)]
    pool = csvs or text or candidates
    if len(pool) == 1:
        return pool[0]
    if not pool:
        raise NotFound(
            say(
                "No microdata file found in the ZIP; pass data_file (see statcan_pumf_list_zip).",
                "Aucun fichier de microdonnées trouvé dans le ZIP ; passez data_file (voir statcan_pumf_list_zip).",
            )
        )
    listing = ", ".join(f"{m.name} ({m.size / 1e6:.0f} MB)" for m in pool[:15])
    raise InvalidInput(
        say(
            f"The ZIP has several data files; pass data_file as one of: {listing}",
            f"Le ZIP contient plusieurs fichiers de données ; passez data_file parmi : {listing}",
        )
    )


def _enforce_cache_cap(root: Path, keep: Path, *also_keep: Path) -> None:
    """Remove the least recently used cached files until the cache fits its cap.

    Never removes `keep` (the file just written) or `also_keep` (other files
    this call is about to read), and never a `.part` file: that is another
    call's download in progress. A file that cannot be removed (Windows
    refuses while a reader has it open) or that vanishes mid-scan is logged
    and skipped, because failing to make room must not fail a call whose own
    data are already on disk.
    """
    protected = {keep, *also_keep}
    entries: list[tuple[float, int, Path]] = []
    for path in root.rglob("*"):
        if path.name.endswith(".part") or not path.is_file():
            continue
        try:
            info = path.stat()
        except OSError:
            continue
        entries.append((info.st_mtime, info.st_size, path))
    entries.sort(key=lambda entry: entry[0])
    total = sum(size for _, size, _ in entries)
    for _, size, path in entries:
        if total <= config.get_pumf_cache_max_bytes():
            break
        if path in protected:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("PUMF cache: could not remove %s: %s", path.name, exc)
            continue
        total -= size


async def _download(
    url: str,
    wanted: list[tuple[remote_zip.ZipMember, Path]],
    also_keep: tuple[Path, ...] = (),
) -> Path:
    """Download the ZIP once and extract every (member, target) in `wanted`.

    Returns the first target. The archive is deleted once they are extracted.
    """
    target = wanted[0][1]
    for _, each in wanted:
        each.parent.mkdir(parents=True, exist_ok=True)
    zip_path = target.parent / "archive.zip.part"
    try:
        async with _client.stream("GET", url, headers=request_headers(url, None)) as response:
            response.raise_for_status()
            written = 0
            with zip_path.open("wb") as handle:
                async for chunk in response.aiter_bytes(1 << 20):
                    written += len(chunk)
                    check_size(written, config.get_pumf_cache_max_bytes(), url)
                    handle.write(chunk)
    except (FileTooLarge, UpstreamError):
        # UpstreamError: a redirect off the allowed hosts, refused by the hook.
        zip_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        zip_path.unlink(missing_ok=True)
        raise UpstreamUnavailable(
            say(
                f"statcan_pumf: download of {url} failed: {exc}",
                f"statcan_pumf : le téléchargement de {url} a échoué : {exc}",
            )
        ) from exc

    def extract() -> None:
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for member, each in wanted:
                    part = each.with_suffix(each.suffix + ".part")
                    try:
                        with archive.open(member.name) as source, part.open("wb") as sink:
                            copy_capped(
                                source,
                                sink,
                                config.get_pumf_cache_max_bytes(),
                                f"{member.name} in {url}",
                            )
                        part.replace(each)
                    finally:
                        part.unlink(missing_ok=True)
        except FileTooLarge:
            raise
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            raise UpstreamError(
                say(
                    f"statcan_pumf: {url} could not be unpacked: {exc}",
                    f"statcan_pumf : {url} n'a pas pu être décompressé : {exc}",
                )
            ) from exc
        finally:
            zip_path.unlink(missing_ok=True)
        _enforce_cache_cap(
            config.get_pumf_cache_dir(), target, *(each for _, each in wanted[1:]), *also_keep
        )

    await run_in_pool(extract)
    return target


def _cache_slot(url: str, member: remote_zip.ZipMember) -> tuple[str, Path]:
    key = hashlib.sha1(f"{url}|{member.name}".encode()).hexdigest()[:16]
    return key, config.get_pumf_cache_dir() / key / Path(member.name).name


async def local_data_file(
    url: str,
    member: remote_zip.ZipMember,
    *,
    also_keep: tuple[Path, ...] = (),
    also_extract: tuple[remote_zip.ZipMember, ...] = (),
) -> Path:
    """The extracted member's path, downloading it first when it is not cached.

    `also_keep` names files the same call has already found and still needs,
    so making room for this download cannot evict them. `also_extract` names
    other members of the same ZIP the call will ask for next (EICS and CSWC
    bootstrap weights): when this member has to be downloaded, they are
    extracted from the same download, so the archive (hundreds of MB) is
    fetched once rather than once per member; the later call finds them cached.
    """
    key, target = _cache_slot(url, member)
    if target.exists():
        target.touch()
        return target
    task = _downloads.get(key)
    if task is None or task.done():
        wanted = [(member, target)]
        extra_keys = []
        for extra in also_extract:
            extra_key, extra_target = _cache_slot(url, extra)
            running = _downloads.get(extra_key)
            # A member another download is already writing is left to it: two
            # tasks extracting to the same .part file would corrupt it.
            if extra_target.exists() or (running is not None and not running.done()):
                continue
            wanted.append((extra, extra_target))
            extra_keys.append(extra_key)
        task = asyncio.create_task(_download(url, wanted, also_keep))
        # Registered under every member it writes, so a concurrent call for
        # any of them joins this download instead of starting another.
        for each_key in (key, *extra_keys):
            _downloads[each_key] = task
    # shield: if the tool call times out, the download still finishes for a retry.
    # The task returns its first member; a call that joined it for another
    # member it writes wants its own target.
    await asyncio.shield(task)
    return target


# Labels StatCan codebooks give the reserve codes of a numeric variable
# (9999996 "Valid skip", 99999999 "Not stated"). Seen in the LFS, CCHS and
# Census PUMF codebooks; a mean that kept them came out orders of magnitude
# too high, and filters (inclusion only) could not drop them.
_RESERVE_LABEL = re.compile(
    r"valid skip|not stated|not applicable|don'?t know|do not know|refus|missing|"
    r"enchaînement valide|non déclaré|non indiqué|sans objet|ne sait pas|refus|manquant",
    re.IGNORECASE,
)


def reserve_codes(variable: PumfVariable) -> list[float]:
    """Numeric codes the codebook labels as valid skip, not stated and the like."""
    codes: list[float] = []
    for value in variable.values:
        if not _RESERVE_LABEL.search(value.label or ""):
            continue
        try:
            codes.append(float(value.code))
        except ValueError:
            continue
    return codes


def _fmt_code(code: float) -> str:
    return str(int(code)) if code.is_integer() else str(code)


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


def _conditions(
    col: Callable[[str], str],
    filters: dict[str, list[str]],
    statistic: Statistic,
    value_variable: str | None,
    exclude_values: list[float] | None,
) -> tuple[list[str], list[Any], str | None]:
    """WHERE clauses with their parameters, and the value expression for means."""
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
    value_expr = None
    if statistic == "mean" and value_variable:
        value_expr = f"TRY_CAST({col(value_variable)} AS DOUBLE)"
        where.append(f"{value_expr} IS NOT NULL")
        if exclude_values:
            placeholders = ", ".join("?" for _ in exclude_values)
            where.append(f"{value_expr} NOT IN ({placeholders})")
            params.extend(exclude_values)
    return where, params, value_expr


def _execute[T](run: Callable[[Any], T]) -> T:
    """Run queries on a fresh DuckDB connection; a DuckDB error is the file's fault."""
    # DuckDB draws a terminal progress bar on long queries, on by default
    # (seen 2026-09-24 on the 1,000-replicate joins); over the stdio transport
    # anything printed to stdout corrupts the MCP stream and drops the client.
    # Imported on first use: duckdb takes ~0.5 s to import and only this tool
    # needs it, so server startup stays faster (2026-09-24).
    import duckdb

    try:
        with duck.connect() as connection:
            connection.execute("SET enable_progress_bar = false")
            # Each thread holds its own CSV buffers. Measured 2026-11-07 on 20 cores
            # with MAPLE_DUCKDB_MEMORY_LIMIT=384MB: the default threads ran out of
            # memory on the Census 2021 individuals file (16 replicate weights) and
            # the EICS 2024 bootstrap join; two threads finished both, at about
            # +400 MB and +215 MB of process memory, in about 80 s and 40 s (one
            # thread: 88 s and 74 s). The default ran out at 512MB too, on EICS.
            connection.execute("SET threads=2")
            return run(connection)
    except duckdb.Error as exc:
        # A ragged CSV row, a column the file does not have, or a bad join key
        # is a fault in the file, not in the caller's arguments.
        raise UpstreamError(
            say(
                f"statcan_pumf: the data file could not be tabulated: {exc}",
                f"statcan_pumf : le fichier de données n'a pas pu être tabulé : {exc}",
            )
        ) from exc


def _run_query(
    main: DataSource,
    group_by: list[str],
    weights: list[str],
    statistic: Statistic,
    value_variable: str | None,
    filters: dict[str, list[str]],
    replicates: DataSource | None = None,
    id_variable: str | None = None,
    exclude_values: list[float] | None = None,
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

    where, params, value_expr = _conditions(col, filters, statistic, value_variable, exclude_values)
    groups = [f"{col(name)} AS g{i}" for i, name in enumerate(group_by)]
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

    def run(connection: Any) -> tuple[list[tuple[Any, ...]], int, float]:
        rows = connection.execute(sql, params).fetchall()
        total_n, total_weight = connection.execute(totals_sql, params).fetchone() or (0, 0.0)
        return rows, int(total_n or 0), float(total_weight or 0.0)

    return _execute(run)


# Any fixed value: the replicates then come out the same on every call, so a
# retried or repeated table reports the same standard errors.
_POISSON_SEED = 123


def _poisson_sign(record: str, replicate: str) -> str:
    """+1 or -1 with probability 1/2, independently per record and replicate.

    The top bit of DuckDB's hash: its lowest bit is not independent across
    consecutive replicate numbers (correlation -0.21 between replicate b and
    b + 1 for the same record, measured 2026-11-08 on 2 million pairs); the
    top bit's correlations were all under 0.002 in absolute value.
    """
    return f"(CASE WHEN (hash({record}, {replicate}, {_POISSON_SEED}) >> 63) = 0 THEN 1.0 ELSE -1.0 END)"


def lfs_calibration_domain(col: Callable[[str], str]) -> str:
    """LFS PUMF User Guide 2025, Appendix B: province x age group x gender, 220 domains.

    Age groups as the guide's sample code builds them (Appendix D): AGE_6
    codes 1 and 2 (15-16, 17-19) on their own, AGE_12 codes 5-6 (35-44) and
    7-8 (45-54) merged, every other AGE_12 code as is (2 is 20-24).
    """

    def code(name: str) -> str:
        return f"TRY_CAST({col(name)} AS INTEGER)"

    age = (
        f"CASE WHEN {code('AGE_6')} IN (1, 2) THEN 'a' || {code('AGE_6')} "
        f"WHEN {code('AGE_12')} IN (5, 6) THEN '5' "
        f"WHEN {code('AGE_12')} IN (7, 8) THEN '7' "
        f"ELSE CAST({code('AGE_12')} AS VARCHAR) END"
    )
    return f"concat_ws('|', {code('PROV')}, {code('GENDER')}, {age})"


def _run_poisson_query(
    main: DataSource,
    group_by: list[str],
    weight: str,
    statistic: Statistic,
    value_variable: str | None,
    filters: dict[str, list[str]],
    method: VarianceMethod,
    exclude_values: list[float] | None = None,
) -> tuple[list[tuple[Any, ...]], int, float]:
    """Like _run_query, with replicate weights generated per the LFS PUMF guide.

    LFS PUMF User Guide 2025, section 6.1 and Appendix A1: for each record k
    and replicate b, a_bk = 1 + z_bk * sqrt(1 - 1/w_k) with z_bk = +1 or -1 at
    random (eq. 1), w_bk = a_bk * w_k (eq. 2), then w*_bk = w_bk * (sum of w
    in the record's calibration domain / sum of w_b in it) (eq. 3). The
    weights are calibrated on the whole file, before any filter, as the
    guide's sample code does. The rows come back in _run_query's layout, the
    replicates after the main weight, for VarianceMethod.standard_error.
    """
    replicates = method.generated_replicates
    id_variable = method.id_variable or ""
    domain_of = method.calibration_domain
    assert domain_of is not None and replicates > 0

    def col(name: str) -> str:
        return f'"{name}"'

    where, params, value_expr = _conditions(col, filters, statistic, value_variable, exclude_values)
    listed: list[str] = [
        *group_by,
        *filters,
        *([value_variable] if value_variable else []),
        weight,
        id_variable,
        *method.calibration_variables,
    ]
    needed = list(dict.fromkeys(listed))
    groups = [f"{col(name)} AS g{i}" for i, name in enumerate(group_by)]
    keep = " AND ".join(where) if where else "TRUE"
    base_sql = (
        f"CREATE TEMP TABLE base AS SELECT {''.join(g + ', ' for g in groups)}"
        f"TRY_CAST({col(id_variable)} AS BIGINT) AS rid, "
        f"TRY_CAST({col(weight)} AS DOUBLE) AS w, "
        f"{domain_of(col)} AS dom, "
        f"{value_expr or 'NULL'} AS x, ({keep}) AS keep "
        f"FROM ({main.select(needed)})"
    )
    # sqrt(1 - 1/w) is the guide's adjustment; GREATEST keeps a weight under 1
    # (none in the LFS) from making it NaN.
    boot = f"base.w * (1 + {_poisson_sign('base.rid', 'r.b')} * sqrt(GREATEST(0, 1 - 1 / base.w)))"
    replicates_sql = f"range(1, {replicates + 1}) AS r(b)"
    factor_sql = (
        "CREATE TEMP TABLE factor AS "
        f"WITH boot AS (SELECT base.dom, r.b, SUM({boot}) AS wb FROM base, {replicates_sql} "
        "GROUP BY base.dom, r.b), "
        "full_sample AS (SELECT dom, SUM(w) AS wd FROM base GROUP BY dom) "
        "SELECT boot.dom, boot.b, full_sample.wd / boot.wb AS f "
        "FROM boot JOIN full_sample ON boot.dom = full_sample.dom"
    )
    group_cols = [f"g{i}" for i in range(len(group_by))]
    group_list = ", ".join(group_cols)
    numerator = "x * w" if value_expr else "w"
    main_sql = (
        f"SELECT {', '.join([*group_cols, 'COUNT(*)', f'SUM({numerator})', 'SUM(w)'])} "
        "FROM base WHERE keep"
        + (f" GROUP BY {group_list} ORDER BY {group_list}" if group_by else "")
    )
    calibrated = f"{boot} * factor.f"
    replicate_numerator = f"base.x * {calibrated}" if value_expr else calibrated
    replicate_sql = (
        f"SELECT {', '.join([*(f'base.{g}' for g in group_cols), 'r.b'])}, "
        f"SUM({replicate_numerator}), SUM({calibrated}) "
        f"FROM base, {replicates_sql}, factor "
        "WHERE base.keep AND factor.dom = base.dom AND factor.b = r.b "
        f"GROUP BY {', '.join([*(f'base.{g}' for g in group_cols), 'r.b'])}"
    )
    totals_sql = "SELECT COUNT(*), SUM(w) FROM base WHERE keep"

    def run(connection: Any) -> tuple[list[tuple[Any, ...]], int, float]:
        connection.execute(base_sql, params)
        connection.execute(factor_sql)
        rows = connection.execute(main_sql).fetchall()
        by_group: dict[tuple[Any, ...], list[Any]] = {}
        width = len(group_by)
        for row in rows:
            by_group[tuple(row[:width])] = [None, None] * replicates
        for *codes, b, numerator_b, denominator_b in connection.execute(replicate_sql).fetchall():
            slots = by_group.get(tuple(codes))
            if slots is not None:
                slots[2 * (b - 1)] = numerator_b
                slots[2 * (b - 1) + 1] = denominator_b
        total_n, total_weight = connection.execute(totals_sql).fetchone() or (0, 0.0)
        wide = [(*row, *by_group[tuple(row[:width])]) for row in rows]
        return wide, int(total_n or 0), float(total_weight or 0.0)

    return _execute(run)


Quality = Literal["acceptable", "marginal", "unacceptable"]


@dataclass(frozen=True)
class ReleaseRule:
    """A user guide's quality bands: respondents in the cell and CV (SE / estimate)."""

    min_respondents: int
    acceptable_below: float  # CV under this is acceptable
    marginal_up_to: float  # CV from acceptable_below up to this is marginal
    citation: str

    def quality(self, respondents: int, cv: float | None) -> Quality | None:
        if respondents < self.min_respondents:
            return "unacceptable"
        if cv is None:
            return None
        if cv < self.acceptable_below:
            return "acceptable"
        return "marginal" if cv <= self.marginal_up_to else "unacceptable"


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
    # Replicates this server generates when the PUMF ships none (LFS), with the
    # variables and domains the guide calibrates them on.
    generated_replicates: int = 0
    calibration_variables: tuple[str, ...] = ()
    calibration_domain: Callable[[Callable[[str], str]], str] | None = None
    release: ReleaseRule | None = None

    @property
    def replicate_count(self) -> int:
        return self.generated_replicates or len(self.replicates)

    def standard_error(
        self, estimate: float | None, replicate_estimates: Sequence[float | None]
    ) -> float | None:
        values = [v for v in replicate_estimates if v is not None]
        if len(values) != self.replicate_count or estimate is None:
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
    VarianceMethod(
        # LFS PUMF User Guide 2025 (UserGuide_LFS_PUMF_2025_ENG.pdf in every
        # 71M0001X ZIP, monthly and historical, checked 2026-11-08): the PUMF has
        # no bootstrap weights; section 6.0 says to approximate the variance with
        # a calibrated Poisson bootstrap, built per 6.1 and Appendix A1 (equations
        # 1-3), calibrated on the Appendix B domains, with the variance of 6.2 and
        # A2 (sum of squared deviations from the FINALWT estimate / 1000), and the
        # Table 5 quality bands of section 5.2. The guide gives no CV lookup table.
        url_marker="/71m0001x/",
        main_weight="FINALWT",
        replicates=(),
        divisor=1000.0,
        centre="estimate",
        description=(
            "calibrated Poisson bootstrap (LFS PUMF User Guide 2025, s. 6.1-6.2 and "
            "Appendix A): 1,000 replicate weights FINALWT x (1 +/- sqrt(1 - 1/FINALWT)), "
            "each calibrated to the FINALWT totals of the 220 province x age group x gender "
            "domains of Appendix B, then sqrt(sum of squared deviations from the "
            "full-sample estimate / 1000). The replicates are generated by this server with "
            "a fixed seed, so the standard error approximates StatCan's (the guide says so "
            "of the method itself) and repeats exactly from call to call."
        ),
        id_variable="REC_NUM",
        generated_replicates=1000,
        calibration_variables=("PROV", "GENDER", "AGE_6", "AGE_12"),
        calibration_domain=lfs_calibration_domain,
        release=ReleaseRule(
            min_respondents=5,
            acceptable_below=0.15,
            marginal_up_to=0.35,
            citation="LFS PUMF User Guide 2025, s. 5.2, Table 5",
        ),
    ),
)


def _replicate_member(
    members: list[remote_zip.ZipMember], file_marker: str
) -> remote_zip.ZipMember | None:
    return next((m for m in members if m.name.lower().endswith(file_marker)), None)


async def _replicate_source(
    url: str, members: list[remote_zip.ZipMember], file_marker: str, main_path: Path
) -> DataSource:
    """The separate bootstrap-weight file, with its layout from its own .dct."""
    data = _replicate_member(members, file_marker)
    layout = next(
        (m for m in members if "bsw" in m.name.lower() and m.name.lower().endswith(".dct")), None
    )
    if data is None or layout is None:
        raise NotFound(
            say(
                f"The bootstrap weight file ({file_marker}) or its layout is not in the ZIP.",
                f"Le fichier des poids bootstrap ({file_marker}) ou sa disposition ne se trouve pas dans le ZIP.",
            )
        )
    dct = await remote_zip.read_member(url, layout)
    columns = codebooks.parse_stata_dct(dct.decode("cp1252", errors="replace"))
    path = await local_data_file(url, data, also_keep=(main_path,))
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


def _release_notes(release: ReleaseRule | None, statistic: Statistic) -> list[str]:
    if release is None:
        return []
    acceptable, marginal = (
        round(100 * release.acceptable_below),
        round(100 * release.marginal_up_to),
    )
    notes = [
        say(
            f"quality follows {release.citation}: acceptable with {release.min_respondents} or more "
            f"respondents and a CV under {acceptable}%; marginal (publish with a warning on "
            f"quality) at a CV of {acceptable}% to {marginal}%; unacceptable under "
            f"{release.min_respondents} respondents or above {marginal}%, which Statistics "
            "Canada recommends not releasing. Cells are flagged, not suppressed.",
            f"quality suit {release.citation} : acceptable si au moins {release.min_respondents} "
            f"répondants et un CV inférieur à {acceptable} % ; marginale (à publier avec une mise "
            f"en garde sur la qualité) pour un CV de {acceptable} % à {marginal} % ; "
            f"inacceptable sous {release.min_respondents} répondants ou au-delà de {marginal} %, "
            "et Statistique Canada recommande alors de ne pas diffuser. Les cellules sont "
            "signalées, pas supprimées.",
        )
    ]
    if statistic in ("share", "mean"):
        notes.append(
            say(
                "For small ratios such as an unemployment rate the guide warns that the CV can be "
                "misleadingly large; a confidence interval (estimate +/- 2 standard errors at 95%) "
                "describes them better.",
                "Pour de petits ratios comme un taux de chômage, le guide prévient que le CV peut "
                "être trompeusement élevé ; un intervalle de confiance (estimation +/- 2 erreurs "
                "types à 95 %) les décrit mieux.",
            )
        )
    return notes


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
    use_lang(lang)
    if len(rows) > 3:
        raise InvalidInput(
            say("Group by at most 3 variables.", "Regroupez selon au plus 3 variables.")
        )
    if statistic == "mean" and not value_variable:
        raise InvalidInput(
            say(
                "statistic 'mean' needs value_variable.",
                "La statistique « mean » exige value_variable.",
            )
        )
    members, _, _ = await client._members(url)
    member = _pick_member(members, data_file)
    stat_file = statfiles.is_stat_file(member.name)
    # A SAS, SPSS or Stata file names its own variables when the ZIP has no
    # codebook the parsers read (CCPI); load_codebook then downloads it.
    variables, _, _ = await client.load_codebook(
        url, lang, data_member=member.name if stat_file else None
    )
    by_name = {v.name: v for v in variables}
    weights = client.weight_names(variables)
    chosen_weight = (weight or client.main_weight(variables) or "").upper()
    if not chosen_weight:
        raise InvalidInput(
            say(
                f"No weight variable found; pass weight (candidates: {weights}).",
                f"Aucune variable de pondération trouvée ; passez weight (candidates : {weights}).",
            )
        )
    wanted = [*rows, chosen_weight, *(filters or {}), *([value_variable] if value_variable else [])]
    for name in wanted:
        if not _NAME.match(name) or name.upper() not in by_name:
            raise InvalidInput(
                say(
                    f"{name!r} is not a variable in this PUMF's codebook.",
                    f"{name!r} n'est pas une variable du dictionnaire de données de ce FMGD.",
                )
            )
    upper_rows = [r.upper() for r in rows]
    upper_filters = {k.upper(): [str(c) for c in v] for k, v in (filters or {}).items()}

    fixed_width = not member.name.lower().endswith(".csv") and not stat_file
    if fixed_width:
        missing = [
            n for n in wanted if not by_name[n.upper()].position or not by_name[n.upper()].width
        ]
        if missing:
            raise UpstreamError(
                say(
                    f"The codebook gives no column positions for {missing}.",
                    f"Le dictionnaire de données ne donne aucune position de colonne pour {missing}.",
                )
            )
    method = variance_method(url)
    if method and chosen_weight != method.main_weight:
        method = None
    if method and method.generated_replicates:
        # Generated replicates need the record id and the calibration variables,
        # by name (CSV) or by position (fixed width).
        needed = [method.id_variable or "", *method.calibration_variables]
        if any(n not in by_name or (fixed_width and not by_name[n].position) for n in needed):
            method = None
    # The bootstrap weights sit in the same ZIP as the data: extracting them
    # from the data file's download spares a second download of the archive
    # when _replicate_source asks for them below.
    replicate_member = (
        _replicate_member(members, method.replicate_file)
        if method and method.replicate_file
        else None
    )
    path = await local_data_file(
        url, member, also_extract=(replicate_member,) if replicate_member else ()
    )
    if stat_file:
        path = await run_in_pool(statfiles.to_csv, path)

    all_weights = [chosen_weight, *(method.replicates if method else [])]
    replicate_source = None
    if method and method.replicate_file:
        replicate_source = await _replicate_source(url, members, method.replicate_file, path)
    known = {**by_name, **(replicate_source.columns if replicate_source else {})}
    missing_replicates = [w for w in all_weights if w not in known]
    if missing_replicates:
        raise UpstreamError(
            say(
                f"Replicate weights {missing_replicates[:3]} are not in the codebook.",
                f"Les poids répliqués {missing_replicates[:3]} ne sont pas dans le dictionnaire de données.",
            )
        )
    if method and method.id_variable and replicate_source is not None:
        # The replicate join reads the record id from both files by position
        # (fixed width) or by name; without it in the layout the query would
        # fail on a bare KeyError instead of saying which variable is missing.
        id_name = method.id_variable
        absent = [
            (en, fr)
            for en, fr, present in (
                (
                    "the main codebook",
                    "le dictionnaire principal",
                    id_name in by_name or not fixed_width,
                ),
                (
                    "the bootstrap weight layout",
                    "la disposition des poids bootstrap",
                    id_name in replicate_source.columns,
                ),
            )
            if not present
        ]
        if absent:
            raise InvalidInput(
                say(
                    f"The record id variable {id_name!r}, needed to join the bootstrap weights, "
                    f"is not in {' or '.join(en for en, _ in absent)}.",
                    f"La variable d'identifiant {id_name!r}, nécessaire pour joindre les poids "
                    f"bootstrap, ne figure pas dans {' ni '.join(fr for _, fr in absent)}.",
                )
            )

    value_name = value_variable.upper() if value_variable else ""
    reserved = reserve_codes(by_name[value_name]) if statistic == "mean" and value_variable else []
    source = DataSource(path, fixed_width, by_name)
    if method and method.generated_replicates:
        result_rows, total_n, total_weight = await run_in_pool(
            _run_poisson_query,
            source,
            upper_rows,
            chosen_weight,
            statistic,
            value_name or None,
            upper_filters,
            method,
            reserved,
        )
    else:
        result_rows, total_n, total_weight = await run_in_pool(
            _run_query,
            source,
            upper_rows,
            all_weights,
            statistic,
            value_name or None,
            upper_filters,
            replicate_source,
            method.id_variable if method else None,
            reserved,
        )
    weight_count = 1 + (method.replicate_count if method else 0)
    width = len(upper_rows)
    labels = {name: _labels(by_name[name]) for name in upper_rows}
    estimates = [_estimates(row, width, weight_count, statistic) for row in result_rows]
    if statistic == "share":
        estimates = _to_shares(result_rows, estimates, width)
    release = method.release if method else None
    cells: list[TableCell] = []
    for row, per_weight in list(zip(result_rows, estimates, strict=True))[
        : constants.TABLE_ROWS_MAX
    ]:
        codes = [str(c) if c is not None else "" for c in row[:width]]
        estimate = per_weight[0]
        standard_error = method.standard_error(estimate, per_weight[1:]) if method else None
        cv = abs(standard_error / estimate) if standard_error is not None and estimate else None
        respondents = int(row[width])
        cells.append(
            TableCell(
                groups=[
                    TableGroup(variable=name, code=code, label=labels[name].get(code))
                    for name, code in zip(upper_rows, codes, strict=True)
                ],
                estimate=estimate,
                standard_error=standard_error,
                cv=cv,
                quality=release.quality(respondents, cv) if release else None,
                unweighted_n=respondents,
                low_count=respondents < min_count,
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
    shown_replicates = ", ".join(replicates[:5])
    variance_note = (
        say(
            f"Standard errors: {method.description}",
            f"Erreurs types : {method.description} (méthode décrite en anglais, d'après le "
            "guide de l'utilisateur)",
        )
        if method
        else say(
            "Standard errors are not computed for this PUMF: its variance method has not been "
            "verified from its user guide"
            + (f"; replicate weights: {shown_replicates}..." if replicates else "")
            + (
                f"; bootstrap weights ship in {bootstrap_files[0]} (joined on the record id)"
                if bootstrap_files
                else ""
            )
            + ".",
            "Les erreurs types ne sont pas calculées pour ce FMGD : sa méthode d'estimation "
            "de la variance n'a pas été vérifiée dans son guide de l'utilisateur"
            + (f" ; poids répliqués : {shown_replicates}..." if replicates else "")
            + (
                f" ; les poids bootstrap sont dans {bootstrap_files[0]} (joints sur "
                "l'identifiant d'enregistrement)"
                if bootstrap_files
                else ""
            )
            + ".",
        )
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
            *_release_notes(release, statistic),
            *(
                [
                    say(
                        f"{member.name} was converted to text once (pyreadstat) and read like a "
                        "CSV; variable names are upper case, other characters replaced by '_'.",
                        f"{member.name} a été converti une fois en texte (pyreadstat) et lu comme "
                        "un CSV ; les noms de variables sont en majuscules, les autres caractères "
                        "remplacés par « _ ».",
                    )
                ]
                if stat_file
                else []
            ),
            say(
                f"Cells with fewer than {min_count} respondents are flagged low_count; StatCan "
                "guidelines usually suppress or qualify them.",
                f"Les cellules de moins de {min_count} répondants sont marquées low_count ; les "
                "lignes directrices de Statistique Canada les suppriment ou les nuancent "
                "habituellement.",
            ),
            say(
                "Special codes (valid skip, don't know, not stated) are included unless filtered "
                "out"
                + (
                    f"; the mean leaves out {value_name}'s reserve codes "
                    f"{', '.join(_fmt_code(c) for c in reserved)}."
                    if reserved
                    else "."
                ),
                "Les codes spéciaux (enchaînement valide, ne sait pas, non déclaré) sont inclus "
                "sauf s'ils sont filtrés"
                + (
                    f" ; la moyenne exclut les codes réservés de {value_name} "
                    f"{', '.join(_fmt_code(c) for c in reserved)}."
                    if reserved
                    else "."
                ),
            ),
            say(
                "Some variables carry implied decimals (LFS HRLYEARN is in cents); check the "
                "codebook or user guide before reporting means.",
                "Certaines variables ont des décimales implicites (HRLYEARN de l'EPA est en "
                "cents) ; vérifiez le dictionnaire de données ou le guide de l'utilisateur avant "
                "de publier des moyennes.",
            ),
        ],
        provenance=make_provenance(
            source=constants.RATE_LIMIT_SOURCE,
            url=url,
            cached=False,
            schema_name="statcan_pumf.WeightedTable",
            limits=say(
                "computed from the PUMF microdata by this server with DuckDB",
                "calculé par ce serveur avec DuckDB à partir des microdonnées du FMGD",
            ),
            lang=lang,
        ),
    )

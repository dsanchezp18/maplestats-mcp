"""One read-only SQL query over a slice of an SDMX dataset (Eurostat, OECD).

The same shape as wds_query_table (modules/statcan/wds/table_query.py): the calling
module reads its dataset's structure and the observations of a slice (codes per
dimension, and the periods), and hands them here. This file loads them into a table
`obs` (OBS_COLUMNS, then two columns per dimension: its code and its label), checks
the query with modules/statcan/wds/query_checks.py (mixed units, scales and
adjustments, a total summed with its own parts, a WHERE value no row holds), runs it
in shared/duck_sandbox.py and returns the result. Nothing is cached or written to
disk: the slice lives for the call.

The checks see SDMX series through the shapes StatCan's use: each series gets a
number (series_id), each code its place in its dimension, and the hierarchy maps a
code's place to its parent's. Parents come from the codelist where the source
publishes them (the OECD: areas, ISIC, COICOP, sectors, transactions; checked live
2026-11-20) and otherwise from what the codes themselves say, which is all Eurostat
offers (its codelists carry no parents and its hierarchical codelists are not served,
checked live 2026-11-20):

- a total code (TOTAL, _T; T for sex) holds every other code of its dimension;
- an age band holds the bands inside it (Y15-64 holds Y15-24; OECD Y15T64);
- a NACE section or range holds its divisions (C holds C10-C12 and C10; B-E holds C);
- a NUTS region holds the regions whose code extends its own (DE holds DE1 and DE11);
- EU27_2020, EU28 and the euro-area aggregates hold their member countries.

A part found this way is always inside its whole, so a refusal is never wrong; a
hierarchy the codes do not show (GDP and its expenditure components on Eurostat) is
not checked.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from maplestats_mcp.modules.eurostat import constants as eurostat_constants
from maplestats_mcp.modules.statcan.wds import client as wds_client
from maplestats_mcp.modules.statcan.wds import query as wds_query
from maplestats_mcp.modules.statcan.wds import query_checks
from maplestats_mcp.shared import duck_sandbox
from maplestats_mcp.shared.errors import InvalidInput, NotFound

# Observations a slice may hold. The sandbox gets them as JSON over a pipe, and `obs`
# here has two columns per dimension: 35,000 Eurostat series over nine years (about
# 300,000 rows) exhausted its memory, 100,000 rows loaded and ran in 19 s, most of it
# the download (demo_r_pjangroup, 2026-11-20).
MAX_ROWS = 150_000

OBS_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("series_id", "BIGINT", "a number for each series of the slice"),
    ("dataset", "VARCHAR", "the dataset id"),
    ("series_key", "VARCHAR", "the series' SDMX key: its codes joined by dots"),
    ("period", "VARCHAR", "the period as published: 2024, 2024-Q2, 2024-05"),
    ("ref_period", "DATE", "the first day of the period"),
    ("value", "DOUBLE", "the value as published; null when confidential or missing"),
    ("scale_multiplier", "BIGINT", "multiply value by this for the full figure"),
    ("decimals", "INTEGER", "decimals published, where the source says"),
    ("status", "VARCHAR", "the observation's status or flag, e.g. 'provisional'"),
    ("series_title", "VARCHAR", "the labels of the series' codes, joined by '; '"),
    ("dataset_title", "VARCHAR", "the dataset's title"),
    ("unit", "VARCHAR", "unit of measure"),
    ("scale", "VARCHAR", "unit multiplier, e.g. 'Millions'"),
    ("frequency", "VARCHAR", "e.g. 'Annual', 'Quarterly'"),
    ("geography", "VARCHAR", "the geography's label"),
    ("adjustment", "VARCHAR", "'seasonally adjusted', 'unadjusted' or 'trend-cycle', when known"),
    ("quality", "VARCHAR", "'E' (low reliability) or 'x' (confidential)"),
)
OBS_COLUMN_NAMES = ", ".join(name for name, _, _ in OBS_COLUMNS)
_TEXT_COLUMNS = frozenset(
    {"dataset", "series_key", "period", "status", "series_title", "dataset_title"}
    | {"unit", "scale", "frequency", "geography", "adjustment", "quality"}
)

# Seasonal adjustment by code: Eurostat's s_adj, the OECD's ADJUSTMENT (checked live
# 2026-11-20). Calendar adjustment alone is not seasonal adjustment.
_ADJUSTMENT_CODES = {
    "NSA": "unadjusted",
    "CA": "unadjusted",
    "SA": "seasonally adjusted",
    "SCA": "seasonally adjusted",
    "TC": "trend-cycle",
    "N": "unadjusted",
    "K": "unadjusted",
    "S": "seasonally adjusted",
    "Y": "seasonally adjusted",
    "T": "trend-cycle",
}

_PERIOD = re.compile(
    r"^(\d{4})(?:-(?:(Q)([1-4])|(S)([12])|(W)(\d{2})|(A)1|M?(\d{2})(?:-(\d{2}))?))?$"
)


def period_start(text: str) -> date | None:
    """The first day of an SDMX period: 2024, 2024-Q2, 2024-S2, 2024-W05, 2024-05,
    2024-M05, 2024-05-15. None for any other form."""
    match = _PERIOD.match(text.strip())
    if not match:
        return None
    year = int(match.group(1))
    try:
        if match.group(2):
            return date(year, 3 * int(match.group(3)) - 2, 1)
        if match.group(4):
            return date(year, 1 if match.group(5) == "1" else 7, 1)
        if match.group(6):
            return date.fromisocalendar(year, int(match.group(7)), 1)
        if match.group(9):
            return date(year, int(match.group(9)), int(match.group(10) or 1))
        return date(year, 1, 1)
    except ValueError:
        return None


@dataclass
class SliceDimension:
    """A key dimension: its id, label, the labels of its codes, and parents where known.

    `role` says what the dimension is for `obs`: "geo", "unit", "freq", "adjustment"
    or None. `parents` holds the parents the source publishes; the others are derived.
    """

    id: str
    name: str
    labels: dict[str, str]
    parents: dict[str, str] = field(default_factory=dict)
    role: str | None = None


@dataclass
class SliceObservation:
    period: str
    value: float | None
    status: str | None = None
    quality: str | None = None


@dataclass
class SliceSeries:
    """One series of the slice: its codes in dimension order, what its attributes say,
    and its observations."""

    codes: tuple[str, ...]
    observations: list[SliceObservation]
    unit: str | None = None
    unit_multiplier: int | None = None
    scale: str | None = None
    decimals: int | None = None


@dataclass
class Outcome:
    sql: str
    columns: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    truncated: bool
    input_rows: int
    dimension_columns: dict[str, str]
    warnings: list[str]


# ---- columns ------------------------------------------------------------------------

_NAME = re.compile(r"[^a-z0-9]+")


def dimension_columns(dims: Sequence[SliceDimension]) -> dict[str, str]:
    """Each dimension's `obs` column for its codes (its id in lower case; "_code" is
    added where that would shadow an obs column: Eurostat's unit). Its label column is
    the same name plus "_label"."""
    taken = {name for name, _, _ in OBS_COLUMNS}
    out: dict[str, str] = {}
    for dim in dims:
        column = _NAME.sub("_", dim.id.strip().lower()).strip("_") or "dimension"
        if column[0].isdigit():
            column = f"d_{column}"
        if column in taken or f"{column}_label" in taken:
            column = f"{column}_code"
        while column in taken or f"{column}_label" in taken:
            column = f"{column}_"
        taken |= {column, f"{column}_label"}
        out[dim.id] = column
    return out


def _hint() -> str:
    example = "SELECT geography, avg(value) FROM obs GROUP BY ALL ORDER BY 2 DESC"
    return wds_client._m(
        f"Query the table `obs`, whose columns are: {OBS_COLUMN_NAMES}, and for each "
        f"dimension its code and its label (dimension_columns names them). Example: {example}",
        f"Interrogez la table `obs`, dont les colonnes sont : {OBS_COLUMN_NAMES}, et pour "
        "chaque dimension son code et son libellé (dimension_columns les nomme). Exemple : "
        f"{example}",
    )


def check_sql(sql: str) -> str:
    """The SQL to run, or InvalidInput when it is not one read-only SELECT over `obs`."""
    text = (sql or "").strip()
    limit = wds_query.constants.QUERY_MAX_SQL_CHARS
    if not text:
        raise InvalidInput(
            wds_client._m(
                f"sql must not be empty. {_hint()}", f"sql ne doit pas être vide. {_hint()}"
            )
        )
    if len(text) > limit:
        raise InvalidInput(
            wds_client._m(
                f"sql is {len(text)} characters; the limit is {limit}.",
                f"sql compte {len(text)} caractères ; la limite est {limit}.",
            )
        )
    problem = duck_sandbox.select_problem(text)
    if problem is None:
        return text
    kind, detail = problem
    if kind == "parse":
        raise InvalidInput(
            wds_client._m(
                f"The SQL does not parse: {detail}. {_hint()}",
                f"Le SQL n'est pas valide : {detail}. {_hint()}",
            )
        )
    raise InvalidInput(wds_query._problem_message(kind, detail))


def check_codes(
    sql: str, dims: Sequence[SliceDimension], columns: Mapping[str, str], lang: str
) -> None:
    """Refuse, before the download, a WHERE comparing a dimension's code column with a
    code the dataset has no data for (query_checks' unknown_value). Labels are checked
    after the download, against the labels the data came with."""
    wds_client.use_lang(lang)
    known: dict[str, set[Any]] = {columns[dim.id]: set(dim.labels) for dim in dims}
    planned = query_checks.plan(sql, known)
    query_checks.check_literals(planned.literals, known)


# ---- hierarchy ------------------------------------------------------------------------

_TOTALS = ("TOTAL", "_T", "TOT", "ALL")
_AGE = re.compile(r"^Y(?:(\d+)(?:-|T)(\d+)|_LT(\d+)|_GE(\d+)|(\d+))$")
# NACE Rev. 2 sections and their divisions.
_NACE_SECTIONS = {
    "A": (1, 3), "B": (5, 9), "C": (10, 33), "D": (35, 35), "E": (36, 39), "F": (41, 43),
    "G": (45, 47), "H": (49, 53), "I": (55, 56), "J": (58, 63), "K": (64, 66), "L": (68, 68),
    "M": (69, 75), "N": (77, 82), "O": (84, 84), "P": (85, 85), "Q": (86, 88), "R": (90, 93),
    "S": (94, 96), "T": (97, 98), "U": (99, 99),
}  # fmt: skip
_NACE_DIVISIONS = re.compile(r"^([A-U])(\d{2})(?:-[A-U]?(\d{2}))?$")
_NACE_LETTERS = re.compile(r"^[A-U](?:-[A-U])?(?:_[A-U](?:-[A-U])?)*$")
_ISIC_RANGE = re.compile(r"^[A-U]T[A-U]$")
# Aggregates of Eurostat's geo codelist and their members (eurostat/constants.py).
_EU27 = frozenset(eurostat_constants.EU27)
_EA21 = frozenset(eurostat_constants.EURO_AREA)
_GEO_AGGREGATES: dict[str, frozenset[str]] = {
    "EU27_2020": _EU27,
    "EU28": _EU27 | {"UK"},
    "EA21": _EA21,
    "EA20": _EA21 - {"BG"},
    "EA19": _EA21 - {"BG", "HR"},
}
_COUNTRIES = _EU27 | {"UK"} | set(eurostat_constants.EFTA) | set(eurostat_constants.CANDIDATES)
# The same aggregates in the OECD's ISO 3166 alpha-3 codes, and the OECD's own: its
# area codelist gives no parent to members or aggregates (checked live 2026-11-20).
_EU27_ISO3 = frozenset((
    "AUT", "BEL", "BGR", "CYP", "CZE", "DEU", "DNK", "EST", "ESP", "FIN", "FRA", "GRC", "HRV",
    "HUN", "IRL", "ITA", "LTU", "LUX", "LVA", "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN",
    "SWE",
))  # fmt: skip
_EA21_ISO3 = frozenset((
    "AUT", "BEL", "BGR", "CYP", "DEU", "EST", "ESP", "FIN", "FRA", "GRC", "HRV", "IRL", "ITA",
    "LTU", "LUX", "LVA", "MLT", "NLD", "PRT", "SVK", "SVN",
))  # fmt: skip
_OECD = frozenset((
    "AUS", "AUT", "BEL", "CAN", "CHE", "CHL", "COL", "CRI", "CZE", "DEU", "DNK", "ESP", "EST",
    "FIN", "FRA", "GBR", "GRC", "HUN", "IRL", "ISL", "ISR", "ITA", "JPN", "KOR", "LTU", "LUX",
    "LVA", "MEX", "NLD", "NOR", "NZL", "POL", "PRT", "SVK", "SVN", "SWE", "TUR", "USA",
))  # fmt: skip
_ISO3_AGGREGATES: dict[str, frozenset[str]] = {
    "OECD": _OECD,
    "G7": frozenset(("CAN", "DEU", "FRA", "GBR", "ITA", "JPN", "USA")),
    "EU27_2020": _EU27_ISO3,
    "EA21": _EA21_ISO3,
    "EA20": _EA21_ISO3 - {"BGR"},
    "EA19": _EA21_ISO3 - {"BGR", "HRV"},
}
_ISO3_COUNTRIES = _OECD | _EU27_ISO3
_NUTS = re.compile(r"^[A-Z]{2}[0-9A-Z]{1,3}$")


def _age(code: str) -> tuple[float, float] | None:
    match = _AGE.match(code)
    if not match:
        return None
    low, high, below, above, single = match.groups()
    if low is not None:
        return float(low), float(high) + 1
    if below is not None:
        return 0.0, float(below)
    if above is not None:
        return float(above), float("inf")
    return float(single), float(single) + 1


def _sections(first: str, last: str) -> set[int]:
    divisions: set[int] = set()
    for letter in "ABCDEFGHIJKLMNOPQRSTU"[ord(first) - 65 : ord(last) - 64]:
        low, high = _NACE_SECTIONS[letter]
        divisions.update(range(low, high + 1))
    return divisions


def _activity(code: str) -> frozenset[int] | None:
    """The NACE Rev. 2 / ISIC Rev. 4 divisions a code holds: C10, C10-C12, C, B-E, M_N,
    or the OECD's BTE (B to E)."""
    match = _NACE_DIVISIONS.match(code)
    if match:
        first = int(match.group(2))
        last = int(match.group(3) or first)
        return frozenset(range(first, last + 1)) if first <= last else None
    if _ISIC_RANGE.match(code):
        return frozenset(_sections(code[0], code[2])) or None
    if _NACE_LETTERS.match(code):
        divisions: set[int] = set()
        for part in code.split("_"):
            first, _, last = part.partition("-")
            divisions |= _sections(first, last or first)
        return frozenset(divisions) or None
    return None


def _covers(dim: SliceDimension) -> dict[str, frozenset[Any]]:
    """What each code holds, where the code says: an age band, activity divisions, or
    countries."""
    dim_id = dim.id.lower()
    out: dict[str, frozenset[Any]] = {}
    # EU27_2020 is a code in both schemes: members in Eurostat's two-letter codes, or in
    # the OECD's ISO 3166 alpha-3, whichever the dimension's countries use.
    iso3 = sum(c in _ISO3_COUNTRIES for c in dim.labels) > sum(c in _COUNTRIES for c in dim.labels)
    aggregates, countries = (
        (_ISO3_AGGREGATES, _ISO3_COUNTRIES) if iso3 else (_GEO_AGGREGATES, _COUNTRIES)
    )
    for code in dim.labels:
        if dim_id == "age":
            band = _age(code)
            if band is not None:
                out[code] = frozenset({band})
        elif "nace" in dim_id or "activity" in dim_id or "isic" in dim_id:
            divisions = _activity(code)
            if divisions:
                out[code] = divisions
        elif dim.role == "geo":
            held = aggregates.get(code)
            if held is not None:
                out[code] = held
            elif code in countries:
                out[code] = frozenset({code})
    return out


def _inside(inner: frozenset[Any], outer: frozenset[Any], bands: bool) -> bool:
    if not bands:
        return inner < outer
    (a,), (b,) = tuple(inner), tuple(outer)
    return b[0] <= a[0] and a[1] <= b[1] and a != b


def _derived_parents(dim: SliceDimension) -> dict[str, set[str]]:
    """Every code each code lies inside, as the codes show it (see the module docstring)."""
    codes = list(dim.labels)
    parents: dict[str, set[str]] = {}
    covers = _covers(dim)
    bands = dim.id.lower() == "age"
    for code, held in covers.items():
        for other, cover in covers.items():
            if other != code and _inside(held, cover, bands):
                parents.setdefault(code, set()).add(other)
    if dim.role == "geo":
        known = set(codes)
        for code in codes:
            if not _NUTS.match(code) or code[:2] not in _COUNTRIES:
                continue
            for cut in range(len(code) - 1, 1, -1):
                if code[:cut] in known:
                    parents.setdefault(code, set()).add(code[:cut])
                    break
    totals = [
        t for t in (*_TOTALS, *(("T",) if dim.id.lower() == "sex" else ())) if t in dim.labels
    ]
    if totals:
        for code in codes:
            if code != totals[0]:
                parents.setdefault(code, set()).add(totals[0])
    return parents


def hierarchy(dims: Sequence[SliceDimension]) -> dict[int, dict[int, list[int]]]:
    """Dimension position (from 1) -> code place -> its parents' places, for query_checks:
    the parents the source publishes and those the codes show."""
    out: dict[int, dict[int, list[int]]] = {}
    for position, dim in enumerate(dims, start=1):
        place = {code: i for i, code in enumerate(dim.labels, start=1)}
        parents = _derived_parents(dim)
        for code, parent in dim.parents.items():
            if parent:
                parents.setdefault(code, set()).add(parent)
        out[position] = {
            place[c]: sorted(place[p] for p in parents.get(c, set()) if p in place) for c in place
        }
    return out


# ---- the query ------------------------------------------------------------------------


def _adjustment(dims: Sequence[SliceDimension], codes: Sequence[str], title: str) -> str | None:
    for dim, code in zip(dims, codes, strict=True):
        if dim.role == "adjustment":
            return _ADJUSTMENT_CODES.get(code.upper()) or query_checks.adjustment(
                dim.labels.get(code, code), None
            )
    return query_checks.adjustment(title, None)


async def run(
    *,
    sql: str,
    dataset: str,
    dataset_title: str,
    dims: Sequence[SliceDimension],
    series: Sequence[SliceSeries],
    lang: str,
) -> Outcome:
    """Load the slice into `obs`, check `sql`, run it and return the result."""
    wds_client.use_lang(lang)
    columns_by_dim = dimension_columns(dims)
    rows: list[tuple[Any, ...]] = []
    refs: list[query_checks.SeriesRef] = []
    places = [{code: i for i, code in enumerate(d.labels, start=1)} for d in dims]
    roles = {d.role: i for i, d in enumerate(dims) if d.role}
    for number, s in enumerate(series, start=1):
        labels = [d.labels.get(c, c) for d, c in zip(dims, s.codes, strict=True)]
        title = "; ".join(labels)
        key = ".".join(s.codes)

        def label_of(role: str, labels: list[str] = labels) -> str | None:
            return labels[roles[role]] if role in roles else None

        unit = label_of("unit") or s.unit
        frequency = label_of("freq")
        geography = label_of("geo")
        adjustment = _adjustment(dims, s.codes, title)
        multiplier = 10**s.unit_multiplier if s.unit_multiplier is not None else 1
        coordinate = ".".join(str(p.get(c, 0)) for p, c in zip(places, s.codes, strict=True))
        refs.append(query_checks.SeriesRef(number, 0, coordinate, title))
        for o in s.observations:
            if len(rows) >= MAX_ROWS:
                raise InvalidInput(
                    wds_client._m(
                        f"The slice holds more than {MAX_ROWS:,} rows. Name codes for more "
                        "dimensions, or narrow the periods.",
                        f"La tranche dépasse {MAX_ROWS:,} lignes. Précisez des codes pour "
                        "d'autres dimensions, ou réduisez les périodes.".replace(",", " "),
                    )
                )
            rows.append(
                (
                    number,
                    dataset,
                    key,
                    o.period,
                    period_start(o.period),
                    o.value,
                    multiplier,
                    s.decimals,
                    o.status,
                    title,
                    dataset_title,
                    unit,
                    s.scale,
                    frequency,
                    geography,
                    adjustment,
                    o.quality,
                    *(v for pair in zip(s.codes, labels, strict=True) for v in pair),
                )
            )
    if not rows:
        raise NotFound(
            wds_client._m(
                "No observation matches the codes and periods asked for.",
                "Aucune observation ne correspond aux codes et aux périodes demandés.",
            )
        )
    # Sorted by series then period, so the sandbox's run-length encoding packs every
    # column that repeats within a series (titles, units, codes).
    rows.sort(key=lambda r: (r[0], r[4] or date.min, r[3]))
    text_columns = set(_TEXT_COLUMNS)
    table_columns = [(name, kind) for name, kind, _ in OBS_COLUMNS]
    for dim in dims:
        column = columns_by_dim[dim.id]
        table_columns += [(column, "VARCHAR"), (f"{column}_label", "VARCHAR")]
        text_columns |= {column, f"{column}_label"}
    values = [list(column) for column in zip(*rows, strict=True)]
    table = duck_sandbox.Table(name="obs", columns=table_columns, values=values)
    names = [name for name, _ in table_columns]
    planned = query_checks.plan(sql, text_columns, series_column="series_id", obs_columns=names)
    held = {
        name: set(column)
        for (name, _), column in zip(table_columns, values, strict=True)
        if name in text_columns
    }
    query_checks.check_literals(planned.literals, held)
    findings = query_checks.Findings()
    seconds = wds_query.query_time_limit()
    if planned.diagnostic_sql:
        try:
            diagnostic = await duck_sandbox.run_query(
                [table],
                planned.diagnostic_sql,
                seconds=seconds,
                row_cap=query_checks.MAX_GROUPS * len(planned.aggregates),
                max_chars=wds_query.constants.QUERY_MAX_RESULT_CHARS,
                max_cell_chars=wds_query.constants.QUERY_MAX_RESULT_CHARS,
            )
        except duck_sandbox.SandboxError:
            diagnostic = None
        if diagnostic is not None:
            findings = query_checks.evaluate(planned, diagnostic.rows, refs, {0: hierarchy(dims)})
            if findings.refusals:
                raise query_checks.refusal_error(findings)
    try:
        result = await duck_sandbox.run_query(
            [table],
            sql,
            seconds=seconds,
            row_cap=wds_query.constants.QUERY_ROW_CAP,
            max_chars=wds_query.constants.QUERY_MAX_RESULT_CHARS,
            max_cell_chars=wds_query.constants.QUERY_MAX_CELL_CHARS,
        )
    except duck_sandbox.SandboxError as exc:
        raise wds_query._sandbox_error(exc, seconds) from exc
    return Outcome(
        sql=sql,
        columns=result.columns,
        column_types=result.types,
        rows=result.rows,
        truncated=result.truncated,
        input_rows=len(rows),
        dimension_columns=columns_by_dim,
        warnings=findings.warnings,
    )

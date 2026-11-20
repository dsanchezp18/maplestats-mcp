"""Checks on what a wds_query_series query does with the numbers, before and after it runs.

The sandbox (query.py) makes sure a query cannot harm the server; these checks look
for queries that run fine and answer wrongly. Each check either refuses the query
before it runs (InvalidInput, saying what to change) or lets it run and adds a
warning to the result, always with what was measured.

How a check sees the data: for every SELECT in the query that reads `obs` directly
and aggregates `value` (sum, avg, min, max, median, ...), a diagnostic query is
built from the user's own FROM, WHERE and GROUP BY (GROUP BY ALL resolved to the
select list's non-aggregate expressions, aliases and positions to their
expressions) with the aggregates replaced by measurements of each group: which
units, scale multipliers, frequencies and seasonal adjustments it mixes, which
series it holds, how many values are null, and how many are flagged E or F. The
diagnostic runs in the same sandbox as the query. Built with DuckDB's own
json_serialize_sql / json_deserialize_sql, so it reads the query as DuckDB does.

Refused (the result would be wrong whatever the data):
- `mixed_units`: one aggregate over values in different units (Percent with Persons).
- `mixed_scale`: different scale multipliers (units with thousands) and the query
  does not use scale_multiplier.
- `mixed_adjustment`: seasonally adjusted with unadjusted or trend-cycle values in a
  sum or average.
- `total_with_parts`: a SUM over a series and its own parts (Canada with the
  provinces, Labour force with Employment), read from the table's member
  hierarchy: the total would be counted twice.
- `unknown_value`: WHERE compares a text column with a value no row holds (a typo,
  or English text on a French result), which would return nothing.

Warned (the result is right but easy to misread):
- `mixed_frequency`, `sum_of_rates`, `average_of_rates` (an unweighted mean of
  several places' rates is not their combined rate), `average_with_parts`,
  `nulls` (suppressed or missing values skipped by the aggregate), `quality`
  (E or F values in the aggregate), `scaled_values` (values in thousands or
  millions, not multiplied out).

A check that cannot be built (an unusual query shape) is skipped, never turned
into an error: the query then runs as before, without these checks.
"""

from __future__ import annotations

import copy
import difflib
import json
import logging
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from maplestats_mcp.modules.statcan.wds import client
from maplestats_mcp.shared import duck_worker
from maplestats_mcp.shared.errors import InvalidInput

_logger = logging.getLogger(__name__)

# Aggregates whose result depends on the units of the values they read.
_SUM = frozenset({"sum", "fsum", "sumkahan", "kahan_sum", "sum_no_overflow"})
_AVG = frozenset({"avg", "mean", "favg"})
_ORDER = frozenset(
    {
        "min",
        "max",
        "median",
        "quantile",
        "quantile_cont",
        "quantile_disc",
        "mode",
        "stddev",
        "stddev_samp",
        "stddev_pop",
        "var_samp",
        "var_pop",
        "variance",
        "product",
        "geomean",
        "geometric_mean",
        "mad",
    }
)
_VALUE_AGGREGATES = _SUM | _AVG | _ORDER
# Every aggregate, to tell GROUP BY ALL's grouping expressions from its aggregates.
_ALL_AGGREGATES = _VALUE_AGGREGATES | {
    "count",
    "count_star",
    "list",
    "array_agg",
    "string_agg",
    "group_concat",
    "listagg",
    "first",
    "last",
    "any_value",
    "arg_min",
    "arg_max",
    "argmin",
    "argmax",
    "min_by",
    "max_by",
    "bool_and",
    "bool_or",
    "histogram",
    "approx_count_distinct",
    "approx_quantile",
    "entropy",
    "kurtosis",
    "skewness",
    "corr",
    "covar_pop",
    "covar_samp",
    "regr_slope",
    "regr_intercept",
}

# Text columns a WHERE may compare with a literal; a literal no row holds is a typo.
TEXT_COLUMNS = frozenset(
    {
        "table_id",
        "coordinate",
        "status",
        "symbol",
        "series_title",
        "table_title",
        "unit",
        "scale",
        "frequency",
        "geography",
        "adjustment",
        "quality",
    }
)
# Units whose values are rates, shares or index levels: their sum means nothing.
_RATE_UNIT = re.compile(r"percent|pourcent|rate|taux|=\s*100|ratio|index|indice", re.IGNORECASE)

_ADJUSTMENT_MIXES = "mixed_adjustment"
MAX_GROUPS = 500
_EXAMPLES = 3

_DIAGNOSTIC_SELECT = (
    "SELECT concat_ws(' / ', 'g') AS grp, count(*) AS n, "
    "count(*) FILTER (WHERE value IS NULL) AS n_null, "
    "count(DISTINCT vector_id) AS n_vec, "
    "string_agg(DISTINCT CAST(vector_id AS VARCHAR), ',') AS vids, "
    "string_agg(DISTINCT unit, '|') AS units, "
    "string_agg(DISTINCT CAST(scale_multiplier AS VARCHAR), '|') AS scales, "
    "string_agg(DISTINCT frequency, '|') AS freqs, "
    "string_agg(DISTINCT adjustment, '|') AS adjs, "
    "count(*) FILTER (WHERE quality = 'E') AS n_e, "
    "count(*) FILTER (WHERE quality = 'F') AS n_f "
    "FROM obs"
)
_DIAGNOSTIC_COLUMNS = (
    "node",
    "grp",
    "n",
    "n_null",
    "n_vec",
    "vids",
    "units",
    "scales",
    "freqs",
    "adjs",
    "n_e",
    "n_f",
)


# ---- the two derived obs columns ------------------------------------------------------

_TREND = re.compile(r"trend[- ]cycle|tendance[- ]cycle", re.IGNORECASE)
_UNADJUSTED_TEXT = re.compile(
    r"\bnot seasonally adjusted|\bunadjusted|non d[ée]saisonnalis|donn[ée]es brutes",
    re.IGNORECASE,
)
_ADJUSTED_TEXT = re.compile(r"seasonally adjusted|d[ée]saisonnalis", re.IGNORECASE)


def adjustment(series_title: str | None, table_title: str | None) -> str | None:
    """'seasonally adjusted', 'unadjusted' or 'trend-cycle' from the series' member
    names (its title), then its table's title; None when neither says.

    A member's word wins over the title's: 14-10-0287 is titled "seasonally adjusted
    and trend-cycle" and its series name one or the other.
    """
    for text in (series_title or "", table_title or ""):
        if _TREND.search(text) and not _ADJUSTED_TEXT.search(text):
            return "trend-cycle"
        if _UNADJUSTED_TEXT.search(text):
            return "unadjusted"
        if _ADJUSTED_TEXT.search(text):
            return "seasonally adjusted"
    return None


def quality(status_code: int | None, security_level_code: int | None) -> str | None:
    """StatCan's letter for a flagged value: E (use with caution), F (too unreliable
    to be published) or x (suppressed); None for the rest."""
    if security_level_code == 1:
        return "x"
    if status_code == 7:
        return "E"
    if status_code == 8:
        return "F"
    return None


# ---- findings -------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesRef:
    """One series as the checks see it: its table, coordinate and a name to quote."""

    vector_id: int
    product_id: int
    coordinate: str
    name: str


@dataclass
class Findings:
    refusals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def refuse(self, text: str) -> None:
        if text not in self.refusals:
            self.refusals.append(text)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)


# ---- reading the query -----------------------------------------------------------------


def _tree(connection: Any, sql: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT json_serialize_sql($1::VARCHAR)", [sql]).fetchone()
    tree = json.loads(row[0]) if row else None
    if not isinstance(tree, dict) or tree.get("error") or not tree.get("statements"):
        return None
    return tree


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _select_nodes(tree: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [n for n in _walk(tree) if n.get("type") == "SELECT_NODE"]


def _reads_obs(node: Mapping[str, Any]) -> bool:
    table = node.get("from_table") or {}
    return (
        table.get("type") == "BASE_TABLE"
        and str(table.get("table_name", "")).lower() == "obs"
        and not table.get("schema_name")
    )


def _column(node: Mapping[str, Any]) -> str | None:
    if node.get("class") == "COLUMN_REF":
        names = node.get("column_names") or []
        return str(names[-1]).lower() if names else None
    return None


def _expressions(node: Any) -> Iterator[dict[str, Any]]:
    """Expressions inside `node`, not descending into subqueries."""
    if isinstance(node, dict):
        if node.get("class") == "SUBQUERY" or node.get("type") == "SELECT_NODE":
            return
        yield node
        for value in node.values():
            yield from _expressions(value)
    elif isinstance(node, list):
        for value in node:
            yield from _expressions(value)


def _function(node: Mapping[str, Any]) -> str | None:
    if node.get("class") in ("FUNCTION", "AGGREGATE") and not node.get("is_operator"):
        return str(node.get("function_name", "")).lower()
    return None


def _has_aggregate(expression: Any) -> bool:
    return any(_function(e) in _ALL_AGGREGATES for e in _expressions(expression))


def _columns_in(expression: Any) -> set[str]:
    return {c for e in _expressions(expression) if (c := _column(e))}


def _value_aggregates(node: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """(aggregate, uses scale_multiplier) for each aggregate over `value` in the node."""
    found = []
    for part in (node.get("select_list"), node.get("having")):
        for expression in _expressions(part):
            name = _function(expression)
            if name not in _VALUE_AGGREGATES:
                continue
            used = _columns_in(expression.get("arguments"))
            if "value" in used:
                found.append((name, "scale_multiplier" in used))
    return found


def _windowed(node: Mapping[str, Any]) -> bool:
    return any(e.get("class") == "WINDOW" for e in _expressions(node.get("select_list")))


def _filtered(node: Mapping[str, Any]) -> bool:
    """Whether an aggregate over `value` has its own FILTER (WHERE ...): the diagnostic
    measures the whole group, not the filtered rows, so it would judge the wrong rows.
    `sum(value) FILTER (WHERE geo = 'DE')` beside a total was refused until 2026-11-20."""
    for part in (node.get("select_list"), node.get("having")):
        for expression in _expressions(part):
            if _function(expression) in _VALUE_AGGREGATES and expression.get("filter"):
                return True
    return False


def _groups(
    node: Mapping[str, Any], obs_names: frozenset[str] | None = None
) -> list[dict[str, Any]] | None:
    """The node's grouping expressions as plain expressions, or None when unusual."""
    obs_names = _OBS_NAMES if obs_names is None else obs_names
    select = list(node.get("select_list") or [])
    if node.get("aggregate_handling") == "FORCE_AGGREGATES":
        return [copy.deepcopy(e) for e in select if not _has_aggregate(e)]
    sets = node.get("group_sets") or []
    if len(sets) > 1:  # ROLLUP, CUBE, GROUPING SETS: totals rows mix by design.
        return None
    aliases = {str(e.get("alias", "")).lower(): e for e in select if e.get("alias")}
    resolved = []
    for expression in node.get("group_expressions") or []:
        literal = (expression.get("literal") or {}) if expression.get("class") == "CONSTANT" else {}
        name = _column(expression)
        if literal.get("kind") in ("INTEGER", "BIGINT") and str(literal.get("text", "")).isdigit():
            position = int(literal["text"])
            if not 1 <= position <= len(select):
                return None
            resolved.append(copy.deepcopy(select[position - 1]))
        elif name and name in aliases and name not in obs_names:
            resolved.append(copy.deepcopy(aliases[name]))
        else:
            resolved.append(copy.deepcopy(expression))
    return resolved


# Set by query.py: the obs column names, so an alias that shadows one is read as the column.
_OBS_NAMES: frozenset[str] = frozenset()


def set_obs_columns(names: Iterable[str]) -> None:
    global _OBS_NAMES
    _OBS_NAMES = frozenset(n.lower() for n in names)


def _template(
    connection: Any, series_column: str = "vector_id"
) -> tuple[list[Any], dict[str, Any]]:
    """The diagnostic select list, and a CAST(... AS VARCHAR) expression to fill.

    `series_column` names the column that tells series apart: vector_id for StatCan,
    series_id for an SDMX dataset's slice (shared/sdmx_query.py)."""
    tree = _tree(connection, _DIAGNOSTIC_SELECT.replace("vector_id", series_column))
    cast_tree = _tree(connection, "SELECT CAST(x AS VARCHAR) FROM obs")
    if tree is None or cast_tree is None:
        raise ValueError("diagnostic template does not parse")
    select = tree["statements"][0]["node"]["select_list"]
    cast = cast_tree["statements"][0]["node"]["select_list"][0]
    return select, cast


def _diagnostic(
    connection: Any,
    tree: Mapping[str, Any],
    node: Mapping[str, Any],
    index: int,
    series_column: str = "vector_id",
    obs_names: frozenset[str] | None = None,
) -> str | None:
    groups = _groups(node, obs_names)
    if groups is None:
        return None
    select, cast = _template(connection, series_column)
    for expression in groups:
        expression["alias"] = ""
    label = select[0]
    arguments = label["arguments"] if "arguments" in label else label["children"]
    if groups:
        filled = []
        for expression in groups:
            item = copy.deepcopy(cast)
            item["child"] = expression
            filled.append({"name": "", "expression": item} if "arguments" in label else item)
        arguments[1:] = filled
    else:
        first = arguments[1]
        constant = (
            first["expression"] if isinstance(first, dict) and "expression" in first else first
        )
        constant["literal"]["text"] = "all rows"
    diagnostic = copy.deepcopy(dict(node))
    diagnostic.update(
        select_list=select,
        group_expressions=copy.deepcopy(groups),
        group_sets=[list(range(len(groups)))] if groups else [],
        aggregate_handling="STANDARD_HANDLING",
        having=None,
        qualify=None,
        modifiers=[],
    )
    statement = copy.deepcopy(dict(tree))
    statement["statements"] = [{**tree["statements"][0], "node": diagnostic}]
    row = connection.execute(
        "SELECT json_deserialize_sql($1::JSON)", [json.dumps(statement)]
    ).fetchone()
    if not row or not row[0]:
        return None
    return f"SELECT {index} AS node, * FROM ({row[0]}) LIMIT {MAX_GROUPS}"


@dataclass
class Plan:
    """What the checks need from one query: its diagnostic SQL and its aggregates."""

    diagnostic_sql: str | None
    aggregates: list[list[tuple[str, bool]]]
    literals: list[tuple[str, str]]
    # The column that tells series apart, as the refusals name it.
    series_column: str = "vector_id"


def plan(
    sql: str,
    text_columns: Iterable[str] = (),
    *,
    series_column: str = "vector_id",
    obs_columns: Iterable[str] | None = None,
) -> Plan:
    """Read `sql` once: the diagnostic to run and the literals its WHERE compares.

    `text_columns` adds text columns beyond TEXT_COLUMNS (a table's dimensions).
    `series_column` and `obs_columns` describe another `obs` than wds_query_series'
    (an SDMX dataset's slice: series_id, and its own columns).
    """
    obs_names = None if obs_columns is None else frozenset(c.lower() for c in obs_columns)
    connection = duck_worker.open_sandbox(16)
    try:
        tree = _tree(connection, sql)
        if tree is None:
            return Plan(None, [], [], series_column)
        literals = _where_literals(tree, TEXT_COLUMNS | {c.lower() for c in text_columns})
        parts: list[str] = []
        aggregates: list[list[tuple[str, bool]]] = []
        for node in _select_nodes(tree):
            if not _reads_obs(node) or _windowed(node) or _filtered(node):
                continue
            used = _value_aggregates(node)
            if not used:
                continue
            try:
                part = _diagnostic(
                    connection, tree, node, len(aggregates), series_column, obs_names
                )
            except (KeyError, IndexError, TypeError, ValueError):
                _logger.debug("query_checks: no diagnostic for one SELECT", exc_info=True)
                part = None
            if part is not None:
                parts.append(part)
                aggregates.append(used)
        return Plan(" UNION ALL ".join(parts) or None, aggregates, literals, series_column)
    finally:
        connection.close()


def _where_literals(tree: Mapping[str, Any], text_columns: frozenset[str]) -> list[tuple[str, str]]:
    """(column, text) for each `column = 'text'` or `column IN ('a', ...)` on obs."""
    found: list[tuple[str, str]] = []
    for node in _select_nodes(tree):
        if not _reads_obs(node):
            continue
        for expression in _expressions(node.get("where_clause")):
            kind = expression.get("type")
            if kind == "COMPARE_EQUAL":
                pairs = [(expression.get("left"), expression.get("right"))]
                pairs.append((expression.get("right"), expression.get("left")))
            elif kind == "COMPARE_IN":
                children = expression.get("children") or []
                pairs = [(children[0], c) for c in children[1:]] if children else []
            else:
                continue
            for column_side, literal_side in pairs:
                column = _column(column_side or {})
                literal = (literal_side or {}).get("literal") or {}
                if column in text_columns and literal.get("kind") in ("VARCHAR", "STRING"):
                    found.append((column, str(literal.get("text", ""))))
    return found


# ---- checking ---------------------------------------------------------------------------


def check_literals(literals: Sequence[tuple[str, str]], values: Mapping[str, set[Any]]) -> None:
    """Refuse a WHERE that compares a text column with a value no row of `obs` holds."""
    problems = []
    for column, text in literals:
        held = {v for v in values.get(column, set()) if isinstance(v, str)}
        if not held or text in held:
            continue
        close = difflib.get_close_matches(text, sorted(held), n=3, cutoff=0.6)
        same_case = [v for v in held if v.lower() == text.lower()]
        hint = same_case or close
        problems.append(
            client._m(
                f"{column} = {text!r} matches no row"
                + (f"; did you mean {', '.join(repr(h) for h in hint)}?" if hint else "")
                + f" ({column} holds {len(held)} value(s)"
                + (f", e.g. {', '.join(repr(v) for v in sorted(held)[:5])})" if not hint else ")"),
                f"{column} = {text!r} ne correspond à aucune ligne"
                + (f" ; vouliez-vous dire {', '.join(repr(h) for h in hint)} ?" if hint else "")
                + f" ({column} contient {len(held)} valeur(s)"
                + (
                    f", p. ex. {', '.join(repr(v) for v in sorted(held)[:5])})" if not hint else ")"
                ),
            )
        )
    if problems:
        raise InvalidInput(
            client._m(
                "The query would return no rows (refused before it ran, unknown_value): ",
                "La requête ne renverrait aucune ligne (refusée avant exécution, unknown_value) : ",
            )
            + "; ".join(problems)
            + "."
        )


Hierarchy = Mapping[int, Mapping[int, Mapping[int, int | Sequence[int] | None]]]
"""product id -> dimension position -> member id -> parent member id. An SDMX code
can have several (a country inside the EU and the OECD; shared/sdmx_query.py)."""


def hierarchy_from(
    cubes: Mapping[int, Mapping[str, Any] | None],
) -> dict[int, dict[int, dict[int, int | None]]]:
    """Each table's member parents from its getCubeMetadata, by dimension position."""
    out: dict[int, dict[int, dict[int, int | None]]] = {}
    for product_id, cube in cubes.items():
        if not cube:
            continue
        dims: dict[int, dict[int, int | None]] = {}
        for dim in cube.get("dimension") or []:
            parents: dict[int, int | None] = {}
            for member in dim.get("member") or []:
                parent = member.get("parentMemberId")
                parents[int(member["memberId"])] = int(parent) if parent not in (None, "") else None
            dims[int(dim["dimensionPositionId"])] = parents
        out[product_id] = dims
    return out


def _ancestors(parents: Mapping[int, int | Sequence[int] | None], member: int) -> set[int]:
    seen: set[int] = set()
    todo = [member]
    while todo:
        found = parents.get(todo.pop())
        for parent in [found] if isinstance(found, int) else (found or []):
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


def part_of(whole: SeriesRef, part: SeriesRef, hierarchy: Hierarchy) -> bool:
    """Whether `part` is inside `whole` in the table's member hierarchy: the same member
    or one of its descendants in every dimension, and a descendant in at least one."""
    if whole.product_id != part.product_id or whole.vector_id == part.vector_id:
        return False
    dims = hierarchy.get(whole.product_id)
    if not dims:
        return False
    a, b = whole.coordinate.split("."), part.coordinate.split(".")
    strictly = False
    for position, (x, y) in enumerate(zip(a, b, strict=False), start=1):
        if x == y:
            continue
        if not (x.isdigit() and y.isdigit()):
            return False
        parents = dims.get(position, {})
        if int(x) not in _ancestors(parents, int(y)):
            return False
        strictly = True
    return strictly


def _groups_text(groups: list[str], total: int) -> str:
    shown = ", ".join(repr(g) for g in groups[:_EXAMPLES])
    more = total - min(total, _EXAMPLES)
    return shown + (client._m(f" and {more} more", f" et {more} autres") if more else "")


def evaluate(
    plan_: Plan,
    rows: Sequence[Sequence[Any]],
    series: Sequence[SeriesRef],
    hierarchy: Hierarchy,
) -> Findings:
    """Turn the diagnostic's measured groups into refusals and warnings."""
    findings = Findings()
    by_id = {s.vector_id: s for s in series}
    by_node: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        record: dict[str, Any] = dict(zip(_DIAGNOSTIC_COLUMNS, row, strict=False))
        by_node.setdefault(int(record["node"]), []).append(record)
    for index, aggregates in enumerate(plan_.aggregates):
        _evaluate_node(
            findings, aggregates, by_node.get(index, []), by_id, hierarchy, plan_.series_column
        )
    return findings


def _split(text: Any, sep: str = "|") -> list[str]:
    return [t for t in str(text).split(sep) if t] if text not in (None, "") else []


def _evaluate_node(
    findings: Findings,
    aggregates: list[tuple[str, bool]],
    groups: list[dict[str, Any]],
    by_id: Mapping[int, SeriesRef],
    hierarchy: Hierarchy,
    series_column: str = "vector_id",
) -> None:
    names = {name for name, _ in aggregates}
    summing = bool(names & _SUM)
    averaging = bool(names & _AVG)
    additive = summing or averaging
    scaled_out = all(uses for _, uses in aggregates)
    hits: dict[str, list[str]] = {}

    def hit(kind: str, group: dict[str, Any]) -> None:
        hits.setdefault(kind, []).append(str(group.get("grp")))

    measured: dict[str, Any] = {"null": [0, 0], "E": 0, "F": 0, "units": set(), "scales": set()}
    parts_example: tuple[str, str] | None = None
    for group in groups:
        units, scales = _split(group.get("units")), _split(group.get("scales"))
        freqs, adjs = _split(group.get("freqs")), _split(group.get("adjs"))
        measured["units"].update(units)
        measured["scales"].update(scales)
        if len(units) > 1:
            hit("mixed_units", group)
        if len(scales) > 1 and not scaled_out:
            hit("mixed_scale", group)
        if additive and len(adjs) > 1:
            hit(_ADJUSTMENT_MIXES, group)
        if additive and len(freqs) > 1:
            hit("mixed_frequency", group)
        rate = any(_RATE_UNIT.search(u) for u in units)
        if summing and rate:
            hit("sum_of_rates", group)
        if averaging and rate and int(group.get("n_vec") or 0) > 1:
            hit("average_of_rates", group)
        measured["null"][0] += int(group.get("n_null") or 0)
        measured["null"][1] += int(group.get("n") or 0)
        measured["E"] += int(group.get("n_e") or 0)
        measured["F"] += int(group.get("n_f") or 0)
        if int(group.get("n_vec") or 0) > 1:
            ids = [int(v) for v in _split(group.get("vids"), ",") if v.isdigit()]
            members = [by_id[i] for i in ids if i in by_id]
            pair = next(
                ((w, p) for w in members for p in members if part_of(w, p, hierarchy)), None
            )
            if pair is not None:
                hit("total_with_parts" if summing else "average_with_parts", group)
                parts_example = parts_example or (pair[0].name, pair[1].name)

    def groups_of(kind: str) -> str:
        return _groups_text(hits[kind], len(hits[kind]))

    if "mixed_units" in hits:
        findings.refuse(
            client._m(
                f"mixed_units: {', '.join(sorted(measured['units']))} are aggregated together "
                f"in group(s) {groups_of('mixed_units')}. Add unit (or {series_column}) to GROUP "
                "BY, or filter to one unit.",
                f"mixed_units : {', '.join(sorted(measured['units']))} sont agrégés ensemble "
                f"dans le ou les groupes {groups_of('mixed_units')}. Ajoutez unit (ou "
                f"{series_column}) au GROUP BY, ou filtrez sur une seule unité.",
            )
        )
    if "mixed_scale" in hits:
        findings.refuse(
            client._m(
                f"mixed_scale: values with scale multipliers {', '.join(sorted(measured['scales']))} "
                f"are aggregated together in group(s) {groups_of('mixed_scale')}. Aggregate "
                "value * scale_multiplier, or group by scale_multiplier.",
                f"mixed_scale : des valeurs aux multiplicateurs {', '.join(sorted(measured['scales']))} "
                f"sont agrégées ensemble dans le ou les groupes {groups_of('mixed_scale')}. "
                "Agrégez value * scale_multiplier, ou groupez par scale_multiplier.",
            )
        )
    if _ADJUSTMENT_MIXES in hits:
        findings.refuse(
            client._m(
                "mixed_adjustment: seasonally adjusted, unadjusted or trend-cycle values are "
                f"summed or averaged together in group(s) {groups_of(_ADJUSTMENT_MIXES)}. "
                "Filter on adjustment (WHERE adjustment = 'seasonally adjusted') or group by it.",
                "mixed_adjustment : des valeurs désaisonnalisées, brutes ou de tendance-cycle "
                f"sont additionnées ou moyennées ensemble dans le ou les groupes "
                f"{groups_of(_ADJUSTMENT_MIXES)}. Filtrez sur adjustment (WHERE adjustment = "
                "'seasonally adjusted') ou groupez par cette colonne.",
            )
        )
    if "total_with_parts" in hits and parts_example:
        whole, part = parts_example
        findings.refuse(
            client._m(
                f"total_with_parts: the sum adds a total to its own parts, e.g. {whole!r} "
                f"includes {part!r} (member hierarchy), in group(s) "
                f"{groups_of('total_with_parts')}: the total would be counted twice. Drop the "
                "total or the parts from the query.",
                f"total_with_parts : la somme ajoute un total à ses propres parties, p. ex. "
                f"{whole!r} comprend {part!r} (hiérarchie des membres), dans le ou "
                f"les groupes {groups_of('total_with_parts')} : le total serait compté deux "
                "fois. Retirez le total ou les parties de la requête.",
            )
        )
    if "average_with_parts" in hits and parts_example:
        whole, part = parts_example
        findings.warn(
            client._m(
                f"average_with_parts: the aggregate mixes a total with its own parts (e.g. "
                f"{whole!r} and {part!r}) in group(s) {groups_of('average_with_parts')}.",
                f"average_with_parts : l'agrégat mêle un total et ses parties (p. ex. "
                f"{whole!r} et {part!r}) dans le ou les groupes "
                f"{groups_of('average_with_parts')}.",
            )
        )
    if "mixed_frequency" in hits:
        findings.warn(
            client._m(
                "mixed_frequency: values of different frequencies (e.g. monthly and annual) are "
                f"summed or averaged together in group(s) {groups_of('mixed_frequency')}.",
                "mixed_frequency : des valeurs de fréquences différentes (p. ex. mensuelles et "
                "annuelles) sont additionnées ou moyennées ensemble dans le ou les groupes "
                f"{groups_of('mixed_frequency')}.",
            )
        )
    if "sum_of_rates" in hits:
        findings.warn(
            client._m(
                "sum_of_rates: SUM adds rates, percentages or index values (a sum of them is "
                f"not a rate) in group(s) {groups_of('sum_of_rates')}. Use AVG, or compute the "
                "rate from the levels.",
                "sum_of_rates : SUM additionne des taux, des pourcentages ou des indices (leur "
                f"somme n'est pas un taux) dans le ou les groupes {groups_of('sum_of_rates')}. "
                "Utilisez AVG, ou calculez le taux à partir des niveaux.",
            )
        )
    if "average_of_rates" in hits:
        findings.warn(
            client._m(
                "average_of_rates: AVG takes an unweighted mean of several series' rates in "
                f"group(s) {groups_of('average_of_rates')}; that is not the rate of the places "
                "combined (for that, use the total's own series or compute it from the levels).",
                "average_of_rates : AVG fait une moyenne non pondérée des taux de plusieurs "
                f"séries dans le ou les groupes {groups_of('average_of_rates')} ; ce n'est pas "
                "le taux de l'ensemble (prenez la série du total, ou calculez-le à partir des "
                "niveaux).",
            )
        )
    nulls, total = measured["null"]
    if nulls:
        findings.warn(
            client._m(
                f"nulls: {nulls} of {total} values read by the aggregate are null (suppressed "
                "or not available) and are skipped, so some groups cover fewer periods or "
                "series than they seem to.",
                f"nulls : {nulls} des {total} valeurs lues par l'agrégat sont nulles "
                "(supprimées ou non disponibles) et sont ignorées : certains groupes couvrent "
                "moins de périodes ou de séries qu'il n'y paraît.",
            )
        )
    if measured["E"] or measured["F"]:
        findings.warn(
            client._m(
                f"quality: the aggregate reads {measured['E']} value(s) flagged E (use with "
                f"caution) and {measured['F']} flagged F (too unreliable to be published); "
                "say so with the result.",
                f"quality : l'agrégat lit {measured['E']} valeur(s) signalée(s) E (à utiliser "
                f"avec prudence) et {measured['F']} signalée(s) F (trop peu fiables pour être "
                "publiées) ; dites-le avec le résultat.",
            )
        )
    big = sorted(s for s in measured["scales"] if s not in ("1", ""))
    if additive and big and not scaled_out and "mixed_scale" not in hits:
        findings.warn(
            client._m(
                f"scaled_values: values are in units of {', '.join(big)} (scale_multiplier); "
                "the result is in those units too, not in full figures.",
                f"scaled_values : les valeurs sont en unités de {', '.join(big)} "
                "(scale_multiplier) ; le résultat l'est aussi, pas en chiffres entiers.",
            )
        )


def refusal_error(findings: Findings) -> InvalidInput:
    return InvalidInput(
        client._m(
            "The query was refused before it ran, because its result would be wrong: ",
            "La requête a été refusée avant son exécution, car son résultat serait faux : ",
        )
        + " ".join(findings.refusals)
    )

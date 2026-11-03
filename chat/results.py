# ============================================================
# MapleStats chat demo: data and sources behind an answer
# Author: Daniel Sanchez
# Purpose: Turn the MCP tool results of one turn into the series, table rows and
#          sources the page draws under the answer. The numbers come from the
#          tool results, never from the model's text, so the chart and the table
#          show what the data server returned even when the answer misquotes it.
# Inputs:  (tool name, structured result) pairs collected by either backend
# Outputs: {"data": [series...], "sources": [source...]}
# ============================================================

import json
from typing import Any

# A page that draws more than this is not a chat answer any more.
MAX_SERIES = 8
MAX_POINTS = 500


def parse_result(raw: Any) -> dict[str, Any] | None:
    """A tool result as a dict: structured content, or the JSON text FastMCP writes."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, RecursionError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def text_of(content: Any) -> str:
    """Join the text blocks of an MCP tool result (SDK objects or plain dicts)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        text = (
            block.get("text")
            if isinstance(block, dict)
            else getattr(block, "text", None)
        )
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _points(observations: Any) -> list[dict[str, Any]]:
    """[{period, value, status}] from WDS (ref_period) or SDMX (period) rows."""
    points = []
    for row in observations if isinstance(observations, list) else []:
        if not isinstance(row, dict):
            continue
        period = row.get("ref_period") or row.get("period")
        if not isinstance(period, str):
            continue
        # As published, like the answer quotes it; the scale label goes with the unit.
        value = _number(row.get("value"))
        status = row.get("status")
        points.append(
            {
                "period": period[:10],
                "value": value,
                "status": status
                if isinstance(status, str) and status != "normal"
                else None,
            }
        )
    points.sort(key=lambda p: p["period"])
    return points[-MAX_POINTS:]


def _series_entry(item: dict[str, Any], caveats: list[str]) -> dict[str, Any] | None:
    points = _points(item.get("observations"))
    if not points:
        return None
    context = item.get("context") if isinstance(item.get("context"), dict) else {}
    vector = item.get("vector_id")
    title = (
        context.get("series_title")
        or context.get("table_title")
        or (f"Vector v{vector}" if vector else "Series")
    )
    releases = [
        row.get("release_time")
        for row in item.get("observations") or []
        if isinstance(row, dict) and isinstance(row.get("release_time"), str)
    ]
    return {
        "title": str(title).replace(";", " · "),
        "vector_id": f"v{vector}" if vector else None,
        "table_id": context.get("table_id"),
        "table_title": context.get("table_title"),
        "table_url": context.get("table_url"),
        "unit": context.get("unit"),
        "scale": context.get("scale")
        if context.get("scale") not in (None, "units")
        else None,
        "geography": context.get("geography"),
        "frequency": context.get("frequency"),
        # The date only: WDS release times are 8:30 a.m. Eastern, sent as UTC.
        "release": (
            max(releases) if releases else context.get("table_release_time") or ""
        )[:10]
        or None,
        "notes": [n for n in context.get("notes") or [] if isinstance(n, str)],
        "caveats": caveats,
        "points": points,
    }


def _valet_series(payload: dict[str, Any], caveats: list[str]) -> list[dict[str, Any]]:
    """Bank of Canada Valet results: {series: {name: meta}, observations: [{ref_date, values}]}."""
    found = []
    for name, meta in payload["series"].items():
        meta = meta if isinstance(meta, dict) else {}
        points = [
            {
                "period": row["ref_date"][:10],
                "value": _number(row["values"].get(name)),
                "status": None,
            }
            for row in payload.get("observations") or []
            if isinstance(row, dict)
            and isinstance(row.get("values"), dict)
            and isinstance(row.get("ref_date"), str)
        ]
        if not points:
            continue
        points.sort(key=lambda p: p["period"])
        found.append(
            {
                "title": meta.get("label") or name,
                "vector_id": name,
                "table_id": "Bank of Canada Valet",
                "table_title": meta.get("description"),
                "table_url": f"https://www.bankofcanada.ca/valet/observations/{name}",
                "unit": meta.get("unit"),
                "scale": None,
                "geography": "Canada",
                "frequency": meta.get("frequency"),
                "release": None,
                "notes": [],
                "caveats": caveats,
                "points": points[-MAX_POINTS:],
            }
        )
    return found


_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "janvier"),
            ("february", "fevrier", "février"),
            ("march", "mars"),
            ("april", "avril"),
            ("may", "mai"),
            ("june", "juin"),
            ("july", "juillet"),
            ("august", "aout", "août"),
            ("september", "septembre"),
            ("october", "octobre"),
            ("november", "novembre"),
            ("december", "decembre", "décembre"),
        ),
        start=1,
    )
    for name in names
}


def _cmhc_period(label: Any) -> str | None:
    """ "2025 October" or "2025 octobre" as 2025-10-01, "2025" as 2025-01-01; else None."""
    if not isinstance(label, str):
        return None
    parts = label.strip().split()
    if not parts or not (len(parts[0]) == 4 and parts[0].isdigit()):
        return None
    if len(parts) == 1:
        return f"{parts[0]}-01-01"
    month = _MONTHS.get(parts[1].casefold()) if len(parts) == 2 else None
    return f"{parts[0]}-{month:02d}-01" if month else None


def _cmhc_series(payload: dict[str, Any], caveats: list[str]) -> list[dict[str, Any]]:
    """CMHC HMIP tables (cmhc_get_table_data) with row_field TIMESERIES: one series per column.

    A cross-tabulation (rows are provinces or centres, not periods) is left to the
    Sources tab: its rows are not a time axis to chart.
    """
    if payload.get("row_field") != "TIMESERIES":
        return []
    rows = [r for r in payload.get("rows") or [] if isinstance(r, dict)]
    periods = [_cmhc_period(r.get("period")) for r in rows]
    if not rows or None in periods:
        return []
    provenance = payload.get("provenance") or {}
    geography = payload.get("geography_name")
    measure = payload.get("category_level_2")
    found = []
    for column in payload.get("columns") or []:
        points = []
        for row, period in zip(rows, periods, strict=True):
            cell = (row.get("values") or {}).get(column)
            if not isinstance(cell, dict):
                continue
            value = _number(cell.get("value"))
            flag = cell.get("flag")
            points.append(
                {
                    "period": period,
                    "value": value,
                    # a-d are reliability grades; a missing value keeps its marker ("**").
                    "status": flag if value is None and isinstance(flag, str) else None,
                }
            )
        if not any(p["value"] is not None for p in points):
            continue
        points.sort(key=lambda p: p["period"])
        found.append(
            {
                "title": " · ".join(str(x) for x in (geography, measure, column) if x),
                "vector_id": None,
                "table_id": f"CMHC {payload.get('table_id')}",
                "table_title": payload.get("table_name"),
                "table_url": provenance.get("url"),
                "unit": measure,
                "scale": None,
                "geography": geography,
                "frequency": None,
                "release": None,
                "notes": [n for n in payload.get("notes") or [] if isinstance(n, str)][
                    :3
                ],
                "caveats": caveats,
                "points": points[-MAX_POINTS:],
            }
        )
    return found


def series_in(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every chartable series in one tool result (WDS, SDMX, Valet and CMHC shapes)."""
    provenance = (
        payload.get("provenance") if isinstance(payload.get("provenance"), dict) else {}
    )
    caveats = [c for c in provenance.get("caveats") or [] if isinstance(c, str)]
    if isinstance(payload.get("series"), dict):
        return _valet_series(payload, caveats)
    if isinstance(payload.get("rows"), list) and "columns" in payload:
        return _cmhc_series(payload, caveats)
    items = (
        payload.get("series") if isinstance(payload.get("series"), list) else [payload]
    )
    found = []
    for item in items:
        if isinstance(item, dict):
            entry = _series_entry(item, caveats)
            if entry is not None:
                found.append(entry)
    return found


def source_of(tool: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """The publisher, URL, date and licence of any tool result that carries provenance."""
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("url"), str):
        return None
    return {
        "tool": tool,
        "source": provenance.get("source"),
        "url": provenance["url"],
        "as_of": provenance.get("as_of"),
        "licence": provenance.get("licence"),
    }


def collect(calls: list[tuple[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Series and sources for one turn, from (tool name, raw result) pairs, in call order.

    Discovery tools (search_tools, plan_query) carry no provenance and add nothing.
    A series returned twice (the model re-fetched it) is kept once, at its last fetch.
    """
    data: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for tool, raw in calls:
        payload = parse_result(raw)
        if payload is None:
            continue
        for entry in series_in(payload):
            key = entry["vector_id"] or f"{entry['table_id']}:{entry['title']}"
            data.pop(key, None)
            data[key] = entry
        source = source_of(tool, payload)
        if source is not None:
            sources[source["url"] + "|" + tool] = source
    return {
        "data": list(data.values())[-MAX_SERIES:],
        "sources": list(sources.values()),
    }

"""Helpers for SDMX REST APIs built on the .Stat Suite (NSI web service).

Pure functions, no HTTP: a module fetches the structure (SDMX-JSON 1.0, with
`references=all&detail=referencepartial`) and the data (SDMX-CSV 2.0 with
`labels=both`) itself, under its own rate limits and cache, and hands the
payloads here. Used by the ILOSTAT (sdmx.ilo.org) and ABS (data.api.abs.gov.au)
modules, whose answers have the same shape as the OECD's (sdmx.oecd.org); the
OECD module predates this file and keeps its own copy.

What the parsing relies on, checked live on 2026-11-08 against sdmx.ilo.org:

- The structure answer holds the dataflow, its data structure (dimensions
  in key order, each with a codelist URN), the codelists, the concept
  schemes and an "Actual" content constraint whose cube region lists the
  codes that have data in each dimension.
- SDMX-CSV 2.0 with `labels=both` writes headers like "REF_AREA: Reference
  area" and cells like "CAN: Canada" ("0: Units" for a multiplier); one row
  per observation, unsorted. The observation value column is OBS_VALUE.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from typing import Any

from maplestats_mcp.shared.envelope import raise_localized
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.json_utils import list_or_empty

# SDMX reporting periods: 2026, 2026-Q1, 2026-S1, 2026-09, 2026-M09, 2026-09-30.
PERIOD = re.compile(r"^\d{4}(-(Q[1-4]|S[12]|A1|W\d{2}|M?\d{2}(-\d{2})?))?$")
_CODE = r"[A-Za-z0-9_@\-]+"
_KEY_PART = re.compile(rf"^(\*|{_CODE}(\+{_CODE})*)?$")


class SdmxFormatError(ValueError):
    """An answer that is not the SDMX shape expected; the calling module turns
    it into a localized UpstreamError naming its source."""


@dataclass
class Dim:
    """A key dimension: its id, its concept name, and the codes with data."""

    id: str
    name: str
    codes: list[tuple[str, str]]
    constrained: bool

    def code_ids(self) -> list[str]:
        return [code for code, _ in self.codes]


@dataclass
class Structure:
    name: str
    version: str
    dimensions: list[Dim]
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass
class Series:
    """One series of a data answer: its dimension codes and labels, its
    series-level attributes (code, label) and its observations, oldest first."""

    dims: list[tuple[str, str, str]]
    attributes: dict[str, tuple[str, str]]
    observations: list[tuple[str, float, str | None]]

    @property
    def key(self) -> str:
        return ".".join(code for _, code, _ in self.dims)

    def dim(self, dim_id: str) -> tuple[str, str] | None:
        return next(((code, label) for d, code, label in self.dims if d == dim_id), None)


def urn_key(urn: str) -> str:
    """'urn:...Codelist=ILO:CL_AREA(1.0)' -> 'ILO:CL_AREA(1.0)'."""
    return urn.split("=", 1)[-1]


def _constraint_values(data: dict[str, Any], fid: str) -> dict[str, list[str]]:
    """Codes with data per dimension, from the dataflow's "Actual" constraints.

    The ABS (data.api.abs.gov.au, checked 2026-11-08) sends two, one per
    release version (CR_A_CPI current, CR_B_CPI previous); their codes are
    merged, in first-seen order.
    """
    constraints = [c for c in list_or_empty(data, "contentConstraints") if isinstance(c, dict)]
    chosen = [
        c
        for c in constraints
        if c.get("type") == "Actual"
        and (
            str(c.get("id") or "").endswith(fid)
            or any(
                f":{fid}(" in str(u)
                for u in list_or_empty(c.get("constraintAttachment") or {}, "dataflows")
            )
        )
    ] or (constraints if len(constraints) == 1 else [])
    values: dict[str, list[str]] = {}
    for constraint in chosen:
        for region in list_or_empty(constraint, "cubeRegions"):
            if not isinstance(region, dict) or region.get("isIncluded") is False:
                continue
            for kv in list_or_empty(region, "keyValues"):
                if isinstance(kv, dict) and kv.get("id") and kv.get("values"):
                    codes = values.setdefault(str(kv["id"]), [])
                    codes.extend(str(v) for v in kv["values"] if str(v) not in codes)
    return values


def parse_structure(payload: Any, fid: str) -> Structure:
    """Dimensions in key order with the codes that have data, from an SDMX-JSON
    structure answer. Raises SdmxFormatError when the answer has no structure."""
    data = (payload or {}).get("data") or {} if isinstance(payload, dict) else {}
    flow = next(
        (
            f
            for f in list_or_empty(data, "dataflows")
            if isinstance(f, dict) and str(f.get("id") or "") == fid
        ),
        next((f for f in list_or_empty(data, "dataflows") if isinstance(f, dict)), {}),
    )
    wanted = urn_key(str(flow.get("structure") or ""))
    structures = [s for s in list_or_empty(data, "dataStructures") if isinstance(s, dict)]
    dsd = next(
        (
            s
            for s in structures
            if f"{s.get('agencyID')}:{s.get('id')}({s.get('version')})" == wanted
        ),
        structures[0] if len(structures) == 1 else None,
    )
    if dsd is None:
        raise SdmxFormatError(f"{fid}: the structure answer has no data structure {wanted}.")
    codelists = {
        f"{c.get('agencyID')}:{c.get('id')}({c.get('version')})": c
        for c in list_or_empty(data, "codelists")
        if isinstance(c, dict)
    }
    concepts: dict[str, str] = {}
    for scheme in list_or_empty(data, "conceptSchemes"):
        for concept in list_or_empty(scheme, "concepts"):
            if isinstance(concept, dict) and concept.get("id"):
                concepts.setdefault(str(concept["id"]), str(concept.get("name") or ""))
    used = _constraint_values(data, fid)
    components = dsd.get("dataStructureComponents") or {}
    dims = [
        d
        for d in list_or_empty(components.get("dimensionList") or {}, "dimensions")
        if isinstance(d, dict)
    ]
    dimensions: list[Dim] = []
    for dim in sorted(dims, key=lambda d: int(d.get("position") or 0)):
        dim_id = str(dim.get("id") or "")
        enumeration = (dim.get("localRepresentation") or {}).get("enumeration") or ""
        names = {
            str(c["id"]): str(c.get("name") or c["id"])
            for c in list_or_empty(codelists.get(urn_key(enumeration)) or {}, "codes")
            if isinstance(c, dict) and c.get("id")
        }
        ids = used.get(dim_id)
        dimensions.append(
            Dim(
                id=dim_id,
                name=concepts.get(dim_id) or dim_id,
                codes=[(code, names.get(code, code)) for code in (ids or list(names))],
                constrained=ids is not None,
            )
        )
    if not dimensions:
        raise SdmxFormatError(f"{fid}: the data structure lists no dimensions.")
    annotations = {
        str(a.get("type")): str(a.get("title") or "")
        for a in list_or_empty(flow, "annotations")
        if isinstance(a, dict) and a.get("type")
    }
    return Structure(
        name=str(flow.get("name") or fid),
        version=str(flow.get("version") or ""),
        dimensions=dimensions,
        annotations=annotations,
    )


def check_periods(
    start_period: str | None,
    end_period: str | None,
    last_n: int | None,
    max_last_n: int,
    lang: str,
) -> None:
    for name, value in (("start_period", start_period), ("end_period", end_period)):
        if value is not None and not PERIOD.match(value.strip()):
            raise_localized(
                InvalidInput,
                f"{name} {value!r} is not an SDMX period (2026, 2026-Q1, 2026-09 or 2026-09-30).",
                f"{name} {value!r} n'est pas une période SDMX (2026, 2026-Q1, 2026-09 ou "
                "2026-09-30).",
                lang,
            )
    if last_n is not None and not 1 <= last_n <= max_last_n:
        raise_localized(
            InvalidInput,
            f"last_n must be between 1 and {max_last_n}.",
            f"last_n doit être compris entre 1 et {max_last_n}.",
            lang,
        )


def data_params(
    start_period: str | None, end_period: str | None, last_n: int | None
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if start_period:
        params["startPeriod"] = start_period.strip()
    if end_period:
        params["endPeriod"] = end_period.strip()
    if last_n is not None:
        params["lastNObservations"] = last_n
    return params


def example_key(dimensions: list[Dim], area: str) -> str:
    """A key for `area` where a dimension has it, the only code of a one-code
    dimension, a wildcard (empty part) elsewhere."""
    parts = []
    for dim in dimensions:
        ids = dim.code_ids()
        if area in ids:
            parts.append(area)
        elif len(ids) == 1:
            parts.append(ids[0])
        else:
            parts.append("")
    return ".".join(parts)


def check_key(
    key: str,
    dimensions: list[Dim],
    fid: str,
    describe_tool: str,
    area: str,
    lang: str,
) -> str:
    """Normalise `key` (code case, `*` as a wildcard) and check each code against
    the codes with data, so a typo fails here with the valid codes instead of
    upstream (ILOSTAT answers an unknown area with HTTP 500)."""
    template = ".".join(d.id for d in dimensions)
    example = example_key(dimensions, area)
    parts = key.strip().split(".")
    if len(parts) != len(dimensions) or not all(_KEY_PART.match(p.strip()) for p in parts):
        raise_localized(
            InvalidInput,
            f"{key!r} is not a key for {fid}: it needs {len(dimensions)} parts in the order "
            f"{template}, each a code, codes joined by +, empty (or *) for all (e.g. "
            f"{example!r}). {describe_tool} lists the codes.",
            f"{key!r} n'est pas une clé de {fid} : il faut {len(dimensions)} parties dans "
            f"l'ordre {template}, chacune un code, des codes joints par +, vide (ou *) pour "
            f"tous (p. ex. {example!r}). {describe_tool} donne les codes.",
            lang,
        )
    normalised = []
    for part, dim in zip(parts, dimensions, strict=True):
        part = part.strip()
        if part in ("", "*"):
            normalised.append("")
            continue
        known = {code.upper(): code for code in dim.code_ids()}
        codes = []
        for code in part.split("+"):
            canonical = known.get(code.upper())
            if canonical is None and dim.constrained:
                ids = dim.code_ids()
                sample = ", ".join(ids[:20]) + ("…" if len(ids) > 20 else "")
                raise_localized(
                    InvalidInput,
                    f"{code} is not a {dim.id} code with data in {fid}. Codes: {sample} "
                    f"({describe_tool} lists them all).",
                    f"{code} n'est pas un code {dim.id} ayant des données dans {fid}. Codes : "
                    f"{sample} ({describe_tool} les énumère tous).",
                    lang,
                )
            codes.append(canonical or code)
        normalised.append("+".join(codes))
    return ".".join(normalised)


def max_series(key: str, dimensions: list[Dim]) -> int:
    """Upper bound on the number of series a key can match (codes with data)."""
    total = 1
    for part, dim in zip(key.split("."), dimensions, strict=True):
        total *= len(part.split("+")) if part else max(1, len(dim.codes))
    return total


def split_label(cell: str) -> tuple[str, str]:
    """'CAN: Canada' -> ('CAN', 'Canada'); '0: ' -> ('0', '0')."""
    code, sep, label = cell.partition(":")
    code, label = code.strip(), label.strip()
    return (code, label or code) if sep else (cell.strip(), cell.strip())


def parse_csv(text: str, dimensions: list[Dim], attributes: tuple[str, ...]) -> list[Series]:
    """Series from an SDMX-CSV 2.0 (labels=both) answer, observations sorted by
    period. Rows without a numeric value are left out; `attributes` are read
    from the first row of each series that has them."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header:
        return []
    columns = [h.split(":", 1)[0].strip() for h in header]
    index = {c: i for i, c in enumerate(columns)}
    dim_ids = [d.id for d in dimensions]
    if (
        "TIME_PERIOD" not in index
        or "OBS_VALUE" not in index
        or any(d not in index for d in dim_ids)
    ):
        raise SdmxFormatError(f"unexpected SDMX-CSV columns: {', '.join(columns)}")
    series: dict[tuple[str, ...], Series] = {}
    for row in reader:
        if len(row) < len(columns):
            row = row + [""] * (len(columns) - len(row))
        period = row[index["TIME_PERIOD"]].strip()
        if not period:
            continue
        values = [split_label(row[index[d]]) for d in dim_ids]
        codes = tuple(code for code, _ in values)
        entry = series.get(codes)
        if entry is None:
            entry = series[codes] = Series(
                dims=[(d, code, label) for d, (code, label) in zip(dim_ids, values, strict=True)],
                attributes={},
                observations=[],
            )
        for name in attributes:
            cell = row[index[name]].strip() if name in index else ""
            if cell and name not in entry.attributes:
                entry.attributes[name] = split_label(cell)
        try:
            value = float(row[index["OBS_VALUE"]].strip())
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        status_cell = row[index["OBS_STATUS"]].strip() if "OBS_STATUS" in index else ""
        entry.observations.append(
            (period, value, split_label(status_cell)[1] if status_cell else None)
        )
    result = [s for s in series.values() if s.observations]
    for s in result:
        s.observations.sort(key=lambda o: o[0])
    result.sort(key=lambda s: s.key)
    return result

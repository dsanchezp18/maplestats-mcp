"""oecd_query_dataset: one read-only SQL query over a slice of an OECD dataset.

oecd_get_data returns up to 200 series and 10,000 rows. A question across a
dataset's breadth ("every member's unemployment rate by age, ranked") needs more;
here the server reads the slice asked for (codes per dimension in `filters`, and the
periods) from the OECD's SDMX API as SDMX-CSV, the same answer oecd_get_data reads,
and hands it to shared/sdmx_query.py, which loads it as `obs`, checks the query and
runs it. Nothing is cached: the slice lives for the call.

The OECD's codelists give parent codes for areas, ISIC activities, COICOP, sectors and
national-accounts transactions (checked live 2026-11-20 on DSD_LFS@DF_IALFS_INDIC,
DSD_PRICES@DF_PRICES_ALL and DSD_NAMAIN10@DF_TABLE1_EXPENDITURE); oecd/client.py's
structure keeps them, and the check of a total summed with its own parts reads them.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from maplestats_mcp.modules.oecd import client, constants
from maplestats_mcp.modules.oecd.schemas import DatasetQueryResult
from maplestats_mcp.shared import sdmx_query
from maplestats_mcp.shared.envelope import raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError
from maplestats_mcp.shared.i18n import fr_number, pick
from maplestats_mcp.shared.limits import join_limits

# Series a slice may span before the download: the product of the codes kept per
# dimension (all codes with data where a dimension is not named). Each query spends
# one of the OECD's hourly downloads (client.BUDGET) whatever its size.
MAX_QUERY_SERIES = 20_000

_ROLES = {
    "REF_AREA": "geo",
    "UNIT_MEASURE": "unit",
    "FREQ": "freq",
    "ADJUSTMENT": "adjustment",
}


def _key(
    filters: Mapping[str, Sequence[str] | str] | None,
    dimensions: list[dict[str, Any]],
    fid: str,
    lang: str,
) -> str:
    """An SDMX key from `filters` (dimension id -> codes), checked against the structure."""
    by_id = {d["id"].upper(): d for d in dimensions}
    parts = {d["id"]: "" for d in dimensions}
    for raw, codes in (filters or {}).items():
        dim = by_id.get(str(raw).strip().upper())
        if dim is None:
            raise_localized(
                InvalidInput,
                f"{fid} has no dimension {raw!r}. Dimensions: "
                f"{', '.join(d['id'] for d in dimensions)}.",
                f"{fid} n'a pas de dimension {raw!r}. Dimensions : "
                f"{', '.join(d['id'] for d in dimensions)}.",
                lang,
            )
        wanted = [codes] if isinstance(codes, str) else list(codes)
        parts[dim["id"]] = "+".join(c.strip() for c in wanted if c and c.strip())
    return client._check_key(".".join(parts[d["id"]] for d in dimensions), dimensions, fid, lang)


def _int(code: str) -> int | None:
    try:
        return int(code)
    except ValueError:
        return None


def _parse(
    text: str, dimensions: list[dict[str, Any]], lang: str
) -> tuple[list[sdmx_query.SliceDimension], list[sdmx_query.SliceSeries]]:
    """The SDMX-CSV answer (labels=both) as the slice's dimensions and series.

    Unlike oecd_get_data, an observation with no value is kept when it carries a status
    (confidential, missing), so the query's nulls warning can count it.
    """
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header:
        return [], []
    columns = [h.split(":", 1)[0].strip() for h in header]
    index = {c: i for i, c in enumerate(columns)}
    dim_ids = [d["id"] for d in dimensions]
    if (
        "TIME_PERIOD" not in index
        or "OBS_VALUE" not in index
        or any(d not in index for d in dim_ids)
    ):
        raise UpstreamError(f"unexpected SDMX-CSV columns: {', '.join(columns)}")
    labels: dict[str, dict[str, str]] = {
        d["id"]: {str(c): str(n) for c, n in d["codes"]} for d in dimensions
    }

    def cell(row: list[str], name: str) -> tuple[str, str] | None:
        raw = row[index[name]].strip() if name in index and index[name] < len(row) else ""
        return client._split(raw) if raw else None

    series: dict[tuple[str, ...], sdmx_query.SliceSeries] = {}
    for row in reader:
        period = row[index["TIME_PERIOD"]].strip() if index["TIME_PERIOD"] < len(row) else ""
        if not period:
            continue
        pairs = [client._split(row[index[d]]) for d in dim_ids]
        codes = tuple(code for code, _ in pairs)
        for d, (code, label) in zip(dim_ids, pairs, strict=True):
            labels[d].setdefault(code, label)
        entry = series.get(codes)
        if entry is None:
            unit = cell(row, "UNIT_MEASURE")
            mult = cell(row, "UNIT_MULT")
            decimals = cell(row, "DECIMALS")
            entry = series[codes] = sdmx_query.SliceSeries(
                codes=codes,
                observations=[],
                unit=unit[1] if unit else None,
                unit_multiplier=_int(mult[0]) if mult else None,
                scale=mult[1] if mult else None,
                decimals=_int(decimals[0]) if decimals else None,
            )
        raw = row[index["OBS_VALUE"]].strip() if index["OBS_VALUE"] < len(row) else ""
        try:
            value: float | None = float(raw)
        except ValueError:
            value = None
        if value is not None and not math.isfinite(value):
            value = None
        status = cell(row, "OBS_STATUS")
        confidential = cell(row, "CONF_STATUS")
        if value is None and status is None and confidential is None:
            continue
        quality = (
            "x"
            if confidential and confidential[0] in ("C", "D", "S")
            else "E"
            if status and status[0] == "U"
            else None
        )
        entry.observations.append(
            sdmx_query.SliceObservation(
                period=period, value=value, status=status[1] if status else None, quality=quality
            )
        )
    dims = [
        sdmx_query.SliceDimension(
            id=d["id"],
            name=str(d.get("name") or d["id"]),
            labels=labels[d["id"]],
            parents=dict(d.get("parents") or {}),
            role=_ROLES.get(d["id"]),
        )
        for d in dimensions
    ]
    return dims, [s for s in series.values() if s.observations]


async def query_dataset(
    dataset: str,
    sql: str,
    filters: Mapping[str, Sequence[str] | str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    lang: str = "en",
) -> DatasetQueryResult:
    """Read the slice, check `sql` (query_checks.py), run it, return the result."""
    lang = client._lang(lang)
    sdmx_query.wds_client.use_lang(lang)
    text = sdmx_query.check_sql(sql)
    client._check_periods(start_period, end_period, None, lang)
    fid, info = await client._dataflow(dataset, lang)
    structure, _ = await client._structure(fid, info, lang)
    dimensions = structure["dimensions"]
    key = _key(filters, dimensions, fid, lang)
    bound = client._max_series(key, dimensions)
    if bound > MAX_QUERY_SERIES:
        open_dims = ", ".join(
            f"{d['id']} ({len(d['codes'])} codes)"
            for d, part in zip(dimensions, key.split("."), strict=True)
            if not part and len(d["codes"]) > 1
        )
        raise_localized(
            InvalidInput,
            f"{fid}: this slice can span up to {bound:,} series (limit {MAX_QUERY_SERIES:,}). "
            f"Name codes in filters for: {open_dims}. oecd_describe_dataset lists the codes.",
            f"{fid} : cette tranche peut compter jusqu'à {fr_number(bound)} séries (limite "
            f"{fr_number(MAX_QUERY_SERIES)}). Précisez des codes dans filters pour : "
            f"{open_dims}. oecd_describe_dataset donne les codes.",
            lang,
        )
    known = [
        sdmx_query.SliceDimension(id=d["id"], name=d["id"], labels={c: c for c, _ in d["codes"]})
        for d in dimensions
        if d["constrained"]
    ]
    sdmx_query.check_codes(text, known, sdmx_query.dimension_columns(known), lang)
    params = client._data_params(start_period, end_period, None)
    url = client._data_url(info["agency"], fid, key)
    response = await client._get(
        url,
        params,
        accept=constants.DATA_ACCEPT,
        timeout=constants.DATA_TIMEOUT_SECONDS,
        not_found=(
            f"No data in OECD dataset {fid} for key {key!r}"
            + (" in the periods asked for" if params else "")
            + ". Check the codes with oecd_describe_dataset.",
            f"aucune donnée dans le jeu {fid} de l'OCDE pour la clé {key!r}"
            + (" pour les périodes demandées" if params else "")
            + ". Vérifiez les codes avec oecd_describe_dataset.",
        ),
        lang=lang,
        data=True,
    )
    try:
        dims, series = _parse(response.text, dimensions, lang)
    except UpstreamError as exc:
        raise_localized(
            UpstreamError, f"{fid}: {exc}", f"{fid} : colonnes SDMX-CSV inattendues.", lang
        )
    if not series:
        raise_localized(
            NotFound,
            f"OECD dataset {fid} has no values for key {key!r} in the periods asked for.",
            f"le jeu {fid} de l'OCDE n'a aucune valeur pour la clé {key!r} pour les périodes "
            "demandées.",
            lang,
        )
    title = str(structure["name"])
    outcome = await sdmx_query.run(
        sql=text, dataset=fid, dataset_title=title, dims=dims, series=series, lang=lang
    )
    limits = pick(
        lang,
        f"at most {sdmx_query.MAX_ROWS:,} observations in obs, {MAX_QUERY_SERIES:,} series in "
        "the slice and 500 rows in the result",
        f"au plus {fr_number(sdmx_query.MAX_ROWS)} observations dans obs, "
        f"{fr_number(MAX_QUERY_SERIES)} séries dans la tranche et 500 lignes dans le résultat",
    )
    if outcome.truncated:
        limits = (
            join_limits(
                limits, pick(lang, "result truncated at the row cap", "résultat tronqué au plafond")
            )
            or limits
        )
    provenance = client._data_provenance(
        fid, info, key, params, structure, False, "oecd.DatasetQueryResult", lang, limits
    )
    filters_kept = {
        d["id"]: part.split("+") for d, part in zip(dimensions, key.split("."), strict=True) if part
    }
    return DatasetQueryResult(
        sql=outcome.sql,
        columns=outcome.columns,
        column_types=outcome.column_types,
        rows=outcome.rows,
        row_count=len(outcome.rows),
        truncated=outcome.truncated,
        input_rows=outcome.input_rows,
        dataset=fid,
        dataset_title=title,
        citation=client._citation(fid, info, structure, lang),
        dimension_columns=outcome.dimension_columns,
        filters=filters_kept,
        warnings=outcome.warnings,
        notes=[
            pick(
                lang,
                f"The same slice as CSV: {httpx.URL(url, params={**params, 'format': 'csvfilewithlabels'})}",
                "La même tranche en CSV : "
                f"{httpx.URL(url, params={**params, 'format': 'csvfilewithlabels'})}",
            )
        ],
        provenance=provenance,
    )

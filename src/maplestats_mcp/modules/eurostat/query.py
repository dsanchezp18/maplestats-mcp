"""eurostat_query_dataset: one read-only SQL query over a slice of a Eurostat dataset.

eurostat_get_data returns up to 400 series as rows. A question across a dataset's
breadth ("each region's employment by sex since 2015, ranked") needs more; here the
server reads the slice asked for (codes per dimension in `filters` and `geo`, and the
periods) from Eurostat's statistics API, the same JSON-stat answer eurostat_get_data
reads, and hands it to shared/sdmx_query.py, which loads it as `obs`, checks the query
and runs it. Nothing is cached: the slice lives for the call.

Eurostat's codelists carry no parent codes (checked live 2026-11-20 on nama_10_gdp,
lfsq_egan2, demo_r_pjangroup and une_rt_m, and the full GEO, NACE_R2, AGE, SEX and
NA_ITEM codelists), so the check of a total summed with its own parts reads the
hierarchy from the codes themselves (sdmx_query's docstring says how).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from maplestats_mcp.modules.eurostat import client, constants
from maplestats_mcp.modules.eurostat.schemas import DatasetQueryResult
from maplestats_mcp.shared import sdmx_query
from maplestats_mcp.shared.envelope import make_provenance, raise_localized
from maplestats_mcp.shared.errors import InvalidInput, NotFound, UpstreamError, UpstreamUnavailable
from maplestats_mcp.shared.i18n import fr_number, normalize_lang, pick
from maplestats_mcp.shared.limits import join_limits

# Series a slice may span before the download: the product of the codes kept per
# dimension (all codes with data where a dimension is not named). The rows are capped
# again after it (sdmx_query.MAX_ROWS). 11,700 series (every region by age, one sex,
# one year) took 5 s live on 2026-11-20.
MAX_QUERY_SERIES = 20_000

_ROLES = {"geo": "geo", "unit": "unit", "freq": "freq", "s_adj": "adjustment"}


def _quality(flag: str | None) -> str | None:
    """'x' for a confidential value (flag c), 'E' for low reliability (flag u)."""
    if not flag:
        return None
    if "c" in flag:
        return "x"
    if "u" in flag:
        return "E"
    return None


async def _fetch(code: str, params: list[tuple[str, str]], lang: str) -> dict[str, Any]:
    """The slice as client._parse_jsonstat reads it, fetched without the response cache."""
    response = await client._get(
        client._data_url(code),
        params,
        constants.DATA_TIMEOUT_SECONDS,
        (
            f"{code} is not a Eurostat dataset, or has no data for this query.",
            (
                f"{code} n'est pas un jeu de données d'Eurostat, ou n'a pas de données pour "
                "cette requête."
            ),
        ),
        lang,
    )
    try:
        payload = response.json()
    except ValueError:
        raise_localized(
            UpstreamError,
            f"{code}: Eurostat's answer is not JSON.",
            f"{code} : la réponse d'Eurostat n'est pas du JSON.",
            lang,
        )
    try:
        return client._parse_jsonstat(payload if isinstance(payload, dict) else {})
    except UpstreamUnavailable:
        raise_localized(
            UpstreamUnavailable,
            f"Eurostat queued the {code} request for asynchronous processing (it is busy, or "
            "the slice is large). Name more codes in filters, narrow the periods, or try again "
            "in a few minutes.",
            f"Eurostat a mis la requête {code} en file d'attente asynchrone (service chargé ou "
            "tranche volumineuse). Précisez des codes dans filters, réduisez les périodes, ou "
            "réessayez dans quelques minutes.",
            lang,
        )
    except UpstreamError as exc:
        raise_localized(
            UpstreamError,
            f"{code}: {exc}.",
            f"{code} : réponse JSON-stat incohérente.",
            lang,
        )


def _slice(
    structure: dict[str, Any], parsed: dict[str, Any], lang: str
) -> tuple[list[sdmx_query.SliceDimension], list[sdmx_query.SliceSeries], set[str]]:
    """The answer's dimensions (time aside) and its series, with labels and flags."""
    by_id = {d["id"].lower(): d for d in structure["dimensions"]}
    ids = [i for i in parsed["ids"] if i.lower() not in ("time", "time_period")]
    dims = []
    for dim_id in ids:
        known = by_id.get(dim_id.lower(), {})
        labels = {c: client._label(n, lang) or c for c, n in known.get("codes", [])}
        codes, data_labels = parsed["categories"][dim_id]
        for c in codes:
            labels[c] = data_labels.get(c) or labels.get(c) or c
        dims.append(
            sdmx_query.SliceDimension(
                id=dim_id,
                name=client._label(known.get("names", {}), lang) or dim_id,
                labels=labels,
                role=_ROLES.get(dim_id.lower()),
            )
        )
    time_id = next((i for i in parsed["ids"] if i.lower() in ("time", "time_period")), "time")
    series: dict[tuple[str, ...], sdmx_query.SliceSeries] = {}
    geos: set[str] = set()
    for codes, value, flag in parsed["cells"]:
        key = tuple(codes[i] for i in ids)
        entry = series.setdefault(key, sdmx_query.SliceSeries(codes=key, observations=[]))
        label = client._flag_label(flag, lang, parsed["flag_labels"]) if flag else None
        entry.observations.append(
            sdmx_query.SliceObservation(
                period=str(codes.get(time_id, "")),
                value=value,
                status=label,
                quality=_quality(flag),
            )
        )
        if "geo" in codes:
            geos.add(codes["geo"])
    return dims, list(series.values()), geos


async def query_dataset(
    dataset: str,
    sql: str,
    filters: Mapping[str, Sequence[str] | str] | None = None,
    geo: Sequence[str] | None = None,
    start_period: str | None = None,
    end_period: str | None = None,
    lang: str = "en",
) -> DatasetQueryResult:
    """Read the slice, check `sql` (query_checks.py), run it, return the result."""
    lang = normalize_lang(lang)
    sdmx_query.wds_client.use_lang(lang)
    text = sdmx_query.check_sql(sql)
    code = client._check_code(dataset, lang)
    client._check_periods(start_period, end_period, None, lang)
    structure, _ = await client._structure(code, lang)
    dimensions = structure["dimensions"]
    chosen = client._resolve_filters(code, filters, geo, dimensions, lang)
    bound = client._series_bound(chosen, dimensions)
    if bound > MAX_QUERY_SERIES:
        open_dims = ", ".join(
            f"{d['id']} ({len(d['codes'])} codes)"
            for d in dimensions
            if d["id"].lower() not in chosen and len(d["codes"]) > 1
        )
        raise_localized(
            InvalidInput,
            f"{code}: this slice can span up to {bound:,} series (limit {MAX_QUERY_SERIES:,}). "
            f"Name codes in filters or geo for: {open_dims}. eurostat_describe_dataset lists "
            "the codes.",
            f"{code} : cette tranche peut compter jusqu'à {fr_number(bound)} séries (limite "
            f"{fr_number(MAX_QUERY_SERIES)}). Précisez des codes dans filters ou geo pour : "
            f"{open_dims}. eurostat_describe_dataset donne les codes.",
            lang,
        )
    # A code no dimension has fails here, before the download.
    known = [
        sdmx_query.SliceDimension(
            id=d["id"], name=d["id"], labels={c: c for c, _ in d["codes"]}, role=None
        )
        for d in dimensions
    ]
    sdmx_query.check_codes(text, known, sdmx_query.dimension_columns(known), lang)
    params = client._data_params(chosen, start_period, end_period, None, lang)
    parsed = await _fetch(code, params, lang)
    if not parsed["cells"]:
        raise_localized(
            NotFound,
            f"{code} has no values for these filters and periods. eurostat_describe_dataset "
            "lists the codes with data; some combinations are still empty.",
            f"{code} n'a aucune valeur pour ces filtres et périodes. eurostat_describe_dataset "
            "donne les codes avec données ; certaines combinaisons restent vides.",
            lang,
        )
    dims, series, geos = _slice(structure, parsed, lang)
    title = parsed["label"] or client._label(structure["names"], lang) or code
    outcome = await sdmx_query.run(
        sql=text, dataset=code, dataset_title=title, dims=dims, series=series, lang=lang
    )
    use, outside = client._commercial(geos)
    notes = [client._commercial_note(outside, lang)] if outside else []
    updated = str(parsed.get("updated") or "")[:10]
    citation = pick(
        lang,
        f"Eurostat, {title} ({code})" + (f", updated {updated}." if updated else "."),
        f"Eurostat, {title} ({code})" + (f", mis à jour le {updated}." if updated else "."),
    )
    limits = pick(
        lang,
        f"at most {sdmx_query.MAX_ROWS:,} observations in obs, {MAX_QUERY_SERIES:,} series in "
        "the slice and 500 rows in the result",
        f"au plus {fr_number(sdmx_query.MAX_ROWS)} observations dans obs, "
        f"{fr_number(MAX_QUERY_SERIES)} séries dans la tranche et 500 lignes dans le résultat",
    )
    return DatasetQueryResult(
        sql=outcome.sql,
        columns=outcome.columns,
        column_types=outcome.column_types,
        rows=outcome.rows,
        row_count=len(outcome.rows),
        truncated=outcome.truncated,
        input_rows=outcome.input_rows,
        dataset=code,
        dataset_title=title,
        citation=citation,
        dimension_columns=outcome.dimension_columns,
        filters=chosen,
        warnings=outcome.warnings,
        notes=notes,
        provenance=make_provenance(
            source=constants.SOURCE,
            url=str(httpx.URL(client._data_url(code), params=params)),
            cached=False,
            schema_name="eurostat.DatasetQueryResult",
            freshness=client._FRESHNESS[lang],
            coverage=pick(
                lang,
                f"{outcome.input_rows:,} observations of {len(series):,} series loaded into obs. "
                "Cells with neither a value nor a flag are left out.",
                f"{fr_number(outcome.input_rows)} observations de {fr_number(len(series))} séries "
                "chargées dans obs. Les cellules sans valeur ni indicateur sont omises.",
            ),
            limits=join_limits(
                limits,
                pick(lang, "result truncated at the row cap", "résultat tronqué au plafond")
                if outcome.truncated
                else None,
            ),
            licence=client._licence(lang),
            commercial_use=use,
            lang=lang,
        ),
    )

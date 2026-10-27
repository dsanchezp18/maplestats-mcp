"""Specs for tools whose request can be rebuilt exactly from their arguments,
or whose filtering happens in MapleStats after the download.

Every other tool is reproduced from the requests recorded while it ran
(probe.py). A builder here is needed when that recording is not enough:
the tool downloads a whole file and filters it itself (CER,
GC InfoBase, CIHI, IRCC, StatCan indicators, PHAC Health Infobase in
phac_infobase.py, IP Horizons), the tool parses HTML tables itself (CFIA
in cfia.py), or a better
native path exists (cansim for StatCan tables).

Each builder takes the tool's arguments and its result payload (the tool
has already run) and returns a Spec.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlencode

from maplestats_mcp.modules.reproduce.render import comment_text, jl_quote
from maplestats_mcp.modules.reproduce.spec import Code, Filter, Spec
from maplestats_mcp.modules.statcan.lang import say
from maplestats_mcp.shared.errors import InvalidInput
from maplestats_mcp.shared.fr_typography import call_error
from maplestats_mcp.shared.transform import TransformRequest, parse_period, period_end

Builder = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Spec]]
_WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
_SDMX = "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/"
_EXACT = "exact: rebuilt from the tool's arguments"
_FILTERED = "exact: the source file, then the tool's filters"
# Every registered tool name matches (tests/test_reproduce.py checks it).
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*")


def _suffix(args: dict[str, Any]) -> str:
    return "eng" if str(args.get("lang", "en")) == "en" else "fra"


# StatCan --------------------------------------------------------------------


def table_spec(product_id: Any, lang: str) -> Spec:
    pid = str(product_id).replace("-", "")[:8]
    if not pid.isdigit() or len(pid) != 8:
        raise call_error(
            InvalidInput,
            f"product_id must be an 8- or 10-digit StatCan table id, got {product_id!r}.",
            "product_id doit être un identifiant de tableau de Statistique Canada à 8 ou "
            f"10 chiffres, reçu {product_id!r}.",
        )
    suffix = "eng" if lang == "en" else "fra"
    dashed = f"{pid[:2]}-{pid[2:4]}-{pid[4:8]}-01"
    language = ', language = "fr"' if lang == "fr" else ""
    return Spec(
        kind="zip_csv",
        url=f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-{suffix}.zip",
        file_name=f"{pid}-{suffix}.zip",
        method="exact: full table from the product id",
        title=f"StatCan table {dashed}",
        native={"r": Code(["cansim"], f'data <- get_cansim("{dashed}"{language})\n')},
        notes=["The full table is downloaded; filter it to the rows the tool returned."],
        # French tables name their columns in French (VALEUR, IDENTIFICATEUR SCALAIRE).
        source="statcan_table" if lang == "en" else "statcan_table_fr",
        delimiter="," if lang == "en" else ";",
    )


def _vector_id(value: Any) -> int:
    """A WDS vector id from 41690973, "41690973" or "v41690973"."""
    text = str(value).strip().lstrip("vV")
    if not text.isdigit() or int(text) < 1:
        raise call_error(
            InvalidInput,
            f"vector ids must look like 41690973 or v41690973, got {value!r}.",
            f"les identifiants de vecteur doivent ressembler à 41690973 ou v41690973, reçu {value!r}.",
        )
    return int(text)


def _count(value: Any, name: str) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise call_error(
            InvalidInput,
            f"{name} must be a whole number, got {value!r}.",
            f"{name} doit être un nombre entier, reçu {value!r}.",
        ) from exc
    if count < 1:
        raise call_error(
            InvalidInput,
            f"{name} must be >= 1, got {count}.",
            f"{name} doit être >= 1, reçu {count}.",
        )
    return count


def vector_spec(vector_ids: Any, latest_n: int) -> Spec:
    if not isinstance(vector_ids, list) or not vector_ids:
        raise call_error(
            InvalidInput,
            "vector_ids must be a non-empty list of vector ids.",
            "vector_ids doit être une liste non vide d'identifiants de vecteur.",
        )
    ids = [_vector_id(v) for v in vector_ids]
    r_ids = ", ".join(f'"v{i}"' for i in ids)
    # get_cansim_vector() alone returns each vector's whole history (1,960
    # rows for two monthly vectors, checked 2026-10-03); the tool keeps the
    # latest periods only.
    r_code = (
        f"data <- get_cansim_vector_for_latest_periods(\n  c({r_ids}),\n  periods = {latest_n}\n)\n"
    )
    return Spec(
        kind="json",
        url=_WDS + "getDataFromVectorsAndLatestNPeriods",
        file_name="vectors.json",
        method="exact: WDS vectors request from the vector ids",
        title="StatCan vectors",
        records_path=["object", "vectorDataPoint"],
        each_item=True,
        post_json=[{"vectorId": i, "latestN": latest_n} for i in ids],
        native={"r": Code(["cansim"], r_code)},
        notes=["WDS returns one object per vector; values are under vectorDataPoint."],
        source="statcan_vectors",
    )


async def _table(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    return table_spec(args["product_id"], str(args.get("lang", "en")))


def sdmx_spec(data_url: str, args: dict[str, Any], title: str) -> Spec:
    """The SDMX data request the tool makes: its key, its periods, and the
    latest-N default it applies when no period is given."""
    from maplestats_mcp.modules.statcan.sdmx.constants import DEFAULT_LAST_N, MAX_ROWS, MAX_SERIES

    start, end = args.get("start_period"), args.get("end_period")
    last_n = args.get("last_n_observations")
    if last_n not in (None, "") and (start or end):
        raise call_error(
            InvalidInput,
            "last_n_observations cannot be combined with start_period/end_period.",
            "last_n_observations ne peut pas être combiné avec start_period/end_period.",
        )
    params: dict[str, Any] = {}
    if start:
        params["startPeriod"] = start
    if end:
        params["endPeriod"] = end
    if last_n not in (None, ""):
        params["lastNObservations"] = _count(last_n, "last_n_observations")
    elif not start and not end:
        params["lastNObservations"] = DEFAULT_LAST_N
    url = f"{data_url}?{urlencode(params)}"
    return Spec(
        kind="sdmx",
        url=url,
        file_name="sdmx_data.xml",
        method="exact: the SDMX data request rebuilt from the tool's arguments",
        title=title,
        notes=[
            (
                "StatCan's SDMX service answers in SDMX-ML (XML); the script makes one row per "
                "observation, with the series key and attributes as columns."
            ),
            (
                f"The tool keeps at most {MAX_SERIES} series and the newest {MAX_ROWS} "
                "observations per series; the script keeps every row StatCan returns."
            ),
        ],
    )


async def _sdmx_data(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.statcan.sdmx.client import _KEY

    pid = str(args["product_id"]).replace("-", "")[:8]
    if not pid.isdigit() or len(pid) != 8:
        raise call_error(
            InvalidInput,
            f"product_id must be an 8- or 10-digit StatCan table id, got {args['product_id']!r}.",
            "product_id doit être un identifiant de tableau de Statistique Canada à 8 ou "
            f"10 chiffres, reçu {args['product_id']!r}.",
        )
    key = str(args["key"])
    if not _KEY.match(key):
        raise call_error(
            InvalidInput,
            f"key {key!r} may only contain member ids, '.', and '+'.",
            f"la clé {key!r} ne peut contenir que des identifiants de membre, « . » et « + ».",
        )
    dashed = f"{pid[:2]}-{pid[2:4]}-{pid[4:8]}-01"
    title = f"StatCan table {dashed}, SDMX key {key}"
    request = transform_request(args)
    if request is not None:
        return _sdmx_transformed(f"{_SDMX}data/DF_{pid}/{key}", args, title, result, request)
    return sdmx_spec(f"{_SDMX}data/DF_{pid}/{key}", args, title)


async def _sdmx_vector(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.statcan.sdmx.constants import DEFAULT_LAST_N

    if args.get("start_period") or args.get("end_period"):
        # A period range needs the vector's SDMX key, which the tool looked
        # up through WDS; its result names the data URL.
        data_url = str(result.get("provenance", {}).get("url") or "")
        if not data_url.startswith(_SDMX):
            raise call_error(
                InvalidInput,
                "sdmx_get_vector_data returned no SDMX data URL to reproduce.",
                "sdmx_get_vector_data n'a renvoyé aucune adresse de données SDMX à reproduire.",
            )
        title = f"StatCan vector {args['vector_id']}"
        request = transform_request(args)
        if request is not None:
            return _sdmx_transformed(data_url, args, title, result, request)
        return sdmx_spec(data_url, args, title)
    # Without periods the tool reads the latest N observations, which WDS
    # serves for the same vector as JSON.
    latest = args.get("last_n_observations")
    latest_n = DEFAULT_LAST_N if latest in (None, "") else _count(latest, "last_n_observations")
    request = transform_request(args)
    if request is not None:
        spec = await _vectors_transformed([args["vector_id"]], latest_n, result, request)
        spec.notes.append("Fetched through WDS, which serves the same vector as JSON.")
        return spec
    spec = vector_spec([args["vector_id"]], latest_n)
    spec.notes.append("Fetched through WDS, which serves the same vector as JSON.")
    return spec


async def _pumf(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.statcan.pumf.client import _check_url

    # This builder runs without the tool, which is what refuses other hosts: the
    # script it writes downloads and unzips the url, so it must check it too.
    url = _check_url(str(args["url"]))
    return Spec(
        kind="zip",
        url=url,
        file_name=url.rsplit("/", 1)[-1],
        method="exact: the PUMF ZIP",
        title="StatCan public use microdata file",
        notes=[
            (
                "Use the survey's weight variable (see statcan_pumf_get_codebook); unweighted "
                "counts describe the sample, not the population."
            ),
            (
                "Where the ZIP has no CSV, read the fixed-width file with the Stata .dct/.do or "
                "SPSS/SAS command files StatCan ships in the same ZIP."
            ),
        ],
    )


# Open-data platforms -------------------------------------------------------------


async def _socrata(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.socrata.constants import PORTALS, ROWS_LIMIT_DEFAULT

    portal = PORTALS.get(str(args.get("portal")))
    if portal is None:
        raise call_error(
            InvalidInput,
            f"Unknown Socrata portal {args.get('portal')!r}.",
            f"Portail Socrata inconnu : {args.get('portal')!r}.",
        )
    # The tool always sends $limit (default 10); SODA's own default is 1,000
    # rows, so the script sends the tool's limit too.
    values = {"limit": ROWS_LIMIT_DEFAULT, **{k: v for k, v in args.items() if v is not None}}
    soql = {
        f"${key}": values[key]
        for key in ("select", "where", "order", "q", "limit", "offset")
        if values.get(key) not in (None, "")
    }
    return Spec(
        kind="csv",
        url=f"https://{portal.domain}/resource/{args['dataset_id']}.csv?{urlencode(soql)}",
        file_name=f"{args['dataset_id']}.csv",
        method="exact: SODA query rebuilt from the tool's arguments",
        title=f"Socrata dataset {args['dataset_id']} ({portal.domain})",
        notes=[
            (
                f"The URL's $limit={soql['$limit']} matches the tool; raise it (SODA allows "
                "50,000 per request) or page with $offset for every row."
            )
        ],
    )


async def _ckan(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.ckan import client as ckan_client
    from maplestats_mcp.modules.ckan.constants import DATASTORE_ROWS_DEFAULT, PORTALS

    portal = PORTALS.get(str(args.get("portal")))
    if portal is None:
        raise call_error(
            InvalidInput,
            f"Unknown CKAN portal {args.get('portal')!r}.",
            f"Portail CKAN inconnu : {args.get('portal')!r}.",
        )
    limit = _count(args.get("limit") or DATASTORE_ROWS_DEFAULT, "limit")
    offset = int(args.get("offset") or 0)  # the client rejects a negative offset
    # A resource that does not exist would give a script that fails on its
    # first run, so the tool's own request runs first (it raises NotFound).
    await ckan_client.datastore_search(
        str(args["portal"]),
        str(args["resource_id"]),
        filters=args.get("filters") or None,
        query=args.get("query") or None,
        sort=args.get("sort") or None,
        fields=args.get("fields") or None,
        limit=limit,
        offset=offset,
    )
    params: dict[str, Any] = {"resource_id": args["resource_id"]}
    for key, name in (("query", "q"), ("sort", "sort"), ("fields", "fields")):
        if args.get(key) not in (None, ""):
            params[name] = args[key]
    # The tool sends limit (default 20) and offset; CKAN's own default is 100.
    params["limit"] = limit
    params["offset"] = offset
    if args.get("filters"):
        params["filters"] = json.dumps(args["filters"])
    return Spec(
        kind="json",
        url=f"{portal.base_url}datastore_search?{urlencode(params)}",
        file_name=f"{args['resource_id']}.json",
        method="exact: DataStore query rebuilt from the tool's arguments",
        title=f"CKAN DataStore resource {args['resource_id']}",
        records_path=["result", "records"],
    )


async def _boc(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.boc import client as boc_client

    series = args["series_names"]
    if not isinstance(series, list) or not series:
        raise call_error(
            InvalidInput,
            "series_names must be a non-empty list of Valet series names.",
            "series_names doit être une liste non vide de noms de séries Valet.",
        )
    names = ",".join(str(name) for name in series)
    keys = ("start_date", "end_date", "recent", "recent_weeks", "recent_months", "recent_years")
    params = {key: args[key] for key in keys if args.get(key) not in (None, "")}
    request = transform_request(args)
    if request is not None:
        return _boc_transformed(names, params, result, request)
    # An unknown series would give a script that fails on its first run, so
    # the tool's own request runs first (Valet answers 404, raised as NotFound).
    await boc_client.get_observations([str(name) for name in series], **params)
    query = f"?{urlencode(params)}" if params else ""
    return Spec(
        kind="json",
        url=f"https://www.bankofcanada.ca/valet/observations/{names}/json{query}",
        file_name="valet_observations.json",
        method="exact: Valet request rebuilt from the tool's arguments",
        title=f"Bank of Canada Valet: {names}",
        records_path=["observations"],
        source="valet",
        notes=["Each observation holds one {'v': value} object per series, keyed by series name."],
    )


# Transforms computed by MapleStats ---------------------------------------------------
#
# A tool called with `transform` or `frequency` returns, beside the published
# values, values MapleStats computed from them (shared/transform.py). The
# script fetches the same levels, reaching back as far as the tool did for the
# lag, and applies the same formula in its own language, in "3. Prepare data"
# on the columns as the source names them. Lags are found by date, as in the
# tool, so a gap in the data cannot shift a year-over-year comparison.

_TRANSFORMS = (
    "level",
    "diff",
    "pct_change",
    "yoy_diff",
    "yoy_pct_change",
    "annualized_pct_change",
    "index",
)
_FREQUENCIES = {"monthly": 1, "quarterly": 3, "annual": 12}  # months per period
_AGGREGATIONS = ("average", "sum", "end_of_period")


def transform_request(args: dict[str, Any]) -> TransformRequest | None:
    """The call's transform arguments, or None when it asked for none."""
    transform = str(args.get("transform") or "level")
    frequency = args.get("frequency") or None
    aggregation = str(args.get("aggregation") or "average")
    index_base = args.get("index_base") or None
    if (
        transform not in _TRANSFORMS
        or (frequency is not None and frequency not in _FREQUENCIES)
        or aggregation not in _AGGREGATIONS
    ):
        raise call_error(
            InvalidInput,
            f"transform must be one of {list(_TRANSFORMS)}, frequency one of "
            f"{list(_FREQUENCIES)} and aggregation one of {list(_AGGREGATIONS)}.",
            f"transform doit valoir l'un de {list(_TRANSFORMS)}, frequency l'un de "
            f"{list(_FREQUENCIES)} et aggregation l'un de {list(_AGGREGATIONS)}.",
        )
    request = TransformRequest(
        transform,  # type: ignore[arg-type]
        frequency,
        aggregation,  # type: ignore[arg-type]
        str(index_base) if index_base else None,
    )
    return request if request.active else None


def _computed(series: dict[str, Any]) -> dict[str, Any]:
    computed = series.get("transformed")
    if not isinstance(computed, dict):
        raise call_error(
            InvalidInput,
            "The tool returned no computed values to reproduce.",
            "L'outil n'a renvoyé aucune valeur calculée à reproduire.",
        )
    return computed


def _months(ppy: Any) -> int:
    """Months per period from periods per year; 0 for daily, weekly or irregular."""
    return 12 // int(ppy) if isinstance(ppy, int) and ppy > 0 else 0


def _index_dates(index_base: str | None) -> tuple[str, str] | None:
    if not index_base:
        return None
    start, ppy = parse_period(index_base)
    end = start if ppy is None else period_end(start, ppy)
    return start.isoformat(), end.isoformat()


@dataclass
class _Plan:
    """What every language's transform step needs, as literals."""

    request: TransformRequest
    source: str  # "wds", "sdmx" or "valet": how the raw columns are named
    steps: dict[str, int]  # series -> months per published period (0: daily or irregular)
    rates: list[str]  # series already in percent: percent changes become point changes
    formula: str
    window_start: str | None = None
    window_end: str | None = None
    latest_n: int | None = None


def _py_literal(value: Any) -> str:
    return repr(value)


def _python_transform(plan: _Plan) -> Code:
    request = plan.request
    base = _index_dates(request.index_base)
    levels = {
        "wds": (
            "levels = data.select(\n"
            '    pl.col("vectorId").cast(pl.Utf8).alias("series"),\n'
            '    pl.col("refPer").cast(pl.Utf8).str.slice(0, 10).str.to_date().alias("date"),\n'
            '    pl.col("value").cast(pl.Float64, strict=False).alias("level"),\n'
            ")\n"
        ),
        "sdmx": (
            "def period_start(text):\n"
            '    """2026-07, 2026-Q3, 2026-S2, 2026 or 2026-07-15: the first day."""\n'
            '    year, _, rest = str(text).partition("-")\n'
            '    if rest[:1] in ("Q", "S"):\n'
            '        months = 3 if rest[0] == "Q" else 6\n'
            "        return date(int(year), (int(rest[1:]) - 1) * months + 1, 1)\n"
            '    month, _, day = rest.partition("-")\n'
            "    return date(int(year), int(month or 1), int(day or 1))\n"
            "\n\n"
            "levels = data.select(\n"
            '    pl.col("VECTOR_ID").cast(pl.Utf8).alias("series"),\n'
            '    pl.col("TIME_PERIOD").cast(pl.Utf8)\n'
            '    .map_elements(period_start, return_dtype=pl.Date).alias("date"),\n'
            '    pl.col("OBS_VALUE").cast(pl.Float64, strict=False).alias("level"),\n'
            ")\n"
        ),
        "valet": (
            "# Valet nests each series as <series>.v; a series missing from a row\n"
            "# (mixed frequencies) is not an observation of it.\n\n"
            'levels = data.unpivot(index="d", variable_name="series", value_name="level").select(\n'
            '    pl.col("series").str.replace(r"\\.v$", ""),\n'
            '    pl.col("d").str.to_date().alias("date"),\n'
            '    pl.col("level").cast(pl.Float64, strict=False),\n'
            ').drop_nulls("level")\n'
        ),
    }[plan.source]
    window_start = f"date.fromisoformat({plan.window_start!r})" if plan.window_start else "None"
    window_end = f"date.fromisoformat({plan.window_end!r})" if plan.window_end else "None"
    index = (
        f"(date.fromisoformat({base[0]!r}), date.fromisoformat({base[1]!r}))" if base else "None"
    )
    body = (
        f"# {plan.formula}\n"
        "# Lags are found by date (the same period a year earlier for yoy), never by\n"
        "# counting rows. `data` becomes one row per series and period: the level\n"
        "# (as published, or aggregated) and the computed value.\n\n"
        f"TRANSFORM = {request.transform!r}\n"
        f"FREQUENCY_MONTHS = {_FREQUENCIES[request.frequency] if request.frequency else None!r}\n"
        f"AGGREGATION = {request.aggregation!r}\n"
        f"STEP_MONTHS = {plan.steps!r}\n"
        f"RATE_SERIES = {plan.rates!r}\n"
        f"INDEX_BASE = {index}\n"
        f"WINDOW_START = {window_start}\n"
        f"WINDOW_END = {window_end}\n"
        f"LATEST_N = {plan.latest_n!r}\n"
        'POINTS_INSTEAD = {"pct_change": "diff", "yoy_pct_change": "yoy_diff", '
        '"annualized_pct_change": "diff"}\n\n'
        f"{levels}\n"
        "def months_after(day, months):\n"
        "    index = day.year * 12 + day.month - 1 + months\n"
        "    return date(index // 12, index % 12 + 1, 1)\n"
        "\n\n"
        "def period_floor(day, months):\n"
        "    return date(day.year, (day.month - 1) // months * months + 1, 1) if months else day\n"
        "\n\n"
        "def aggregate(points, step):\n"
        "    groups = {}\n"
        "    for day, level in points:\n"
        "        groups.setdefault(period_floor(day, FREQUENCY_MONTHS), []).append((day, level))\n"
        "    starts = list(groups)\n"
        "    out = []\n"
        "    for start, members in groups.items():\n"
        "        values = [level for _, level in members]\n"
        "        if step:\n"
        "            periods = {period_floor(day, step) for day, _ in members}\n"
        "            complete = None not in values and len(periods) == FREQUENCY_MONTHS // step\n"
        "        else:\n"
        "            values = [value for value in values if value is not None]\n"
        "            end = months_after(start, FREQUENCY_MONTHS) - timedelta(days=1)\n"
        "            cut_start = start == starts[0] and (points[0][0] - start).days > 4\n"
        "            cut_end = start == starts[-1] and (end - points[-1][0]).days > 4\n"
        "            complete = bool(values) and not cut_start and not cut_end\n"
        "        if not complete:\n"
        "            out.append((start, None))\n"
        '        elif AGGREGATION == "sum":\n'
        "            out.append((start, sum(values)))\n"
        '        elif AGGREGATION == "end_of_period":\n'
        "            out.append((start, values[-1]))\n"
        "        else:\n"
        "            out.append((start, sum(values) / len(values)))\n"
        "    return out\n"
        "\n\n"
        "def compute(applied, level, lagged, step, base):\n"
        '    if applied == "level":\n'
        "        return level\n"
        '    if applied == "index":\n'
        "        return None if level is None or not base else 100 * level / base\n"
        "    if level is None or lagged is None:\n"
        "        return None\n"
        '    if applied in ("diff", "yoy_diff"):\n'
        "        return level - lagged\n"
        "    if lagged == 0:\n"
        "        return None\n"
        '    if applied == "annualized_pct_change":\n'
        "        ratio = level / lagged\n"
        "        return None if ratio < 0 else 100 * (ratio ** (12 // step) - 1)\n"
        "    return 100 * (level / lagged - 1)\n"
        "\n\n"
        "rows = []\n"
        'for series in sorted(set(levels["series"].to_list())):\n'
        "    points = [\n"
        "        (day, None if level is None or level != level else level)\n"
        '        for day, level in levels.filter(pl.col("series") == series)\n'
        '        .sort("date").select("date", "level").iter_rows()\n'
        "    ]\n"
        "    step = STEP_MONTHS.get(series, 0)\n"
        "    if FREQUENCY_MONTHS:\n"
        "        points, step = aggregate(points, step), FREQUENCY_MONTHS\n"
        "    elif step:\n"
        "        points = [(period_floor(day, step), level) for day, level in points]\n"
        "    applied = POINTS_INSTEAD.get(TRANSFORM, TRANSFORM) if series in RATE_SERIES else TRANSFORM\n"
        '    lag = 12 if applied in ("yoy_diff", "yoy_pct_change") else step\n'
        "    by_date = dict(points)\n"
        "    base = None\n"
        '    if applied == "index":\n'
        "        inside = [level for day, level in points if INDEX_BASE[0] <= day <= INDEX_BASE[1]]\n"
        "        base = sum(inside) / len(inside) if inside and None not in inside else None\n"
        "    computed = []\n"
        "    for i, (day, level) in enumerate(points):\n"
        "        if step:\n"
        "            lagged = by_date.get(months_after(day, -lag))\n"
        "        else:\n"
        "            lagged = points[i - 1][1] if i else None\n"
        "        computed.append((day, level, compute(applied, level, lagged, step, base)))\n"
        "    if WINDOW_START is not None:\n"
        "        first = period_floor(WINDOW_START, step)\n"
        "        computed = [row for row in computed if row[0] >= first]\n"
        "    if WINDOW_END is not None:\n"
        "        computed = [row for row in computed if row[0] <= WINDOW_END]\n"
        "    if LATEST_N is not None:\n"
        "        computed = computed[-LATEST_N:]\n"
        "    for day, level, value in computed:\n"
        "        rows.append(\n"
        '            {"series": series, "period": day, "level": level, "value": value, '
        '"transform": applied}\n'
        "        )\n"
        "data = pl.DataFrame(\n"
        "    rows,\n"
        "    schema={\n"
        '        "series": pl.Utf8,\n'
        '        "period": pl.Date,\n'
        '        "level": pl.Float64,\n'
        '        "value": pl.Float64,\n'
        '        "transform": pl.Utf8,\n'
        "    },\n"
        ")\n"
    )
    return Code(["from datetime import date, timedelta"], body)


def _r_date(value: str | None) -> str:
    return f'as.Date("{value}")' if value else "as.Date(NA)"


def _r_transform(plan: _Plan) -> Code:
    request = plan.request
    base = _index_dates(request.index_base)
    steps = ", ".join(f"{_quote_r(series)} = {months}L" for series, months in plan.steps.items())
    rates = ", ".join(_quote_r(series) for series in plan.rates)
    packages = ["purrr", "tibble"]
    levels = {
        "wds": (
            "levels <- tibble(\n"
            "  series = as.character(data$vectorId),\n"
            "  date = as.Date(substr(as.character(data$refPer), 1, 10)),\n"
            "  level = if (is.null(data$value)) NA_real_ else suppressWarnings(as.numeric(data$value))\n"
            ")\n"
        ),
        "sdmx": (
            "# 2026-07, 2026-Q3, 2026-S2, 2026 or 2026-07-15: the period's first day.\n"
            "period_start <- function(text) {\n"
            "  text <- as.character(text)\n"
            "  rest <- substring(text, 6)\n"
            "  kind <- substr(rest, 1, 1)\n"
            "  number <- suppressWarnings(as.integer(substring(rest, 2)))\n"
            "  month <- suppressWarnings(as.integer(substr(rest, 1, 2)))\n"
            "  month <- ifelse(\n"
            '    kind == "Q", (number - 1L) * 3L + 1L,\n'
            '    ifelse(kind == "S", (number - 1L) * 6L + 1L, ifelse(is.na(month), 1L, month))\n'
            "  )\n"
            "  day <- suppressWarnings(as.integer(substr(rest, 4, 5)))\n"
            '  day <- ifelse(kind %in% c("Q", "S") | is.na(day), 1L, day)\n'
            '  as.Date(sprintf("%s-%02d-%02d", substr(text, 1, 4), month, day))\n'
            "}\n\n"
            "levels <- tibble(\n"
            "  series = as.character(data$VECTOR_ID),\n"
            "  date = period_start(data$TIME_PERIOD),\n"
            "  level = suppressWarnings(as.numeric(data$OBS_VALUE))\n"
            ")\n"
        ),
        "valet": (
            "# Valet nests each series as <series>.v; a series missing from a row\n"
            "# (mixed frequencies) is not an observation of it.\n\n"
            "levels <- data |>\n"
            '  pivot_longer(-d, names_to = "series", values_to = "level", values_transform = as.character) |>\n'
            "  transmute(\n"
            '    series = str_remove(series, "\\\\.v$"),\n'
            "    date = as.Date(d),\n"
            "    level = suppressWarnings(as.numeric(level))\n"
            "  ) |>\n"
            "  filter(!is.na(level))\n"
        ),
    }[plan.source]
    if plan.source == "valet":
        packages += ["dplyr", "stringr", "tidyr"]
    body = (
        f"# {plan.formula}\n"
        "# Lags are found by date (the same period a year earlier for yoy), never by\n"
        "# counting rows. `data` becomes one row per series and period: the level\n"
        "# (as published, or aggregated) and the computed value.\n\n"
        f'transform_name <- "{request.transform}"\n'
        "frequency_months <- "
        + (f"{_FREQUENCIES[request.frequency]}L" if request.frequency else "NA_integer_")
        + "\n"
        f'aggregation <- "{request.aggregation}"\n'
        f"step_months <- c({steps})\n"
        f"rate_series <- c({rates})\n"
        f"index_base <- c({_r_date(base[0] if base else None)}, "
        f"{_r_date(base[1] if base else None)})\n"
        f"window_start <- {_r_date(plan.window_start)}\n"
        f"window_end <- {_r_date(plan.window_end)}\n"
        f"latest_n <- {f'{plan.latest_n}L' if plan.latest_n else 'NA_integer_'}\n"
        'points_instead <- c(pct_change = "diff", yoy_pct_change = "yoy_diff", '
        'annualized_pct_change = "diff")\n\n'
        f"{levels}\n"
        "months_after <- function(day, months) {\n"
        '  index <- as.integer(format(day, "%Y")) * 12L + as.integer(format(day, "%m")) - 1L + months\n'
        '  as.Date(sprintf("%04d-%02d-01", index %/% 12L, index %% 12L + 1L))\n'
        "}\n\n"
        "period_floor <- function(day, months) {\n"
        "  if (is.na(months) || months == 0) return(day)\n"
        '  month <- (as.integer(format(day, "%m")) - 1L) %/% months * months + 1L\n'
        '  as.Date(sprintf("%s-%02d-01", format(day, "%Y"), month))\n'
        "}\n\n"
        "aggregate_levels <- function(points, step) {\n"
        "  starts <- period_floor(points$date, frequency_months)\n"
        "  group_starts <- sort(unique(starts))\n"
        "  level <- vapply(seq_along(group_starts), \\(i) {\n"
        "    rows <- which(starts == group_starts[i])\n"
        "    values <- points$level[rows]\n"
        "    if (step > 0) {\n"
        "      periods <- unique(period_floor(points$date[rows], step))\n"
        "      if (anyNA(values) || length(periods) != frequency_months %/% step) return(NA_real_)\n"
        "    } else {\n"
        "      values <- values[!is.na(values)]\n"
        "      end <- months_after(group_starts[i], frequency_months) - 1\n"
        "      cut_start <- i == 1 && as.numeric(points$date[1] - group_starts[i]) > 4\n"
        "      cut_end <- i == length(group_starts) &&\n"
        "        as.numeric(end - points$date[nrow(points)]) > 4\n"
        "      if (length(values) == 0 || cut_start || cut_end) return(NA_real_)\n"
        "    }\n"
        "    switch(aggregation, sum = sum(values), end_of_period = values[length(values)], mean(values))\n"
        "  }, numeric(1))\n"
        "  tibble(date = group_starts, level = level)\n"
        "}\n\n"
        "compute_series <- function(points, series) {\n"
        "  points <- points[order(points$date), ]\n"
        "  points$level[is.nan(points$level)] <- NA\n"
        "  step <- if (series %in% names(step_months)) step_months[[series]] else 0L\n"
        "  if (!is.na(frequency_months)) {\n"
        "    points <- aggregate_levels(points, step)\n"
        "    step <- frequency_months\n"
        "  } else if (step > 0) {\n"
        "    points$date <- period_floor(points$date, step)\n"
        "  }\n"
        "  applied <- transform_name\n"
        "  if (series %in% rate_series && applied %in% names(points_instead)) {\n"
        "    applied <- points_instead[[applied]]\n"
        "  }\n"
        '  lag <- if (applied %in% c("yoy_diff", "yoy_pct_change")) 12L else step\n'
        "  x <- points$level\n"
        "  lagged <- if (step > 0) {\n"
        "    x[match(months_after(points$date, -lag), points$date)]\n"
        "  } else {\n"
        "    c(NA_real_, x)[seq_along(x)]\n"
        "  }\n"
        "  value <- switch(applied,\n"
        "    level = x,\n"
        "    index = {\n"
        "      inside <- x[points$date >= index_base[1] & points$date <= index_base[2]]\n"
        "      base <- if (length(inside) == 0 || anyNA(inside)) NA_real_ else mean(inside)\n"
        "      ifelse(is.na(base) | base == 0, NA_real_, 100 * x / base)\n"
        "    },\n"
        "    diff = ,\n"
        "    yoy_diff = x - lagged,\n"
        "    annualized_pct_change = ifelse(\n"
        "      lagged == 0 | x / lagged < 0, NA_real_, 100 * ((x / lagged)^(12 %/% step) - 1)\n"
        "    ),\n"
        "    ifelse(lagged == 0, NA_real_, 100 * (x / lagged - 1))\n"
        "  )\n"
        "  out <- tibble(\n"
        "    series = rep(series, length(x)), period = points$date, level = x, value = value,\n"
        "    transform = rep(applied, length(x))\n"
        "  )\n"
        "  if (!is.na(window_start)) out <- out[out$period >= period_floor(window_start, step), ]\n"
        "  if (!is.na(window_end)) out <- out[out$period <= window_end, ]\n"
        "  if (!is.na(latest_n)) out <- tail(out, latest_n)\n"
        "  out\n"
        "}\n\n"
        "data <- split(levels, levels$series) |>\n"
        "  imap(\\(points, series) compute_series(points, series)) |>\n"
        "  list_rbind()\n"
    )
    return Code(packages, body)


def _quote_r(value: str) -> str:
    return json.dumps(value)


def _julia_transform(plan: _Plan) -> Code:
    request = plan.request
    base = _index_dates(request.index_base)
    steps = ", ".join(f"{jl_quote(series)} => {months}" for series, months in plan.steps.items())
    rates = ", ".join(jl_quote(series) for series in plan.rates)

    def jl_date(value: str | None) -> str:
        return f'Date("{value}")' if value else "nothing"

    levels = {
        "wds": (
            "levels = DataFrame(\n"
            "    series = string.(data.vectorId),\n"
            "    date = [Date(first(string(day), 10)) for day in data.refPer],\n"
            "    level = [ismissing(x) ? missing : Float64(x) for x in data.value],\n"
            ")\n"
        ),
        "sdmx": (
            "# 2026-07, 2026-Q3, 2026-S2, 2026 or 2026-07-15: the period's first day.\n"
            "function period_start(text)\n"
            "    text = string(text)\n"
            "    year_ = parse(Int, text[1:4])\n"
            '    rest = length(text) > 5 ? text[6:end] : ""\n'
            '    startswith(rest, "Q") && return Date(year_, (parse(Int, rest[2:end]) - 1) * 3 + 1, 1)\n'
            '    startswith(rest, "S") && return Date(year_, (parse(Int, rest[2:end]) - 1) * 6 + 1, 1)\n'
            "    isempty(rest) && return Date(year_, 1, 1)\n"
            "    length(rest) == 2 && return Date(year_, parse(Int, rest), 1)\n"
            "    return Date(text[1:10])\n"
            "end\n\n"
            "levels = DataFrame(\n"
            "    series = string.(data.VECTOR_ID),\n"
            "    date = period_start.(data.TIME_PERIOD),\n"
            "    level = [\n"
            "        ismissing(x) ? missing : something(tryparse(Float64, string(x)), missing)\n"
            "        for x in data.OBS_VALUE\n"
            "    ],\n"
            ")\n"
        ),
        "valet": (
            "# Valet nests each series as {v: value}; a series missing from a row\n"
            "# (mixed frequencies) is not an observation of it.\n\n"
            "levels = DataFrame(series = String[], date = Date[], level = Float64[])\n"
            "for name in names(data)\n"
            '    name == "d" && continue\n'
            "    for (day, cell) in zip(data.d, data[!, name])\n"
            "        (ismissing(cell) || cell === nothing) && continue\n"
            '        value = tryparse(Float64, string(get(cell, :v, "")))\n'
            "        value === nothing && continue\n"
            "        push!(levels, (name, Date(day), value))\n"
            "    end\n"
            "end\n"
        ),
    }[plan.source]
    body = (
        f"# {plan.formula}\n"
        "# Lags are found by date (the same period a year earlier for yoy), never by\n"
        "# counting rows. `data` becomes one row per series and period: the level\n"
        "# (as published, or aggregated) and the computed value.\n\n"
        f'transform_name = "{request.transform}"\n'
        "frequency_months = "
        + (str(_FREQUENCIES[request.frequency]) if request.frequency else "nothing")
        + "\n"
        f'aggregation = "{request.aggregation}"\n'
        f"step_months = Dict{{String, Int}}({steps})\n"
        f"rate_series = Set{{String}}([{rates}])\n"
        f"index_base = "
        + (f"({jl_date(base[0])}, {jl_date(base[1])})" if base else "nothing")
        + "\n"
        f"window_start = {jl_date(plan.window_start)}\n"
        f"window_end = {jl_date(plan.window_end)}\n"
        f"latest_n = {plan.latest_n if plan.latest_n else 'nothing'}\n"
        'points_instead = Dict("pct_change" => "diff", "yoy_pct_change" => "yoy_diff", '
        '"annualized_pct_change" => "diff")\n\n'
        f"{levels}"
        "levels.level = [ismissing(x) || isnan(x) ? missing : x for x in levels.level]\n\n"
        "function months_after(day, months)\n"
        "    index = year(day) * 12 + month(day) - 1 + months\n"
        "    return Date(fld(index, 12), mod(index, 12) + 1, 1)\n"
        "end\n\n"
        "period_floor(day, months) =\n"
        "    months == 0 ? day : Date(year(day), div(month(day) - 1, months) * months + 1, 1)\n\n"
        "function aggregate_levels(dates, levels_, step)\n"
        "    starts = period_floor.(dates, frequency_months)\n"
        "    group_starts = unique(starts)\n"
        "    out = Union{Missing, Float64}[]\n"
        "    for (i, start) in enumerate(group_starts)\n"
        "        rows = findall(==(start), starts)\n"
        "        values = levels_[rows]\n"
        "        if step > 0\n"
        "            periods = unique(period_floor.(dates[rows], step))\n"
        "            complete = !any(ismissing, values) && length(periods) == div(frequency_months, step)\n"
        "        else\n"
        "            values = collect(skipmissing(values))\n"
        "            stop = months_after(start, frequency_months) - Day(1)\n"
        "            cut_start = i == 1 && Dates.value(dates[1] - start) > 4\n"
        "            cut_end = i == length(group_starts) && Dates.value(stop - dates[end]) > 4\n"
        "            complete = !isempty(values) && !cut_start && !cut_end\n"
        "        end\n"
        "        if !complete\n"
        "            push!(out, missing)\n"
        '        elseif aggregation == "sum"\n'
        "            push!(out, sum(values))\n"
        '        elseif aggregation == "end_of_period"\n'
        "            push!(out, values[end])\n"
        "        else\n"
        "            push!(out, sum(values) / length(values))\n"
        "        end\n"
        "    end\n"
        "    return group_starts, out\n"
        "end\n\n"
        "function compute_value(applied, x, lagged, step, base)\n"
        '    applied == "level" && return x\n'
        '    if applied == "index"\n'
        "        return ismissing(x) || ismissing(base) || base == 0 ? missing : 100 * x / base\n"
        "    end\n"
        "    (ismissing(x) || ismissing(lagged)) && return missing\n"
        '    applied in ("diff", "yoy_diff") && return x - lagged\n'
        "    lagged == 0 && return missing\n"
        '    if applied == "annualized_pct_change"\n'
        "        return x / lagged < 0 ? missing : 100 * ((x / lagged)^div(12, step) - 1)\n"
        "    end\n"
        "    return 100 * (x / lagged - 1)\n"
        "end\n\n"
        "function compute_series(series, dates, levels_)\n"
        "    order = sortperm(dates)\n"
        "    dates, levels_ = dates[order], levels_[order]\n"
        "    step = get(step_months, series, 0)\n"
        "    if frequency_months !== nothing\n"
        "        dates, levels_ = aggregate_levels(dates, levels_, step)\n"
        "        step = frequency_months\n"
        "    elseif step > 0\n"
        "        dates = period_floor.(dates, step)\n"
        "    end\n"
        "    applied = series in rate_series ? get(points_instead, transform_name, transform_name) :\n"
        "        transform_name\n"
        '    lag = applied in ("yoy_diff", "yoy_pct_change") ? 12 : step\n'
        "    position = Dict(zip(dates, eachindex(dates)))\n"
        "    base = missing\n"
        '    if applied == "index"\n'
        "        inside = levels_[(dates .>= index_base[1]) .& (dates .<= index_base[2])]\n"
        "        base = isempty(inside) || any(ismissing, inside) ? missing : sum(inside) / length(inside)\n"
        "    end\n"
        "    values = Union{Missing, Float64}[]\n"
        "    for (i, (day, x)) in enumerate(zip(dates, levels_))\n"
        "        if step > 0\n"
        "            j = get(position, months_after(day, -lag), 0)\n"
        "            lagged = j == 0 ? missing : levels_[j]\n"
        "        else\n"
        "            lagged = i > 1 ? levels_[i - 1] : missing\n"
        "        end\n"
        "        push!(values, compute_value(applied, x, lagged, step, base))\n"
        "    end\n"
        "    out = DataFrame(\n"
        "        series = fill(series, length(dates)),\n"
        "        period = dates,\n"
        "        level = levels_,\n"
        "        value = values,\n"
        "        transform = fill(applied, length(dates)),\n"
        "    )\n"
        "    window_start === nothing || (out = out[out.period .>= period_floor(window_start, step), :])\n"
        "    window_end === nothing || (out = out[out.period .<= window_end, :])\n"
        "    latest_n === nothing || (out = last(out, latest_n))\n"
        "    return out\n"
        "end\n\n"
        "data = reduce(\n"
        "    vcat,\n"
        "    [\n"
        "        compute_series(key.series, collect(group.date), collect(group.level))\n"
        "        for (key, group) in pairs(groupby(levels, :series))\n"
        "    ],\n"
        ")\n"
    )
    return Code(["DataFrames", "Dates"], body)


def _with_transform(spec: Spec, plan: _Plan) -> Spec:
    """The spec with the transform step in every script language.

    The step works on the columns as the source names them, so the
    source-specific cleaning (which expects them) is skipped; the R script
    reads the JSON instead of cansim for the same reason. Power Query gets no
    query: it cannot repeat the step, and a query of the levels alone would
    look like the tool's result without being it.
    """
    spec.native = {}
    spec.source = ""
    spec.prepare = {
        "python": _python_transform(plan),
        "r": _r_transform(plan),
        "julia": _julia_transform(plan),
    }
    spec.languages = tuple(lang for lang in spec.languages if lang != "excel")
    spec.title += f" ({plan.request.transform}"
    spec.title += (
        f", {plan.request.frequency} {plan.request.aggregation})" if plan.request.frequency else ")"
    )
    spec.notes.append(
        say(
            f"The scripts compute what the tool computed: {plan.formula}. They fetch the "
            "published levels, reaching back as far as the tool did for the lag, and keep the "
            "requested window. Stata does it in its Python block.",
            f"Les scripts calculent ce que l'outil a calculé : {plan.formula}. Ils récupèrent "
            "les niveaux publiés, en remontant aussi loin que l'outil pour le décalage, et "
            "gardent la période demandée. Stata le fait dans son bloc Python.",
        )
    )
    spec.notes.append(
        say(
            "No Excel (Power Query) query: Power Query cannot apply the transform, and a query "
            "of the published levels alone would not match the tool's result. Call reproduce_code "
            "without transform or frequency for an Excel query of the levels.",
            "Aucune requête Excel (Power Query) : Power Query ne peut pas appliquer la "
            "transformation, et une requête des seuls niveaux publiés ne correspondrait pas au "
            "résultat de l'outil. Appelez reproduce_code sans transform ni frequency pour une "
            "requête Excel des niveaux.",
        )
    )
    return spec


def _plan(
    request: TransformRequest,
    source: str,
    series: list[tuple[str, dict[str, Any]]],
    **window: Any,
) -> _Plan:
    """The plan from the tool's own result: each series' published frequency
    and whether the percent-point rule applied to it."""
    steps: dict[str, int] = {}
    rates: list[str] = []
    formula = ""
    for name, computed in series:
        steps[name] = _months(computed.get("source_periods_per_year"))
        if computed.get("transform") != computed.get("requested_transform"):
            rates.append(name)
        formula = formula or str(computed.get("formula") or "")
    return _Plan(
        request,
        source,
        steps,
        rates,
        comment_text(formula, stata=True),
        **window,
    )


def _series_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The series of a VectorDataSet, or the one series of a VectorData."""
    if isinstance(result.get("series"), list):
        return [s for s in result["series"] if isinstance(s, dict)]
    return [result]


def _ppys(result: dict[str, Any]) -> list[int | None]:
    return [_computed(s).get("source_periods_per_year") for s in _series_payloads(result)]


async def _vectors_transformed(
    ids: list[Any], latest_n: int, result: dict[str, Any], request: TransformRequest
) -> Spec:
    """The WDS latest-N request with the extra periods the tool fetched for the lag."""
    from maplestats_mcp.modules.statcan.wds.transforms import latest_n_to_fetch

    series = _series_payloads(result)
    spec = vector_spec(ids, latest_n_to_fetch(latest_n, request, _ppys(result)))
    return _with_transform(
        spec,
        _plan(
            request,
            "wds",
            [(str(s["vector_id"]), _computed(s)) for s in series],
            latest_n=latest_n,
        ),
    )


async def _vectors(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    request = transform_request(args)
    latest_n = _count(args.get("latest_n", 12), "latest_n")
    if request is not None:
        return await _vectors_transformed(list(args["vector_ids"]), latest_n, result, request)
    return vector_spec(args["vector_ids"], latest_n)


async def _cube_coord(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    """wds_get_data_from_cube_coord with a transform: the vector the tool read."""
    request = transform_request(args)
    if request is None:
        return await _table(args, result)
    latest_n = _count(args.get("latest_n", 12), "latest_n")
    return await _vectors_transformed([result["vector_id"]], latest_n, result, request)


async def _reference_range(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    """wds_get_data_by_reference_period_range with a transform: the same GET,
    from the earlier start the tool used for the lag."""
    from maplestats_mcp.modules.statcan.wds.client import _ref_period
    from maplestats_mcp.modules.statcan.wds.transforms import start_to_fetch

    request = transform_request(args)
    assert request is not None  # builder_for routes here only with a transform
    ids = [_vector_id(v) for v in args["vector_ids"]]
    start = date.fromisoformat(
        _ref_period(str(args["start_ref_period"]), "start_ref_period", end=False)
    )
    end = _ref_period(str(args["end_ref_period"]), "end_ref_period", end=True)
    fetch_start = start_to_fetch(start, request, _ppys(result))
    query = urlencode(
        {
            "vectorIds": ",".join(str(i) for i in ids),
            "startRefPeriod": fetch_start.isoformat(),
            "endReferencePeriod": end,
        }
    )
    spec = Spec(
        kind="json",
        url=f"{_WDS}getDataFromVectorByReferencePeriodRange?{query}",
        file_name="vectors.json",
        method="exact: WDS reference-period request rebuilt from the tool's arguments",
        title="StatCan vectors",
        records_path=["object", "vectorDataPoint"],
        each_item=True,
        notes=["WDS returns one object per vector; values are under vectorDataPoint."],
    )
    return _with_transform(
        spec,
        _plan(
            request,
            "wds",
            [(str(s["vector_id"]), _computed(s)) for s in _series_payloads(result)],
            window_start=start.isoformat(),
            window_end=end,
        ),
    )


def _sdmx_transformed(
    data_url: str,
    args: dict[str, Any],
    title: str,
    result: dict[str, Any],
    request: TransformRequest,
) -> Spec:
    """The SDMX request reaching back as the tool's did, with the transform step."""
    from maplestats_mcp.modules.statcan.sdmx.client import transform_params
    from maplestats_mcp.modules.statcan.sdmx.constants import DEFAULT_LAST_N

    series = _series_payloads(result)
    ppys = _ppys(result)
    start, end = args.get("start_period"), args.get("end_period")
    last_n = args.get("last_n_observations")
    latest_n = (
        _count(last_n, "last_n_observations")
        if last_n not in (None, "")
        else (None if start or end else DEFAULT_LAST_N)
    )
    spec = sdmx_spec(data_url, args, title)
    base, _, query = spec.url.partition("?")
    params = dict(parse_qsl(query))
    params = transform_params(params, request, ppys[0] if ppys else None, latest_n=latest_n)
    spec.url = f"{base}?{urlencode(params)}"
    return _with_transform(
        spec,
        _plan(
            request,
            "sdmx",
            [(str(s.get("vector_id")), _computed(s)) for s in series],
            window_start=parse_period(str(start))[0].isoformat() if start else None,
            window_end=parse_period(str(end))[0].isoformat() if end else None,
            latest_n=latest_n,
        ),
    )


def _boc_transformed(
    names: str, params: dict[str, Any], result: dict[str, Any], request: TransformRequest
) -> Spec:
    """The window the tool returned, fetched again from as far back as the tool
    went for the lag. A `recent` window becomes its dates as of the tool's run."""
    from maplestats_mcp.modules.boc.client import history_window

    transformed = result.get("transformed")
    if not isinstance(transformed, dict):
        raise call_error(
            InvalidInput,
            "The tool returned no computed values to reproduce.",
            "L'outil n'a renvoyé aucune valeur calculée à reproduire.",
        )
    days = sorted(
        date.fromisoformat(str(row["ref_date"])[:10])
        for row in result.get("observations") or []
        if isinstance(row, dict) and row.get("ref_date")
    )
    window: dict[str, Any] = {}
    query = ""
    if days:
        window = {"window_start": days[0].isoformat(), "window_end": days[-1].isoformat()}
        if params:
            ppys = [c.get("source_periods_per_year") for c in transformed.values()]
            query = f"?{urlencode(history_window(days, ppys, request))}"
    spec = Spec(
        kind="json",
        url=f"https://www.bankofcanada.ca/valet/observations/{names}/json{query}",
        file_name="valet_observations.json",
        method="exact: Valet request rebuilt from the tool's arguments and window",
        title=f"Bank of Canada Valet: {names}",
        records_path=["observations"],
        notes=["Each observation holds one {'v': value} object per series, keyed by series name."],
    )
    if params.keys() & {"recent", "recent_weeks", "recent_months", "recent_years"}:
        spec.notes.append(
            say(
                "The tool's recent window is written as the dates it covered when the tool ran.",
                "La fenêtre « recent » de l'outil est écrite avec les dates qu'elle couvrait "
                "quand l'outil a été appelé.",
            )
        )
    return _with_transform(
        spec,
        _plan(request, "valet", [(str(k), v) for k, v in transformed.items()], **window),
    )


# Files the tool filters itself ------------------------------------------------------


async def _header(url: str) -> list[str]:
    from maplestats_mcp.shared.csv_files import fetch_rows
    from maplestats_mcp.shared.rate_limiter import get_limiter

    limiter = get_limiter("reproduce-header", rate=1.0, capacity=3.0)
    rows, _ = await fetch_rows(url, limiter=limiter, ttl=3600, context="reproduce_code")
    return list(rows[0].keys()) if rows else []


def _resolve(header: list[str], name: str) -> str:
    by_lower = {h.lower(): h for h in header}
    return by_lower.get(name.strip().lower(), name)


async def _cer_file(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(args["url"])
    header = await _header(url)
    filters = [
        Filter("is", [_resolve(header, k)], v) for k, v in (args.get("filters") or {}).items()
    ]
    date_column = result.get("date_column")
    if date_column and args.get("start"):
        filters.append(Filter("ge", [date_column], str(args["start"])))
    if date_column and args.get("end"):
        filters.append(Filter("le", [date_column], str(args["end"])))
    notes = []
    if date_column and (args.get("start") or args.get("end")):
        notes.append(f"Date bounds compare {date_column} as ISO text (YYYY-MM-DD).")
    return Spec(
        kind="csv",
        url=url,
        file_name=url.rsplit("/", 1)[-1],
        method=_FILTERED,
        title="Canada Energy Regulator open data file",
        filters=filters,
        sort_by=date_column or "",
        notes=notes,
    )


async def _gc_infobase(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(result.get("provenance", {}).get("url") or "")
    header = await _header(url)
    filters = [
        Filter("is", [_resolve(header, k)], v) for k, v in (args.get("filters") or {}).items()
    ]
    if args.get("organization") and result.get("organization_column"):
        filters.append(Filter("contains", [result["organization_column"]], args["organization"]))
    if args.get("fiscal_year") and result.get("fiscal_year_column"):
        year = "".join(ch for ch in str(args["fiscal_year"]) if ch.isdigit())[:4]
        filters.append(Filter("starts", [result["fiscal_year_column"]], year))
    return Spec(
        kind="csv",
        url=url,
        file_name=url.rsplit("/", 1)[-1],
        method=_FILTERED,
        title=f"GC InfoBase: {result.get('name', 'open dataset')}",
        filters=filters,
    )


async def _cihi(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(result.get("data_file_url") or "")
    header = list(result.get("columns") or [])
    tables = list(result.get("tables") or [])
    sheet = str(args.get("table") or (tables[0] if tables else ""))
    filters = [
        Filter("is", [_resolve(header, k)], v) for k, v in (args.get("filters") or {}).items()
    ]
    place_names = ("place or organization", "lieu ou organisme", "lieu ou organisation")
    place = next((h for h in header if h.lower() in place_names), None)
    if args.get("place") and place:
        filters.append(Filter("contains", [place], args["place"]))
    return Spec(
        kind="xlsx",
        url=url,
        file_name=url.rsplit("/", 1)[-1].split("?")[0] + ("" if url.endswith(".xlsx") else ".xlsx"),
        method=_FILTERED,
        title=f"CIHI indicator data: {result.get('table') or sheet}",
        sheet=sheet,
        skip_rows=1,
        filters=filters,
        notes=["Each 'Table' sheet has a title row above its header, hence the skipped row."],
    )


async def _ircc_monthly(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.ircc.monthly import client as ircc_monthly

    table = await ircc_monthly._find(str(args["table_id"]), "en")
    parsed, _ = await ircc_monthly._load(table)
    filters = [
        Filter("is", [column], value)
        for column, value in (result.get("applied_filters") or {}).items()
    ]
    if args.get("year_from") is not None:
        filters.append(Filter("ge", ["EN_YEAR"], int(args["year_from"])))
    if args.get("year_to") is not None:
        filters.append(Filter("le", ["EN_YEAR"], int(args["year_to"])))
    notes = [
        "Counts are rounded to 5; '--' marks a suppressed count of 1 to 4.",
    ]
    if args.get("group_by") is not None or args.get("period"):
        notes.append(
            f"The tool then summed these rows to period={result.get('period')} "
            f"and group_by={result.get('group_by')}; the script returns the rows."
        )
    return Spec(
        kind="csv",
        url=table.csv_url,
        file_name=table.csv_url.rsplit("/", 1)[-1],
        method=_FILTERED,
        title=f"IRCC monthly update: {table.title}",
        delimiter=parsed.delimiter,
        na_values=["--"],
        filters=filters,
        notes=notes,
    )


async def _ircc_rounds(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(result.get("provenance", {}).get("url") or "")
    filters = []
    if args.get("program"):
        filters.append(Filter("terms", ["drawName", "drawText2"], args["program"]))
    if args.get("since"):
        filters.append(Filter("ge", ["drawDate"], str(args["since"])))
    return Spec(
        kind="json",
        url=url,
        file_name=url.rsplit("/", 1)[-1],
        method=_FILTERED,
        title="IRCC Express Entry rounds",
        records_path=["rounds"],
        filters=filters,
        sort_by="drawDate",
        sort_descending=True,
    )


async def _statcan_indicators(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(result.get("provenance", {}).get("url") or "")
    lang = "en" if str(args.get("lang", "en")) == "en" else "fr"
    filters = []
    if str(args.get("query") or "").strip():
        filters.append(Filter("contains", [f"title.{lang}"], str(args["query"]).strip()))
    if args.get("geo_code") is not None:
        filters.append(Filter("eq", ["geo_code"], int(args["geo_code"])))
    return Spec(
        kind="json",
        url=url,
        file_name=url.rsplit("/", 1)[-1],
        method=_FILTERED,
        title="StatCan key indicators",
        records_path=["results", "indicators"],
        filters=filters,
    )


async def _phac_query(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import phac_infobase

    return await phac_infobase.query(args, result)


async def _phac_describe(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import phac_infobase

    return await phac_infobase.describe(args, result)


async def _phac_list(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import phac_infobase

    return await phac_infobase.list_datasets(args, result)


async def _cfia_reportable(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import cfia

    return await cfia.reportable(args, result)


async def _cfia_detections(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import cfia

    return await cfia.detections(args, result)


async def _cfia_avian_influenza(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce import cfia

    return await cfia.avian_influenza(args, result)


BUILDERS: dict[str, Builder] = {
    "wds_get_data_from_vectors": _vectors,
    "wds_get_data_from_cube_coord": _cube_coord,
    "wds_get_data_by_reference_period_range": _reference_range,
    "sdmx_get_vector_data": _sdmx_vector,
    "sdmx_get_data": _sdmx_data,
    "socrata_query_dataset_rows": _socrata,
    "ckan_datastore_search": _ckan,
    "boc_get_observations": _boc,
    "cer_query_file": _cer_file,
    "gc_infobase_query": _gc_infobase,
    "cihi_get_indicator_data": _cihi,
    "ircc_list_express_entry_rounds": _ircc_rounds,
    "ircc_monthly_query": _ircc_monthly,
    "statcan_indicators_get_indicators": _statcan_indicators,
    "phac_infobase_query": _phac_query,
    "phac_infobase_describe_dataset": _phac_describe,
    "phac_infobase_list_datasets": _phac_list,
    "cfia_reportable_diseases": _cfia_reportable,
    "cfia_disease_detections": _cfia_detections,
    "cfia_avian_influenza": _cfia_avian_influenza,
}

_ONLY_WITH_TRANSFORM = {"wds_get_data_from_cube_coord", "wds_get_data_by_reference_period_range"}

# Tools rebuilt from arguments alone, without running the tool first.
ARGUMENT_ONLY = {
    "wds_get_data_from_vectors",
    "sdmx_get_vector_data",
    "sdmx_get_data",
    "socrata_query_dataset_rows",
    "ckan_datastore_search",
    "boc_get_observations",
    # The PHAC builders load the file (through the tool's cache) and run the
    # tool's own query on it, so running the tool first would repeat that.
    "phac_infobase_query",
    "phac_infobase_describe_dataset",
    "phac_infobase_list_datasets",
    # The CFIA builders run the tool's own client (its cache holds the parsed
    # pages) to validate the arguments and read each page's title and date.
    "cfia_reportable_diseases",
    "cfia_disease_detections",
    "cfia_avian_influenza",
}


def _require_tool_name(tool: str) -> None:
    """Refuse a name no registered tool can have before a name prefix picks a builder.

    The product-id and PUMF routes match on a prefix and skip the tool, so a name
    that only starts like a StatCan tool must not reach them. client._spec then
    checks that the name is registered.
    """
    if not _TOOL_NAME.fullmatch(tool):
        raise call_error(
            InvalidInput,
            f"{tool!r} is not a tool name: tool names hold lowercase letters, digits and '_'.",
            f"{tool!r} n'est pas un nom d'outil : les noms d'outils ne contiennent que des "
            "lettres minuscules, des chiffres et '_'.",
        )


def builder_for(tool: str, args: dict[str, Any]) -> Builder | None:
    """The builder for a tool, including the product-id and PUMF families."""
    _require_tool_name(tool)
    # Without a transform these two are reproduced as before: the full table
    # for a coordinate, and the recorded request for a reference-period range.
    if tool in _ONLY_WITH_TRANSFORM and transform_request(args) is None:
        if tool == "wds_get_data_from_cube_coord":
            return _table
        return None
    if tool in BUILDERS:
        return BUILDERS[tool]
    if "product_id" in args and tool.startswith(("wds_", "sdmx_")):
        return _table
    if tool.startswith("statcan_pumf_") and str(args.get("url", "")).endswith(".zip"):
        return _pumf
    return None


def argument_only(tool: str, args: dict[str, Any]) -> bool:
    _require_tool_name(tool)
    if transform_request(args) is not None:
        return False  # the scripts read each series' frequency and unit off the tool's result
    if tool == "sdmx_get_vector_data" and (args.get("start_period") or args.get("end_period")):
        return False  # the SDMX key comes from the tool's WDS lookup
    if tool in ARGUMENT_ONLY:
        return True
    if "product_id" in args and tool.startswith(("wds_", "sdmx_")):
        return True
    return tool.startswith("statcan_pumf_") and str(args.get("url", "")).endswith(".zip")

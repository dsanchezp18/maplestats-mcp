"""Specs for tools whose request can be rebuilt exactly from their arguments,
or whose filtering happens in MapleStats after the download.

Every other tool is reproduced from the requests recorded while it ran
(probe.py). A builder here is needed when that recording is not enough:
the tool downloads a whole file and filters it itself (CER,
GC InfoBase, CIHI, IRCC, StatCan indicators, PHAC Health Infobase in
phac_infobase.py, IP Horizons), the tool parses HTML tables itself (CFIA
in cfia.py), or a better
native path exists (cansim for StatCan tables, canivt for Beyond 20/20).

Each builder takes the tool's arguments and its result payload (the tool
has already run) and returns a Spec.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from maplestats_mcp.modules.reproduce.spec import Code, Filter, Spec
from maplestats_mcp.shared.errors import InvalidInput

Builder = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Spec]]
_WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"
_SDMX = "https://www150.statcan.gc.ca/t1/wds/sdmx/statcan/rest/"
_EXACT = "exact: rebuilt from the tool's arguments"
_FILTERED = "exact: the source file, then the tool's filters"


def _suffix(args: dict[str, Any]) -> str:
    return "eng" if str(args.get("lang", "en")) == "en" else "fra"


# StatCan --------------------------------------------------------------------


def table_spec(product_id: Any, lang: str) -> Spec:
    pid = str(product_id).replace("-", "")[:8]
    if not pid.isdigit() or len(pid) != 8:
        raise InvalidInput(
            f"product_id must be an 8- or 10-digit StatCan table id, got {product_id!r}."
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


def vector_spec(vector_ids: list[Any], latest_n: int) -> Spec:
    ids = [int(str(v).lstrip("vV")) for v in vector_ids]
    r_ids = ", ".join(f'"v{i}"' for i in ids)
    return Spec(
        kind="json",
        url=_WDS + "getDataFromVectorsAndLatestNPeriods",
        file_name="vectors.json",
        method="exact: WDS vectors request from the vector ids",
        title="StatCan vectors",
        records_path=["object", "vectorDataPoint"],
        each_item=True,
        post_json=[{"vectorId": i, "latestN": latest_n} for i in ids],
        native={"r": Code(["cansim"], f"data <- get_cansim_vector(c({r_ids}))\n")},
        notes=["WDS returns one object per vector; values are under vectorDataPoint."],
        source="statcan_vectors",
    )


async def _table(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    return table_spec(args["product_id"], str(args.get("lang", "en")))


async def _vectors(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    return vector_spec(args["vector_ids"], int(args.get("latest_n", 12)))


async def _sdmx_data(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.reproduce.excel import sdmx_generic_steps
    from maplestats_mcp.modules.reproduce.render import safe_url

    spec = table_spec(args["product_id"], str(args.get("lang", "en")))
    params = {
        name: args[key]
        for key, name in (
            ("start_period", "startPeriod"),
            ("end_period", "endPeriod"),
            ("last_n_observations", "lastNObservations"),
        )
        if args.get(key) not in (None, "")
    }
    query = f"?{urlencode(params)}" if params else ""
    pid = str(args["product_id"]).replace("-", "")[:8]
    url = safe_url(f"{_SDMX}data/DF_{pid}/{args['key']}{query}")
    # Power Query reads SDMX-ML, so the Excel query fetches only the key's
    # series, as the tool does; the scripts read the full table instead.
    spec.native["excel"] = Code([url], sdmx_generic_steps(url))
    spec.notes.append(
        "The Excel (Power Query) query reads only this key's series from StatCan's SDMX "
        "service, as the tool does; the other scripts download the full table."
    )
    return spec


async def _sdmx_vector(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    # The SDMX-ML the tool reads is XML; WDS serves the same vector as JSON.
    spec = vector_spec([args["vector_id"]], int(args.get("last_n_observations") or 12))
    spec.notes.append("Fetched through WDS, which serves the same vector as JSON.")
    return spec


async def _pumf(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    url = str(args["url"])
    if not url.endswith(".zip"):
        raise InvalidInput("statcan_pumf tools reproduce from a PUMF ZIP url.")
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


async def _census_table(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.statcan.census_tables.constants import HOST, RELEASES

    pid, release = str(args["pid"]), str(args.get("release", "2016"))
    base = f"{HOST}{RELEASES[release].path}"
    ivt_url = f"{base}Download.cfm?PID={pid}"
    canivt = Code(
        ["canivt"],
        (
            '# Install once with remotes::install_github("mountainMath/canivt").\n\n'
            f'download.file("{ivt_url}", "data/raw/table_{pid}.ivt", mode = "wb")\n'
            f'data <- read_ivt("data/raw/table_{pid}.ivt") |>\n  ivt_tidy()\n'
        ),
    )
    if release == "2016":
        return Spec(
            kind="zip_csv",
            url=f"{base}CompDataDownload.cfm?LANG=E&PID={pid}&OFT=CSV",
            file_name=f"census_table_{pid}.zip",
            method="exact: full-table CSV from the PID",
            title=f"Census {release} data table {pid}",
            native={"r": canivt},
            notes=[
                "The R version reads the Beyond 20/20 file with canivt, which keeps dimension labels."
            ],
        )
    return Spec(
        kind="ivt",
        url=ivt_url,
        file_name=f"table_{pid}.ivt",
        method="exact: Beyond 20/20 file from the PID",
        title=f"Census {release} data table {pid}",
        native={"r": canivt},
        languages=("r",),
        notes=[
            (
                f"{release} tables have no full-table CSV; an SDMX ZIP is at "
                f"{base}OpenDataDownload.cfm?PID={pid} for non-R languages."
            ),
        ],
    )


# Open-data platforms -------------------------------------------------------------


async def _socrata(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.socrata.constants import PORTALS

    portal = PORTALS.get(str(args.get("portal")))
    if portal is None:
        raise InvalidInput(f"Unknown Socrata portal {args.get('portal')!r}.")
    soql = {
        f"${key}": args[key]
        for key in ("select", "where", "order", "q", "limit", "offset")
        if args.get(key) not in (None, "")
    }
    query = f"?{urlencode(soql)}" if soql else ""
    return Spec(
        kind="csv",
        url=f"https://{portal.domain}/resource/{args['dataset_id']}.csv{query}",
        file_name=f"{args['dataset_id']}.csv",
        method="exact: SODA query rebuilt from the tool's arguments",
        title=f"Socrata dataset {args['dataset_id']} ({portal.domain})",
        notes=["Remove $limit to download every row (SODA's default page is 1,000 rows)."],
    )


async def _ckan(args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.ckan.constants import PORTALS

    portal = PORTALS.get(str(args.get("portal")))
    if portal is None:
        raise InvalidInput(f"Unknown CKAN portal {args.get('portal')!r}.")
    params: dict[str, Any] = {"resource_id": args["resource_id"]}
    for key, name in (("query", "q"), ("sort", "sort"), ("fields", "fields")):
        if args.get(key) not in (None, ""):
            params[name] = args[key]
    for key in ("limit", "offset"):
        if args.get(key) not in (None, ""):
            params[key] = args[key]
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
    names = ",".join(args["series_names"])
    keys = ("start_date", "end_date", "recent", "recent_weeks", "recent_months", "recent_years")
    params = {key: args[key] for key in keys if args.get(key) not in (None, "")}
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
    "sdmx_get_vector_data": _sdmx_vector,
    "sdmx_get_data": _sdmx_data,
    "socrata_query_dataset_rows": _socrata,
    "ckan_datastore_search": _ckan,
    "boc_get_observations": _boc,
    "statcan_census_tables_get_downloads": _census_table,
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

# Tools rebuilt from arguments alone, without running the tool first.
ARGUMENT_ONLY = {
    "wds_get_data_from_vectors",
    "sdmx_get_vector_data",
    "sdmx_get_data",
    "socrata_query_dataset_rows",
    "ckan_datastore_search",
    "boc_get_observations",
    "statcan_census_tables_get_downloads",
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


def builder_for(tool: str, args: dict[str, Any]) -> Builder | None:
    """The builder for a tool, including the product-id and PUMF families."""
    if tool in BUILDERS:
        return BUILDERS[tool]
    if "product_id" in args and tool.startswith(("wds_", "sdmx_")):
        return _table
    if tool.startswith("statcan_pumf_") and str(args.get("url", "")).endswith(".zip"):
        return _pumf
    return None


def argument_only(tool: str, args: dict[str, Any]) -> bool:
    if tool in ARGUMENT_ONLY:
        return True
    if "product_id" in args and tool.startswith(("wds_", "sdmx_")):
        return True
    return tool.startswith("statcan_pumf_") and str(args.get("url", "")).endswith(".zip")

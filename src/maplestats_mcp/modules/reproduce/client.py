"""Rebuild a tool call as a download spec, then render it per language.

A spec is built from the tool's own arguments where the request can be
reconstructed exactly (StatCan tables and vectors, Bank of Canada Valet,
Socrata, CKAN DataStore, PUMF ZIPs, census tables). Any other tool is
run once and its provenance URL used instead, with a note that filters
applied by the tool may not be part of that URL (checked 2026-09-24:
Valet and Socrata provenance URLs omit the query parameters).

Snippets follow the house conventions: R with the native pipe and
janitor::clean_names(), Python with polars, Julia with TidierFiles,
Stata without cd; every download is saved under data/raw/ first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode

from maplestats_mcp.modules.reproduce import cleaning
from maplestats_mcp.modules.reproduce.schemas import (
    Language,
    LanguageChoice,
    ReproductionCode,
    Script,
)
from maplestats_mcp.shared.envelope import make_provenance
from maplestats_mcp.shared.errors import InvalidInput, NotFound

Kind = Literal["csv", "json", "zip_csv", "zip", "ivt", "html"]

_WDS = "https://www150.statcan.gc.ca/t1/wds/rest/"


@dataclass
class Spec:
    kind: Kind
    url: str
    file_name: str
    method: str
    records_path: list[str] = field(default_factory=list)  # where rows sit in the JSON
    # True when the JSON is a list of objects, each holding rows at records_path
    # (WDS vectors: [{"object": {"vectorDataPoint": [...]}}, ...]).
    each_item: bool = False
    native: dict[str, str] = field(default_factory=dict)  # language -> better native code
    native_packages: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    post_json: Any = None
    source: str = ""  # key into cleaning.SPECIFIC
    # StatCan's French full-table CSVs use ";" (checked 2026-09-24 on 18100004-fra).
    delimiter: str = ","


def _table_spec(product_id: Any, lang: str) -> Spec:
    pid = str(product_id).replace("-", "")[:8]
    if not pid.isdigit() or len(pid) != 8:
        raise InvalidInput(
            f"product_id must be an 8- or 10-digit StatCan table id, got {product_id!r}."
        )
    suffix = "eng" if lang == "en" else "fra"
    dashed = f"{pid[:2]}-{pid[2:4]}-{pid[4:8]}-01"
    return Spec(
        kind="zip_csv",
        url=f"https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-{suffix}.zip",
        file_name=f"{pid}-{suffix}.zip",
        method="exact: full table from the product id",
        native={
            "r": (
                "library(cansim)\nlibrary(dplyr)\n\n"
                f'data <- get_cansim("{dashed}"{', language = "fr"' if lang == "fr" else ""}) |>\n'
                "  janitor::clean_names()\n"
            )
        },
        native_packages={"r": ["cansim", "dplyr", "janitor"]},
        notes=["The full table is downloaded; filter it to the rows the tool returned."],
        # French tables name their columns in French (VALEUR, IDENTIFICATEUR SCALAIRE).
        source="statcan_table" if lang == "en" else "statcan_table_fr",
        delimiter="," if lang == "en" else ";",
    )


def _vector_spec(vector_ids: list[Any], latest_n: int) -> Spec:
    ids = [int(str(v).lstrip("vV")) for v in vector_ids]
    r_ids = ", ".join(f'"v{i}"' for i in ids)
    return Spec(
        kind="json",
        url=_WDS + "getDataFromVectorsAndLatestNPeriods",
        file_name="vectors.json",
        method="exact: WDS vectors request from the vector ids",
        records_path=["object", "vectorDataPoint"],
        each_item=True,
        post_json=[{"vectorId": i, "latestN": latest_n} for i in ids],
        native={
            "r": (
                "library(cansim)\nlibrary(dplyr)\n\n"
                f"data <- get_cansim_vector(c({r_ids})) |>\n  janitor::clean_names()\n"
            )
        },
        native_packages={"r": ["cansim", "janitor"]},
        notes=["WDS returns one object per vector; values are under vectorDataPoint."],
        source="statcan_vectors",
    )


def _socrata_spec(args: dict[str, Any]) -> Spec:
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
        notes=["Remove $limit to download every row (SODA's default page is 1,000 rows)."],
    )


def _ckan_spec(args: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.ckan.constants import PORTALS

    portal = PORTALS.get(str(args.get("portal")))
    if portal is None:
        raise InvalidInput(f"Unknown CKAN portal {args.get('portal')!r}.")
    params: dict[str, Any] = {"resource_id": args["resource_id"]}
    for key, name in (
        ("query", "q"),
        ("sort", "sort"),
        ("fields", "fields"),
        ("limit", "limit"),
        ("offset", "offset"),
    ):
        if args.get(key) not in (None, ""):
            params[name] = args[key]
    if args.get("filters"):
        params["filters"] = json.dumps(args["filters"])
    return Spec(
        kind="json",
        url=f"{portal.base_url}datastore_search?{urlencode(params)}",
        file_name=f"{args['resource_id']}.json",
        method="exact: DataStore query rebuilt from the tool's arguments",
        records_path=["result", "records"],
    )


def _boc_spec(args: dict[str, Any]) -> Spec:
    names = ",".join(args["series_names"])
    params = {
        key: args[key]
        for key in (
            "start_date",
            "end_date",
            "recent",
            "recent_weeks",
            "recent_months",
            "recent_years",
        )
        if args.get(key) not in (None, "")
    }
    query = f"?{urlencode(params)}" if params else ""
    return Spec(
        kind="json",
        url=f"https://www.bankofcanada.ca/valet/observations/{names}/json{query}",
        file_name="valet_observations.json",
        method="exact: Valet request rebuilt from the tool's arguments",
        records_path=["observations"],
        source="valet",
        notes=["Each observation holds one {'v': value} object per series, keyed by series name."],
    )


def _pumf_spec(url: str) -> Spec:
    name = url.rsplit("/", 1)[-1]
    return Spec(
        kind="zip",
        url=url,
        file_name=name,
        method="exact: the PUMF ZIP",
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


def _census_table_spec(pid: str, release: str) -> Spec:
    from maplestats_mcp.modules.statcan.census_tables.constants import HOST, RELEASES

    base = f"{HOST}{RELEASES[release].path}"
    ivt_url = f"{base}Download.cfm?PID={pid}"
    canivt = (
        '# remotes::install_github("mountainMath/canivt")\nlibrary(canivt)\n\n'
        f'download.file("{ivt_url}", "data/raw/table_{pid}.ivt", mode = "wb")\n'
        f'data <- read_ivt("data/raw/table_{pid}.ivt") |>\n  ivt_tidy()\n'
    )
    if release == "2016":
        return Spec(
            kind="zip_csv",
            url=f"{base}CompDataDownload.cfm?LANG=E&PID={pid}&OFT=CSV",
            file_name=f"census_table_{pid}.zip",
            method="exact: full-table CSV from the PID",
            native={"r": canivt},
            native_packages={"r": ["canivt"]},
            notes=[
                "The R version reads the Beyond 20/20 file with canivt, which keeps dimension labels."
            ],
        )
    return Spec(
        kind="ivt",
        url=ivt_url,
        file_name=f"table_{pid}.ivt",
        method="exact: Beyond 20/20 file from the PID",
        native={"r": canivt},
        native_packages={"r": ["canivt"]},
        notes=[
            (
                f"{release} tables have no full-table CSV; an SDMX ZIP is at "
                f"{base}OpenDataDownload.cfm?PID={pid} for non-R languages."
            ),
        ],
    )


def _spec_from_arguments(tool: str, args: dict[str, Any]) -> Spec | None:
    lang = str(args.get("lang", "en"))
    if "product_id" in args and tool.startswith(("wds_", "sdmx_")):
        return _table_spec(args["product_id"], lang)
    if tool == "wds_get_data_from_vectors":
        return _vector_spec(args["vector_ids"], int(args.get("latest_n", 12)))
    if tool == "socrata_query_dataset_rows":
        return _socrata_spec(args)
    if tool == "ckan_datastore_search":
        return _ckan_spec(args)
    if tool == "boc_get_observations":
        return _boc_spec(args)
    if tool.startswith("statcan_pumf_") and str(args.get("url", "")).endswith(".zip"):
        return _pumf_spec(str(args["url"]))
    if tool == "statcan_census_tables_get_downloads":
        return _census_table_spec(str(args["pid"]), str(args.get("release", "2016")))
    return None


def _spec_from_provenance(url: str) -> Spec:
    lower = url.lower().split("?", 1)[0]
    name = lower.rstrip("/").rsplit("/", 1)[-1] or "download"
    note = "Rebuilt from the result's provenance URL; filters the tool applied may not be in it."
    if lower.endswith(".csv"):
        return Spec("csv", url, name, "provenance URL", notes=[note])
    if lower.endswith(".zip"):
        return Spec("zip", url, name, "provenance URL", notes=[note])
    json_markers = (
        "/api/",
        "/json",
        ".json",
        "/rest/",
        "/valet/",
        "/resource/",
        "/query",
        "/items",
    )
    if any(marker in lower for marker in json_markers):
        return Spec(
            "json",
            url,
            f"{name}.json" if not name.endswith(".json") else name,
            "provenance URL",
            notes=[note],
        )
    return Spec(
        "html",
        url,
        name,
        "provenance URL",
        notes=[
            (
                "This source is a web page that the tool parses, not a data file, so a plain "
                "download does not reproduce the result. Cite the URL and the retrieval date, or "
                "keep the tool's output as the raw input."
            )
        ],
    )


# Rendering -----------------------------------------------------------------


def _r(spec: Spec) -> tuple[str, list[str]]:
    path = f"data/raw/{spec.file_name}"
    read = (
        "read_csv(" if spec.delimiter == "," else f'read_delim(delim = "{spec.delimiter}", file = '
    )
    if spec.kind == "csv":
        return (
            (
                "library(readr)\n\n"
                f'download.file("{spec.url}", "{path}", mode = "wb")\n\n'
                f'data <- {read}"{path}") |>\n  janitor::clean_names()\n'
            ),
            ["readr", "janitor"],
        )
    if spec.kind in ("zip", "zip_csv"):
        folder = f"data/raw/{spec.file_name.removesuffix('.zip')}"
        return (
            (
                "library(readr)\nlibrary(stringr)\n\n"
                f'download.file("{spec.url}", "{path}", mode = "wb")\n'
                f'unzip("{path}", exdir = "{folder}")\n'
                f'file.remove("{path}")\n\n'
                "# The ZIP may also hold a metadata CSV; read the data file.\n\n"
                f'data_files <- list.files("{folder}", pattern = "[.]csv$", full.names = TRUE, '
                "recursive = TRUE)\n"
                'data_files <- data_files[!str_detect(str_to_lower(data_files), "metadata")]\n'
                f"data <- {read}data_files[1]) |>\n  janitor::clean_names()\n"
            ),
            ["readr", "stringr", "janitor"],
        )
    if spec.kind == "json":
        records = "".join(f'[["{key}"]]' for key in spec.records_path)
        if spec.post_json is not None:
            body = json.dumps(spec.post_json)
            request = (
                f'response <- request("{spec.url}") |>\n'
                f"  req_body_raw('{body}', type = \"application/json\") |>\n  req_perform()\n"
            )
        else:
            request = f'response <- request("{spec.url}") |>\n  req_perform()\n'
        return (
            "library(httr2)\nlibrary(jsonlite)\nlibrary(tibble)\n\n"
            + request
            + f'\nwriteLines(resp_body_string(response), "{path}")\n\n'
            f'records <- fromJSON("{path}", flatten = TRUE){records}\n'
            "data <- as_tibble(records) |>\n  janitor::clean_names()\n",
            ["httr2", "jsonlite", "tibble", "janitor"],
        )
    return f'download.file("{spec.url}", "{path}", mode = "wb")\n', []


def _python_records(spec: Spec, payload: str) -> str:
    walk = "".join(f'["{key}"]' for key in spec.records_path)
    if spec.each_item:
        return f"records = [row for item in {payload} for row in item{walk}]"
    return f"records = {payload}{walk}"


def _python_fetch(spec: Spec, name: str) -> str:
    # http2=True is required: StatCan drops TLS connections from clients that
    # offer only HTTP/1.1 (see shared/http.py), so a plain httpx.get fails there.
    call = (
        f'client.post("{spec.url}", json={spec.post_json!r})'
        if spec.post_json is not None
        else f'client.get("{spec.url}")'
    )
    return (
        "with httpx.Client(http2=True, follow_redirects=True, timeout=300) as client:\n"
        f"    {name} = {call}"
    )


def _python(spec: Spec) -> tuple[str, list[str]]:
    head = (
        "from pathlib import Path\n\nimport httpx\nimport polars as pl\n\n"
        'RAW_DIR = Path("data/raw")\nRAW_DIR.mkdir(parents=True, exist_ok=True)\n'
        f'raw_path = RAW_DIR / "{spec.file_name}"\n\n'
    )
    fetch = f"{_python_fetch(spec, 'response')}\n"
    save = "response.raise_for_status()\nraw_path.write_bytes(response.content)\n\n"
    packages = ["httpx[http2]", "polars"]
    separator = "" if spec.delimiter == "," else f', separator="{spec.delimiter}"'
    if spec.kind == "csv":
        return (
            head
            + fetch
            + save
            + f"data = pl.read_csv(raw_path, infer_schema_length=100_000{separator})\n",
            packages,
        )
    if spec.kind in ("zip", "zip_csv"):
        return (
            head.replace("import httpx\n", "import zipfile\n\nimport httpx\n")
            + fetch
            + save
            + "# The ZIP may also hold a metadata CSV; read the data file.\n\n"
            + "with zipfile.ZipFile(raw_path) as archive:\n"
            + "    data_name = next(\n"
            + "        n\n"
            + "        for n in archive.namelist()\n"
            + '        if n.lower().endswith(".csv") and "metadata" not in n.lower()\n'
            + "    )\n"
            + "    archive.extract(data_name, RAW_DIR)\n\n"
            + f"data = pl.read_csv(RAW_DIR / data_name, infer_schema_length=100_000{separator})\n",
            packages,
        )
    if spec.kind == "json":
        payload = 'json.loads(raw_path.read_text(encoding="utf-8"))'
        return (
            head.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n")
            + fetch
            + save
            + f"{_python_records(spec, payload)}\n"
            + "data = pl.json_normalize(records)\n",
            packages,
        )
    return head + fetch + save, ["httpx[http2]"]


def _stata(spec: Spec) -> tuple[str, list[str]]:
    path = f"data/raw/{spec.file_name}"
    delimiters = "" if spec.delimiter == "," else f' delimiters("{spec.delimiter}")'
    if spec.kind == "csv":
        return (
            (
                f'copy "{spec.url}" "{path}", replace\n'
                f'import delimited "{path}", clear varnames(1){delimiters}\n'
            ),
            [],
        )
    if spec.kind in ("zip", "zip_csv"):
        folder = f"data/raw/{spec.file_name.removesuffix('.zip')}"
        return (
            (
                f'local folder "{folder}"\n'
                f'copy "{spec.url}" "{path}", replace\n'
                'capture mkdir "`folder\'"\n\n'
                "* unzipfile extracts into the working directory; tar (Windows 10+, macOS,\n"
                "* Linux) extracts into the folder without a cd.\n\n"
                f'shell tar -xf "{path}" -C "`folder\'"\n'
                "* The ZIP may also hold a metadata CSV; read the data file.\n\n"
                'local csv_files : dir "`folder\'" files "*.csv"\n'
                "foreach file of local csv_files {\n"
                '    if strpos(lower("`file\'"), "metadata") == 0 {\n'
                "        local data_csv `file'\n"
                "    }\n"
                "}\n"
                f"import delimited \"`folder'/`data_csv'\", clear varnames(1){delimiters}\n"
            ),
            [],
        )
    if spec.kind == "json":
        # Stata has no JSON reader; its built-in Python integration (Stata 16+) does it.
        return (
            (
                "python:\n"
                "import httpx\nimport polars as pl\n\n"
                f"{_python_fetch(spec, 'response')}\n"
                "response.raise_for_status()\n"
                f"{_python_records(spec, 'response.json()')}\n"
                f'pl.json_normalize(records).write_csv("data/raw/{spec.file_name.removesuffix(".json")}.csv")\n'
                "end\n\n"
                f'import delimited "data/raw/{spec.file_name.removesuffix(".json")}.csv", clear varnames(1)\n'
            ),
            ["python: httpx[http2], polars"],
        )
    return f'copy "{spec.url}" "{path}", replace\n', []


def _julia(spec: Spec) -> tuple[str, list[str]]:
    path = f"data/raw/{spec.file_name}"
    head = "using Downloads\nusing TidierFiles\n\n"
    delim = "" if spec.delimiter == "," else f', delim = "{spec.delimiter}"'
    if spec.kind == "csv":
        return (
            head
            + f'Downloads.download("{spec.url}", "{path}")\ndata = read_csv("{path}"{delim})\n',
            ["TidierFiles"],
        )
    if spec.kind in ("zip", "zip_csv"):
        return (
            (
                "using Downloads\nusing TidierFiles\nusing ZipFile\n\n"
                f'Downloads.download("{spec.url}", "{path}")\n'
                f'archive = ZipFile.Reader("{path}")\n\n'
                "# The ZIP may also hold a metadata CSV; read the data file.\n\n"
                "data_file = first(\n"
                "    f for f in archive.files\n"
                '    if endswith(lowercase(f.name), ".csv") && !occursin("metadata", lowercase(f.name))\n'
                ")\n"
                'write("data/raw/table.csv", read(data_file))\nclose(archive)\n'
                f'data = read_csv("data/raw/table.csv"{delim})\n'
            ),
            ["TidierFiles", "ZipFile"],
        )
    if spec.kind == "json":
        walk = "".join(f'["{key}"]' for key in spec.records_path)
        # Downloads.jl uses libcurl, which offers HTTP/2 as StatCan requires.
        if spec.post_json is not None:
            fetch = (
                f'Downloads.request("{spec.url}"; method = "POST", '
                'headers = ["Content-Type" => "application/json"], '
                f"input = IOBuffer({json.dumps(json.dumps(spec.post_json))}), "
                f'output = "{path}")'
            )
        else:
            fetch = f'Downloads.download("{spec.url}", "{path}")'
        payload = f'JSON3.read(read("{path}", String))'
        records = (
            f"records = reduce(vcat, [collect(item{walk}) for item in {payload}])"
            if spec.each_item
            else f"records = {payload}{walk}"
        )
        return (
            (
                "using DataFrames\nusing Downloads\nusing JSON3\n\n"
                f"{fetch}\n"
                f"{records}\n"
                "data = DataFrame(records)\n"
            ),
            ["DataFrames", "JSON3"],
        )
    return f'using Downloads\n\nDownloads.download("{spec.url}", "{path}")\n', []


_RENDERERS = {"r": _r, "python": _python, "stata": _stata, "julia": _julia}


async def _provenance_url(tool: str, args: dict[str, Any]) -> str:
    # Lazy import: the server imports this module's tools at startup.
    from fastmcp import Client
    from mcp.types import TextContent

    from maplestats_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "call_tool", {"name": tool, "arguments": args}, raise_on_error=False
        )
    text = next((block.text for block in result.content if isinstance(block, TextContent)), "")
    if result.is_error:
        raise InvalidInput(
            f"{tool} failed with these arguments, so there is nothing to reproduce: {text[:300]}"
        )
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise NotFound(f"{tool} did not return a result with provenance.") from exc
    url = payload.get("provenance", {}).get("url") if isinstance(payload, dict) else None
    if not url:
        raise NotFound(f"{tool} results carry no source URL to reproduce.")
    return str(url)


def _script(spec: Spec, language: Language) -> Script | None:
    """Retrieval plus cleaning in one language, or None when it cannot read the source."""
    if spec.kind == "html":
        return None
    if spec.kind == "ivt" and language != "r":
        return None  # only canivt (R) reads Beyond 20/20 files
    if language in spec.native:
        code, packages = spec.native[language], list(spec.native_packages.get(language, []))
    else:
        code, packages = _RENDERERS[language](spec)
    if spec.kind in ("csv", "json", "zip_csv") or language in spec.native:
        code = f"{code}\n{cleaning.cleaning(language, spec.source)}"
        packages += cleaning.PACKAGES[language]
    return Script(language=language, code=code, packages=sorted(set(packages)))


async def reproduce(
    tool: str, arguments: dict[str, Any], language: LanguageChoice = "all"
) -> ReproductionCode:
    languages: list[Language] = (
        ["r", "python", "stata", "julia"] if language == "all" else [language]  # type: ignore[list-item]
    )
    if any(lang not in _RENDERERS for lang in languages):
        raise InvalidInput(
            f"language must be 'all' or one of {sorted(_RENDERERS)}, got {language!r}."
        )
    if tool in ("reproduce_code", "plan_query", "search_tools", "call_tool"):
        raise InvalidInput(f"{tool} does not fetch data, so there is nothing to reproduce.")
    try:
        spec = _spec_from_arguments(tool, arguments)
    except KeyError as exc:
        raise InvalidInput(f"{tool} is missing the argument {exc.args[0]!r}.") from exc
    if spec is None:
        spec = _spec_from_provenance(await _provenance_url(tool, arguments))

    scripts = [s for s in (_script(spec, lang) for lang in languages) if s is not None]
    skipped = [lang for lang in languages if lang not in {s.language for s in scripts}]
    if skipped and spec.kind == "ivt":
        spec.notes.append(
            f"No {', '.join(skipped)} script: Beyond 20/20 IVT files are read only by canivt "
            "(R); use the SDMX file in other languages."
        )
    if spec.kind == "zip":
        spec.notes.append(
            "Cleaning is not applied to ZIP contents automatically: pick the data file first."
        )
    return ReproductionCode(
        tool=tool,
        scripts=scripts,
        source_url=spec.url,
        method=spec.method,
        notes=spec.notes,
        provenance=make_provenance(
            source="maplestats-reproduce",
            url=spec.url,
            cached=False,
            schema_name="reproduce.ReproductionCode",
        ),
    )

"""Scripts for the IP Horizons patent tools, which join bulk files.

ised_ip_horizons_get_patent and _search_patents read pipe-delimited
CSVs inside ZIPs (hundreds of MB each), join tables on the patent number
and filter; no single URL reproduces that. These scripts download only
the tables and number ranges the query used, read them with every column
as text (the files write NULL for missing and pad some dates with a
leading space), and repeat the tool's filters and joins.

opic-cipo.ca omits its RapidSSL intermediate certificate (see
ised/ip_horizons/client.py). The Python scripts add it from the issuer,
on top of certifi's roots, so verification still anchors at a root.
"""

from __future__ import annotations

import json
import re
from typing import Any

from maplestats_mcp.modules.reproduce.spec import Code, Spec

_TLS_NOTE = (
    "opic-cipo.ca omits its intermediate certificate. Windows fetches it automatically; "
    "on Linux or macOS, R, Stata and Julia need RapidSSL TLS RSA CA G1 "
    "(http://cacerts.rapidssl.com/RapidSSLTLSRSACAG1.crt) in the system trust store."
)
_IPC = re.compile(r"^([A-H])(\d{2})([A-Z])(?:\s*(\d{1,4})(?:/(\d{1,6}))?)?$")


def _files(groups: dict[str, list[Any]]) -> dict[str, str]:
    return {
        f"{table}_{index + 1}": item.url
        for table, items in groups.items()
        for index, item in enumerate(items)
    }


def _py_body(files: dict[str, str], steps: str) -> Code:
    listing = "".join(f"    {name!r}: {url!r},\n" for name, url in files.items())
    body = (
        "# CIPO's server omits its RapidSSL intermediate certificate; add it from the\n"
        "# issuer on top of certifi's roots, so verification still anchors at a root.\n\n"
        'intermediate = httpx.get("http://cacerts.rapidssl.com/RapidSSLTLSRSACAG1.crt").content\n'
        "tls = ssl.create_default_context(cafile=certifi.where())\n"
        "tls.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(intermediate))\n\n"
        f"files = {{\n{listing}}}\n"
        "tables = {}\n"
        "with httpx.Client(verify=tls, timeout=900, follow_redirects=True) as client:\n"
        "    for name, url in files.items():\n"
        '        zip_path = RAW_DIR / f"{name}.zip"\n'
        '        with client.stream("GET", url) as response, zip_path.open("wb") as handle:\n'
        "            response.raise_for_status()\n"
        "            for chunk in response.iter_bytes(1 << 20):\n"
        "                handle.write(chunk)\n"
        "        with zipfile.ZipFile(zip_path) as archive:\n"
        "            member = archive.namelist()[0]\n"
        "            archive.extract(member, RAW_DIR)\n\n"
        '        # Every column as text; headers are bilingual ("Patent Number - Numéro\n'
        '        # du brevet"), so keep the English half in snake_case.\n\n'
        "        tables[name] = (\n"
        "            pl.scan_csv(\n"
        "                RAW_DIR / member,\n"
        '                separator="|",\n'
        "                quote_char=None,\n"
        '                null_values=["NULL"],\n'
        "                infer_schema=False,\n"
        "            )\n"
        "            .rename(\n"
        "                lambda column: re.sub(\n"
        '                    r"[^a-z0-9]+", "_", column.split(" - ")[0].strip().lower()\n'
        '                ).strip("_")\n'
        "            )\n"
        "            .with_columns(pl.all().str.strip_chars())\n"
        "        )\n\n"
        f"{steps}"
    )
    imports = [
        "import re",
        "import ssl",
        "import zipfile",
        "from pathlib import Path",
        "import certifi",
        "import httpx",
        "import polars as pl",
    ]
    return Code(imports, body)


def _r_body(files: dict[str, str], steps: str) -> Code:
    listing = ",\n".join(f"  {name} = {json.dumps(url)}" for name, url in files.items())
    body = (
        f"files <- c(\n{listing}\n)\n\n"
        "walk2(\n"
        "  files,\n"
        "  names(files),\n"
        '  \\(url, name) download.file(url, str_c("data/raw/", name, ".zip"), mode = "wb")\n'
        ")\n\n"
        '# Every column as text; headers are bilingual ("Patent Number - Numéro du\n'
        '# brevet"), so keep the English half in snake_case.\n\n'
        "tables <- names(files) |>\n"
        "  map(\n"
        '    \\(name) unzip(str_c("data/raw/", name, ".zip"), exdir = "data/raw") |>\n'
        "      read_delim(\n"
        '        delim = "|",\n'
        '        quote = "",\n'
        '        na = c("", "NULL"),\n'
        "        col_types = cols(.default = col_character()),\n"
        "        trim_ws = TRUE\n"
        "      ) |>\n"
        '      rename_with(\\(x) str_split_i(x, " - ", 1) |> make_clean_names())\n'
        "  ) |>\n"
        "  set_names(names(files))\n\n"
        f"{steps}"
    )
    return Code(["dplyr", "janitor", "purrr", "readr", "stringr"], body)


def _jl_body(files: dict[str, str], steps: str) -> Code:
    listing = ",\n".join(f"    {json.dumps(n)} => {json.dumps(u)}" for n, u in files.items())
    body = (
        f"files = Dict(\n{listing},\n)\n"
        "tables = Dict{String, DataFrame}()\n"
        "for (name, url) in files\n"
        '    zip_path = "data/raw/$(name).zip"\n'
        "    Downloads.download(url, zip_path)\n"
        "    archive = ZipFile.Reader(zip_path)\n"
        "    member = archive.files[1]\n"
        '    csv_path = "data/raw/$(member.name)"\n'
        "    write(csv_path, read(member))\n"
        "    close(archive)\n\n"
        "    # Every column as text; keep the English half of each bilingual header.\n\n"
        "    table = CSV.read(csv_path, DataFrame; delim = '|', quoted = false, missingstring = \"NULL\", types = String)\n"
        '    rename!(table, [lowercase(replace(strip(split(n, " - ")[1]), r"[^A-Za-z0-9]+" => "_")) for n in names(table)])\n'
        "    tables[name] = mapcols(col -> [ismissing(x) ? missing : strip(x) for x in col], table)\n"
        "end\n\n"
        f"{steps}"
    )
    return Code(["CSV", "DataFrames", "Downloads", "ZipFile"], body)


def _group_names(files: dict[str, str], table: str) -> list[str]:
    return [name for name in files if name.startswith(f"{table}_")]


def patent_spec(number: int, groups: dict[str, list[Any]], include_classes: bool) -> Spec:
    files = _files(groups)
    number_text = json.dumps(str(number))
    main, party = _group_names(files, "main"), _group_names(files, "interested_party")
    ipc = _group_names(files, "ipc_classification")
    py_steps = (
        f'data = tables["{main[0]}"].filter(pl.col("patent_number") == {number_text}).collect()\n'
        f'parties = tables["{party[0]}"].filter(pl.col("patent_number") == {number_text}).collect()\n'
    )
    r_steps = (
        f"data <- tables[[{json.dumps(main[0])}]] |>\n"
        f"  filter(patent_number == {number_text})\n"
        f"parties <- tables[[{json.dumps(party[0])}]] |>\n"
        f"  filter(patent_number == {number_text})\n"
    )
    jl_steps = (
        f'data = filter(row -> row.patent_number == {number_text}, tables["{main[0]}"])\n'
        f'parties = filter(row -> row.patent_number == {number_text}, tables["{party[0]}"])\n'
    )
    if include_classes and ipc:
        py_steps += f'classes = tables["{ipc[0]}"].filter(pl.col("patent_number") == {number_text}).collect()\n'
        r_steps += (
            f"classes <- tables[[{json.dumps(ipc[0])}]] |>\n"
            f"  filter(patent_number == {number_text})\n"
        )
        jl_steps += (
            f'classes = filter(row -> row.patent_number == {number_text}, tables["{ipc[0]}"])\n'
        )
    first = next(iter(groups.values()))[0]
    return Spec(
        kind="zip_csv",
        url=first.url,
        file_name=first.url.rsplit("/", 1)[-1],
        method="exact: the IP Horizons files covering this patent, then the tool's lookup",
        title=f"Canadian patent {number} (CIPO IP Horizons)",
        native={
            "python": _py_body(files, py_steps),
            "r": _r_body(files, r_steps),
            "julia": _jl_body(files, jl_steps),
        },
        notes=[
            "`data` holds the patent; `parties` its owners, inventors, applicants and agents"
            + ("; `classes` its IPC classes." if include_classes and ipc else "."),
            _TLS_NOTE,
        ],
    )


def search_spec(args: dict[str, Any], groups: dict[str, list[Any]]) -> Spec:
    files = _files(groups)
    main = _group_names(files, "main")
    party = _group_names(files, "interested_party")
    ipc = _group_names(files, "ipc_classification")
    py_filters: list[str] = []
    r_filters: list[str] = []
    jl_filters: list[str] = []
    title = str(args.get("title") or "").strip()
    for term in title.lower().split():
        py_filters.append(
            'pl.concat_str([pl.col("application_patent_title_english").fill_null(""), '
            'pl.col("application_patent_title_french").fill_null("")], separator=" ")'
            f".str.to_lowercase().str.contains({json.dumps(term)}, literal=True)"
        )
        r_filters.append(
            'str_detect(str_c(coalesce(application_patent_title_english, ""), '
            'coalesce(application_patent_title_french, ""), sep = " "), '
            f"fixed({json.dumps(term)}, ignore_case = TRUE))"
        )
        jl_filters.append(
            f'occursin({json.dumps(term)}, lowercase(string(coalesce(row.application_patent_title_english, ""), '
            '" ", coalesce(row.application_patent_title_french, ""))))'
        )
    for key, symbol in (("filed_from", ">="), ("filed_to", "<=")):
        if args.get(key):
            value = json.dumps(str(args[key]))
            # Unknown filing dates are "-1"; the ISO pattern keeps them out of a range.
            py_filters.append(
                f'pl.col("filing_date").str.contains(r"^\\d{{4}}-\\d{{2}}-\\d{{2}}$"), '
                f'pl.col("filing_date") {symbol} {value}'
            )
            r_filters.append(
                'str_detect(filing_date, "^\\\\d{4}-\\\\d{2}-\\\\d{2}$"), '
                f"filing_date {symbol} {value}"
            )
            jl_filters.append(
                f'!ismissing(row.filing_date) && occursin(r"^\\d{{4}}-\\d{{2}}-\\d{{2}}$", row.filing_date) '
                f"&& row.filing_date {symbol} {value}"
            )
    py_joins: list[str] = []
    r_joins: list[str] = []
    jl_joins: list[str] = []
    party_types = {
        "owner": "Owner",
        "inventor": "Inventor",
        "applicant": "Applicant",
        "agent": "Agent",
    }
    if args.get("party_name"):
        name = json.dumps(str(args["party_name"]).strip().lower())
        kind = party_types.get(str(args.get("party_type") or "").lower())
        py_party = f'pl.col("party_name").str.to_lowercase().str.contains({name}, literal=True)'
        r_party = f"str_detect(party_name, fixed({name}, ignore_case = TRUE))"
        jl_party = f'occursin({name}, lowercase(coalesce(row.party_name, "")))'
        if kind:
            py_party += f', pl.col("interested_party_type") == {json.dumps(kind)}'
            r_party += f", interested_party_type == {json.dumps(kind)}"
            jl_party += f' && coalesce(row.interested_party_type, "") == {json.dumps(kind)}'
        py_joins.append(
            "matching_parties = (\n"
            f"    pl.concat([tables[name] for name in {party!r}])\n"
            f"    .filter({py_party})\n"
            '    .select("patent_number")\n'
            "    .unique()\n"
            ")\n"
            'patents = patents.join(matching_parties, on="patent_number", how="semi")\n'
        )
        r_joins.append(
            f"matching_parties <- bind_rows(tables[c({', '.join(json.dumps(p) for p in party)})]) |>\n"
            f"  filter({r_party}) |>\n"
            "  distinct(patent_number)\n"
            "patents <- patents |>\n"
            "  semi_join(matching_parties, by = join_by(patent_number))\n"
        )
        jl_joins.append(
            f"matching_parties = filter(row -> {jl_party}, vcat([tables[n] for n in {json.dumps(party)}]...))\n"
            'patents = semijoin(patents, unique(matching_parties[:, ["patent_number"]]), on = "patent_number")\n'
        )
    match = _IPC.match(" ".join(str(args.get("ipc") or "").upper().split()))
    if match:
        section, klass, subclass, group, subgroup = match.groups()
        py_ipc = [
            f'pl.col("ipc_section_code") == {json.dumps(section)}',
            f'pl.col("ipc_class_code") == {json.dumps(klass)}',
            f'pl.col("ipc_subclass_code") == {json.dumps(subclass)}',
        ]
        r_ipc = [
            f"ipc_section_code == {json.dumps(section)}",
            f"ipc_class_code == {json.dumps(klass)}",
            f"ipc_subclass_code == {json.dumps(subclass)}",
        ]
        jl_ipc = [
            f"row.ipc_section_code == {json.dumps(section)}",
            f"row.ipc_class_code == {json.dumps(klass)}",
            f"row.ipc_subclass_code == {json.dumps(subclass)}",
        ]
        if group:
            py_ipc.append(
                f'pl.col("ipc_main_group_code").cast(pl.Int64, strict=False) == {int(group)}'
            )
            r_ipc.append(f"as.integer(ipc_main_group_code) == {int(group)}")
            jl_ipc.append(f'tryparse(Int, coalesce(row.ipc_main_group_code, "")) == {int(group)}')
        if subgroup:
            value = json.dumps(subgroup.lstrip("0"))
            py_ipc.append(f'pl.col("ipc_subgroup_code").str.strip_chars_start("0") == {value}')
            r_ipc.append(f'str_remove(ipc_subgroup_code, "^0+") == {value}')
            jl_ipc.append(f"lstrip(coalesce(row.ipc_subgroup_code, \"\"), '0') == {value}")
        py_joins.append(
            "matching_classes = (\n"
            f"    pl.concat([tables[name] for name in {ipc!r}])\n"
            f"    .filter({', '.join(py_ipc)})\n"
            '    .select("patent_number")\n'
            "    .unique()\n"
            ")\n"
            'patents = patents.join(matching_classes, on="patent_number", how="semi")\n'
        )
        r_joins.append(
            f"matching_classes <- bind_rows(tables[c({', '.join(json.dumps(p) for p in ipc)})]) |>\n"
            f"  filter({', '.join(r_ipc)}) |>\n"
            "  distinct(patent_number)\n"
            "patents <- patents |>\n"
            "  semi_join(matching_classes, by = join_by(patent_number))\n"
        )
        jl_joins.append(
            f"matching_classes = filter(row -> {' && '.join(jl_ipc)}, vcat([tables[n] for n in {json.dumps(ipc)}]...))\n"
            'patents = semijoin(patents, unique(matching_classes[:, ["patent_number"]]), on = "patent_number")\n'
        )
    py_where = f".filter({', '.join(py_filters)})" if py_filters else ""
    r_where = f" |>\n  filter({', '.join(r_filters)})" if r_filters else ""
    jl_where = " && ".join(f"({f})" for f in jl_filters)
    py_steps = (
        f"patents = pl.concat([tables[name] for name in {main!r}]){py_where}\n"
        + "".join(py_joins)
        + 'data = patents.sort("filing_date", descending=True, nulls_last=True).collect()\n'
    )
    r_steps = (
        f"patents <- bind_rows(tables[c({', '.join(json.dumps(m) for m in main)})]){r_where}\n"
        + "".join(r_joins)
        + "data <- patents |>\n  arrange(desc(filing_date))\n"
    )
    jl_steps = (
        f"patents = vcat([tables[n] for n in {json.dumps(main)}]...)\n"
        + (f"patents = filter(row -> {jl_where}, patents)\n" if jl_where else "")
        + "".join(jl_joins)
        + 'data = sort(patents, "filing_date"; rev = true)\n'
    )
    first = groups["main"][0]
    return Spec(
        kind="zip_csv",
        url=first.url,
        file_name=first.url.rsplit("/", 1)[-1],
        method="exact: the IP Horizons tables the search used, then the tool's filters",
        title="Canadian patent search (CIPO IP Horizons)",
        native={
            "python": _py_body(files, py_steps),
            "r": _r_body(files, r_steps),
            "julia": _jl_body(files, jl_steps),
        },
        notes=[
            "Name and title filters are case-insensitive substrings, as in the tool.",
            "The party and IPC tables are large (up to 2.6 GB unzipped); expect minutes.",
            _TLS_NOTE,
        ],
    )


async def build(tool: str, args: dict[str, Any], result: dict[str, Any]) -> Spec:
    from maplestats_mcp.modules.ised.ip_horizons import client

    if tool == "ised_ip_horizons_get_patent":
        number = int(args["patent_number"])
        tables = ["main", "interested_party"]
        if args.get("include_classifications"):
            tables.append("ipc_classification")
        groups = {}
        for table in tables:
            covering = client._covering(await client._patent_files(table), number)
            if covering is not None:
                groups[table] = [covering]
        return patent_spec(number, groups, bool(args.get("include_classifications")))
    tables = ["main"]
    if args.get("party_name"):
        tables.append("interested_party")
    if args.get("ipc"):
        tables.append("ipc_classification")
    groups = {table: await client._patent_files(table) for table in tables}
    return search_spec(args, groups)

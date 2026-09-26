"""Render a Spec as a complete R, Python, Stata or Julia script.

Every script follows the house layout: a header block, then numbered
sections (0. Setup with every package, 1. Read inputs, 2. Check inputs,
3. Prepare data). Downloads are saved under data/raw/ before reading.
Filters run right after loading, on the source's own column names.
"""

from __future__ import annotations

import io
import json
import re
import tokenize
from typing import Any
from urllib.parse import urlencode

from maplestats_mcp.modules.reproduce import cleaning
from maplestats_mcp.modules.reproduce.spec import Filter, Spec

_STDLIB = {"io", "json", "pathlib", "re", "ssl", "unicodedata", "xml", "zipfile"}


def _header(prefix: str, spec: Spec, tool: str) -> str:
    rule = f"{prefix} {'=' * 60}"
    output = {
        "zip": "the unzipped files",
        "file": "the downloaded file",
    }.get(spec.kind, "the prepared table as `data`")
    return (
        f"{rule}\n"
        f"{prefix} {spec.title or 'Reproduce ' + tool}\n"
        f"{prefix} Purpose: Fetch the data behind MapleStats MCP's {tool}\n"
        f"{prefix}          ({spec.method})\n"
        f"{prefix} Inputs:  {spec.url}\n"
        f"{prefix} Outputs: data/raw/{spec.file_name}; {output}\n"
        f"{rule}\n"
    )


def _join(*blocks: str) -> str:
    return "\n".join(block.rstrip("\n") + "\n" for block in blocks if block.strip())


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


# R ----------------------------------------------------------------------


def _r_filter(item: Filter) -> str:
    columns = [f"`{c}`" for c in item.columns]
    if item.op == "contains":
        return f"str_detect({columns[0]}, fixed({_quote(str(item.value))}, ignore_case = TRUE))"
    if item.op == "terms":
        cells = ", ".join(f'coalesce(as.character({c}), "")' for c in columns)
        haystack = f'str_c({cells}, sep = " ")'
        return ",\n    ".join(
            f"str_detect({haystack}, fixed({_quote(term)}, ignore_case = TRUE))"
            for term in str(item.value).lower().split()
        )
    if item.op == "is":
        value = _quote(str(item.value).strip().lower())
        return f"str_to_lower(str_trim({columns[0]})) == {value}"
    if item.op == "starts":
        return f"str_starts(as.character({columns[0]}), fixed({_quote(str(item.value))}))"
    symbol = {"eq": "==", "ge": ">=", "le": "<="}[item.op]
    value = item.value if isinstance(item.value, int | float) else _quote(str(item.value))
    return f"{columns[0]} {symbol} {value}"


def _r_json(value: Any) -> str:
    """An R literal for a JSON body (lists and named lists)."""
    if isinstance(value, dict):
        return "list(" + ", ".join(f"`{k}` = {_r_json(v)}" for k, v in value.items()) + ")"
    if isinstance(value, list):
        return "list(" + ", ".join(_r_json(v) for v in value) + ")"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if value is None:
        return "NULL"
    if isinstance(value, int | float):
        return str(value)
    return _quote(str(value))


def _needs_request(spec: Spec) -> bool:
    return bool(spec.post_json is not None or spec.post_form or spec.headers)


def _r_download(spec: Spec, path: str) -> str:
    """download.file for a plain GET; httr2 when the request needs a body or headers."""
    if not _needs_request(spec):
        return f'download.file({_quote(spec.url)}, "{path}", mode = "wb")\n'
    request = f"request({_quote(spec.url)})"
    for name, value in spec.headers.items():
        request += f" |>\n  req_headers(`{name}` = {_quote(value)})"
    if spec.post_json is not None:
        request += f" |>\n  req_body_json({_r_json(spec.post_json)}, auto_unbox = TRUE)"
    if spec.post_form:
        request += f" |>\n  req_body_form(!!!{_r_json(spec.post_form)})"
    return f'{request} |>\n  req_perform(path = "{path}")\n'


def _r_read(spec: Spec) -> tuple[list[str], str]:
    path = f"data/raw/{spec.file_name}"
    na = (
        ', na = c("", "NA", ' + ", ".join(_quote(v) for v in spec.na_values) + ")"
        if spec.na_values
        else ""
    )
    read_args = f"delim = {_quote(spec.delimiter)}{na}, show_col_types = FALSE"
    download = _r_download(spec, path)
    fetch_packages = ["httr2"] if _needs_request(spec) else []
    if spec.kind == "csv":
        read = f'data <- read_delim("{path}", {read_args})\n'
        return ["readr", *fetch_packages], f"{download}\n{read}"
    if spec.kind == "file":
        return fetch_packages, download
    if spec.kind in ("zip", "zip_csv"):
        folder = f"data/raw/{spec.file_name.removesuffix('.zip')}"
        # zip::unzip, namespaced because base R's utils::unzip shares the name,
        # reads the non-UTF-8 member names in StatCan PUMF ZIPs that base R
        # rejects ("invalid multibyte string", 2026-09-25).
        code = (
            f"{download}"
            f'zip::unzip("{path}", exdir = "{folder}")\n'
            f'file.remove("{path}")\n\n'
            f'data_files <- list.files("{folder}", full.names = TRUE, recursive = TRUE)\n'
        )
        if spec.kind == "zip":
            return ["zip", *fetch_packages], code
        if spec.member_pattern:
            pick = (
                "data_files <- data_files[\n"
                f"  str_detect(basename(data_files), fixed({_quote(spec.member_pattern)}))\n"
                "]\n"
            )
        else:
            pick = (
                "\n# The ZIP may also hold a metadata file; read the data file.\n\n"
                'data_files <- data_files[str_detect(data_files, "[.](csv|txt)$")]\n'
                'data_files <- data_files[!str_detect(str_to_lower(data_files), "metadata")]\n'
            )
        read = f"data <- read_delim(data_files[1], {read_args})\n"
        return ["readr", "stringr", "zip", *fetch_packages], f"{code}{pick}{read}"
    if spec.kind == "xlsx":
        sheet = f", sheet = {_quote(spec.sheet)}" if spec.sheet else ""
        start = f", start_row = {spec.skip_rows + 1}" if spec.skip_rows else ""
        read = f'data <- read_xlsx("{path}"{sheet}{start})\n'
        return ["openxlsx2", *fetch_packages], f"{download}\n{read}"
    if spec.kind == "json":
        request = f"response <- request({_quote(spec.url)})"
        for name, value in spec.headers.items():
            request += f" |>\n  req_headers(`{name}` = {_quote(value)})"
        if spec.post_json is not None:
            request += f" |>\n  req_body_json({_r_json(spec.post_json)}, auto_unbox = TRUE)"
        if spec.post_form:
            request += f" |>\n  req_body_form(!!!{_r_json(spec.post_form)})"
        request += " |>\n  req_perform()\n"
        save = f'\nwriteLines(resp_body_string(response), "{path}")\n\n'
        packages = ["httr2", "jsonlite", "tibble"]
        if spec.single_object:
            body = (
                "# One record: nested fields become dotted column names in one row.\n\n"
                f'payload <- fromJSON("{path}")\n'
                "data <- as_tibble(as.list(unlist(payload)))\n"
            )
        elif spec.columnar:
            body = f'payload <- fromJSON("{path}")\ndata <- as_tibble(payload)\n'
        elif spec.records_dict:
            packages.append("dplyr")
            walk = "".join(f"[[{_quote(k)}]]" for k in spec.records_path)
            body = (
                "# Records keyed by name: one row each, the name in `key`.\n\n"
                f'payload <- fromJSON("{path}", flatten = TRUE)\n'
                f'data <- bind_rows(payload{walk}, .id = "key")\n'
            )
        elif spec.name_value:
            packages += ["dplyr", "purrr"]
            walk = "".join(f"[[{_quote(k)}]]" for k in spec.records_path)
            body = (
                "# Each row is a list of {Name, Value: {Literal}} cells.\n\n"
                f'payload <- fromJSON("{path}", simplifyVector = FALSE)\n'
                f"data <- payload{walk} |>\n"
                "  map(\\(row) set_names(\n"
                "    map(row, \\(cell) cell$Value$Literal %||% NA),\n"
                '    map_chr(row, "Name")\n'
                "  )) |>\n"
                "  bind_rows()\n"
            )
        elif spec.each_item:
            packages.append("dplyr")
            walk = "".join(f"[[{_quote(k)}]]" for k in spec.records_path)
            body = f'payload <- fromJSON("{path}")\ndata <- bind_rows(payload{walk})\n'
        elif spec.record_field:
            keys = [*spec.records_path, spec.record_field]
            walk = "".join(f"[[{_quote(k)}]]" for k in keys)
            body = f'payload <- fromJSON("{path}")\ndata <- as_tibble(payload{walk})\n'
        else:
            walk = "".join(f"[[{_quote(k)}]]" for k in spec.records_path)
            body = (
                f'payload <- fromJSON("{path}", flatten = TRUE)\ndata <- as_tibble(payload{walk})\n'
            )
        return packages, request + save + body
    if spec.kind == "html_table":
        return (
            ["rvest", "xml2"],
            (
                f"page <- read_html({_quote(spec.url)})\n"
                f'write_html(page, "{path}")\n\n'
                'tables <- page |>\n  html_elements("table") |>\n  html_table()\n'
                f"data <- tables[[{spec.html_table_index + 1}]]\n"
            ),
        )
    if spec.kind == "feed":
        return (
            ["dplyr", "tibble", "xml2", *fetch_packages],
            (
                f"{download}\n"
                f'feed <- read_xml("{path}")\n'
                "xml_ns_strip(feed)\n"
                'entries <- xml_find_all(feed, "//item | //entry")\n'
                'links <- xml_find_first(entries, "./link")\n\n'
                "# RSS puts the link in the text, Atom in an href attribute.\n\n"
                "data <- tibble(\n"
                '  title = xml_text(xml_find_first(entries, "./title")),\n'
                '  link = coalesce(na_if(xml_text(links), ""), xml_attr(links, "href")),\n'
                '  date = xml_text(xml_find_first(entries, "./pubDate | ./updated | ./published"))\n'
                ")\n"
            ),
        )
    return [], download


def render_r(spec: Spec, tool: str) -> tuple[str, list[str]]:
    native = spec.native.get("r")
    packages, read = (list(native.imports), native.body) if native else _r_read(spec)
    prepare: list[str] = []
    if spec.header_prefix:
        packages.append("stringr")
        prepare.append(
            f"# Drop the {spec.header_prefix!r} that marks the header row.\n\n"
            "data <- data |>\n"
            f'  rename_with(\\(name) str_remove(name, "^{spec.header_prefix}"))\n'
        )
    if spec.filters:
        packages += ["dplyr", "stringr"]
        conditions = ",\n    ".join(_r_filter(f) for f in spec.filters)
        prepare.append(
            "# Keep the rows the MapleStats tool kept.\n\n"
            f"data <- data |>\n  filter(\n    {conditions}\n  )\n"
        )
    if spec.sort_by:
        packages.append("dplyr")
        order = f"desc(`{spec.sort_by}`)" if spec.sort_descending else f"`{spec.sort_by}`"
        prepare.append(f"data <- data |>\n  arrange({order})\n")
    if spec.kind not in ("zip", "file"):
        packages.append("janitor")
        prepare.append("data <- data |>\n  clean_names()\n")
        specific = cleaning.specific("r", spec.source)
        if specific:
            packages += specific.imports
            prepare.append(specific.body)
        packages += cleaning.GENERIC["r"].imports
        prepare.append(cleaning.GENERIC["r"].body)
    # zip is called as zip::unzip, not attached, so it does not mask utils::unzip.
    libraries = "".join(f"library({p})\n" for p in sorted(set(packages)) if p != "zip")
    setup = _join(
        "# 0. Setup ----\n",
        libraries,
        'dir.create("data/raw", recursive = TRUE, showWarnings = FALSE)\n',
    )
    sections = [_header("#", spec, tool), setup, "# 1. Read inputs ----\n", read]
    if spec.kind not in ("zip", "file"):
        check = f"stopifnot({_quote(spec.url + ' returned no rows')} = nrow(data) > 0)\n"
        sections += ["# 2. Check inputs ----\n", check, "# 3. Prepare data ----\n", *prepare]
    return _join(*sections), sorted(set(packages))


# Python -------------------------------------------------------------------


def _py_filter(item: Filter) -> str:
    if item.op == "contains":
        return (
            f"pl.col({item.columns[0]!r}).cast(pl.Utf8).str.to_lowercase()"
            f".str.contains({str(item.value).lower()!r}, literal=True)"
        )
    if item.op == "terms":
        parts = ", ".join(f'pl.col({c!r}).cast(pl.Utf8).fill_null("")' for c in item.columns)
        haystack = f'pl.concat_str([{parts}], separator=" ").str.to_lowercase()'
        return ",\n    ".join(
            f"{haystack}.str.contains({term!r}, literal=True)"
            for term in str(item.value).lower().split()
        )
    if item.op == "is":
        return (
            f"pl.col({item.columns[0]!r}).cast(pl.Utf8).str.strip_chars().str.to_lowercase()"
            f" == {str(item.value).strip().lower()!r}"
        )
    if item.op == "starts":
        return f"pl.col({item.columns[0]!r}).cast(pl.Utf8).str.starts_with({str(item.value)!r})"
    symbol = {"eq": "==", "ge": ">=", "le": "<="}[item.op]
    column = f"pl.col({item.columns[0]!r})"
    if isinstance(item.value, int | float):
        column += ".cast(pl.Float64, strict=False)"
    else:
        column += ".cast(pl.Utf8)"
    return f"{column} {symbol} {item.value!r}"


def _py_fetch(spec: Spec) -> str:
    # http2=True is required: StatCan drops TLS connections from clients that
    # offer only HTTP/1.1 (see shared/http.py), so a plain httpx.get fails there.
    headers = f", headers={spec.headers!r}" if spec.headers else ""
    if spec.post_json is not None:
        call = f"client.post({spec.url!r}, json={spec.post_json!r}{headers})"
    elif spec.post_form:
        call = f"client.post({spec.url!r}, data={spec.post_form!r}{headers})"
    else:
        call = f"client.get({spec.url!r}{headers})"
    # CanadaBuys answers 403 to httpx's default User-Agent (checked 2026-09-25).
    return (
        "with httpx.Client(\n"
        "    http2=True,\n"
        "    follow_redirects=True,\n"
        "    timeout=300,\n"
        '    headers={"User-Agent": "Mozilla/5.0 (compatible; research script)"},\n'
        ") as client:\n"
        f"    response = {call}\n"
        "response.raise_for_status()\n"
        "raw_path.write_bytes(response.content)\n"
    )


def py_read(spec: Spec) -> tuple[list[str], str]:
    imports = ["from pathlib import Path", "import httpx", "import polars as pl"]
    null = f", null_values={spec.na_values!r}" if spec.na_values else ""
    read_args = f"separator={spec.delimiter!r}, infer_schema_length=100_000{null}"
    fetch = _py_fetch(spec)
    if spec.kind == "csv":
        return imports, f"{fetch}\ndata = pl.read_csv(raw_path, {read_args})\n"
    if spec.kind in ("zip", "zip_csv"):
        imports.append("import zipfile")
        if spec.kind == "zip":
            return imports, (
                f"{fetch}\n"
                "with zipfile.ZipFile(raw_path) as archive:\n"
                "    archive.extractall(RAW_DIR / raw_path.stem)\n"
            )
        pick = (
            f"if {spec.member_pattern!r} in n"
            if spec.member_pattern
            else 'if n.lower().endswith((".csv", ".txt")) and "metadata" not in n.lower()'
        )
        return imports, (
            f"{fetch}\n"
            "# The ZIP may also hold a metadata file; read the data file.\n\n"
            "with zipfile.ZipFile(raw_path) as archive:\n"
            f"    data_name = next(n for n in archive.namelist() {pick})\n"
            "    archive.extract(data_name, RAW_DIR)\n\n"
            f"data = pl.read_csv(RAW_DIR / data_name, {read_args})\n"
        )
    if spec.kind == "xlsx":
        sheet = f", sheet_name={spec.sheet!r}" if spec.sheet else ""
        header = f', read_options={{"header_row": {spec.skip_rows}}}' if spec.skip_rows else ""
        return imports, f"{fetch}\ndata = pl.read_excel(raw_path{sheet}{header})\n"
    if spec.kind == "json":
        imports.append("import json")
        payload = 'payload = json.loads(raw_path.read_text(encoding="utf-8"))\n'
        walk = "".join(f"[{k!r}]" for k in spec.records_path)
        if spec.single_object:
            records = (
                "# One record: nested fields become dotted column names in one row.\n\n"
                "records = [payload]\n"
            )
        elif spec.records_dict:
            records = (
                "# Records keyed by name: one row each, the name in `key`.\n\n"
                f'records = [{{"key": key, **value}} for key, value in payload{walk}.items()]\n'
            )
        elif spec.columnar:
            return imports, f"{fetch}\n{payload}data = pl.DataFrame(payload, strict=False)\n"
        elif spec.name_value:
            records = (
                "# Each row is a list of {Name, Value: {Literal}} cells.\n\n"
                "records = [\n"
                '    {cell["Name"]: (cell.get("Value") or {}).get("Literal") for cell in row}\n'
                f"    for row in payload{walk}\n"
                "]\n"
            )
        elif spec.each_item:
            records = f"records = [row for item in payload for row in item{walk}]\n"
        elif spec.record_field:
            records = f"records = [row[{spec.record_field!r}] for row in payload{walk}]\n"
        else:
            records = f"records = payload{walk}\n"
        # Some sources mix types within a field (census profile values).
        normalize = "data = pl.json_normalize(records, strict=False)\n"
        return imports, f"{fetch}\n{payload}{records}{normalize}"
    if spec.kind == "html_table":
        imports += ["import io", "import pandas as pd"]
        return imports, (
            f"{fetch}\n"
            "# polars has no HTML reader; pandas parses the page's tables once.\n\n"
            "tables = pd.read_html(io.StringIO(response.text))\n"
            f"data = pl.from_pandas(tables[{spec.html_table_index}])\n"
        )
    if spec.kind == "feed":
        imports.append("import xml.etree.ElementTree as ET")
        return imports, (
            f"{fetch}\n"
            "# RSS items and Atom entries become one row each; Atom puts the link in href.\n\n"
            "root = ET.fromstring(response.content)\n"
            "rows = []\n"
            "for entry in root.iter():\n"
            '    if entry.tag.rsplit("}", 1)[-1] not in ("item", "entry"):\n'
            "        continue\n"
            '    fields = {child.tag.rsplit("}", 1)[-1]: child for child in entry}\n'
            '    link = fields.get("link")\n'
            '    dates = [fields[k].text for k in ("pubDate", "updated", "published") if k in fields]\n'
            "    rows.append(\n"
            "        {\n"
            '            "title": fields["title"].text if "title" in fields else None,\n'
            '            "link": (link.text or link.get("href")) if link is not None else None,\n'
            '            "date": dates[0] if dates else None,\n'
            "        }\n"
            "    )\n"
            "data = pl.DataFrame(rows)\n"
        )
    return imports, fetch


def py_prepare(spec: Spec) -> list[str]:
    """Header fix, filters and sort, shared by the Python and Stata scripts."""
    blocks: list[str] = []
    if spec.header_prefix:
        blocks.append(
            f"# Drop the {spec.header_prefix!r} that marks the header row.\n\n"
            f"data = data.rename(lambda name: name.removeprefix({spec.header_prefix!r}))\n"
        )
    if spec.filters:
        conditions = ",\n    ".join(_py_filter(f) for f in spec.filters)
        blocks.append(
            "# Keep the rows the MapleStats tool kept.\n\n"
            f"data = data.filter(\n    {conditions},\n)\n"
        )
    if spec.sort_by:
        blocks.append(
            f"data = data.sort({spec.sort_by!r}, descending={spec.sort_descending}, nulls_last=True)\n"
        )
    return blocks


def _py_imports(lines: list[str]) -> str:
    unique = sorted(set(lines), key=lambda line: (line.startswith("from"), line))
    stdlib = [line for line in unique if line.split()[1].split(".")[0] in _STDLIB]
    third = [line for line in unique if line not in stdlib]
    return _join("\n".join(stdlib), "\n".join(third))


def py_packages(imports: list[str], spec: Spec) -> list[str]:
    names = {"httpx": "httpx[http2]", "polars": "polars", "pandas": "pandas", "certifi": "certifi"}
    packages = {names[line.split()[1]] for line in imports if line.split()[1] in names}
    if "pandas" in packages:
        packages |= {"lxml", "pyarrow"}
    if spec.kind == "xlsx":
        packages.add("fastexcel")  # polars' Excel reader
    return sorted(packages)


def _py_loaded(spec: Spec) -> tuple[list[str], str]:
    native = spec.native.get("python")
    return (list(native.imports), native.body) if native else py_read(spec)


def render_python(spec: Spec, tool: str) -> tuple[str, list[str]]:
    imports, read = _py_loaded(spec)
    packages = py_packages(imports, spec)
    prepare = py_prepare(spec)
    if spec.kind not in ("zip", "file"):
        specific = cleaning.specific("python", spec.source)
        if specific:
            imports += specific.imports
            prepare.append(specific.body)
        imports += cleaning.GENERIC["python"].imports
        prepare.append(cleaning.GENERIC["python"].body)
    setup = _join(
        "# %% 0. Setup\n",
        _py_imports(imports),
        'RAW_DIR = Path("data/raw")\n'
        "RAW_DIR.mkdir(parents=True, exist_ok=True)\n"
        f'raw_path = RAW_DIR / "{spec.file_name}"\n',
    )
    sections = [_header("#", spec, tool), setup, "# %% 1. Read inputs\n", read]
    if spec.kind not in ("zip", "file"):
        check = f'assert data.height > 0, "{spec.url} returned no rows"\n'
        sections += ["# %% 2. Check inputs\n", check, "# %% 3. Prepare data\n", *prepare]
    return _join(*sections), packages


# Stata ----------------------------------------------------------------------


def stata_statements(code: str) -> str:
    """Python rewritten for a Stata `python:` block.

    Stata 18 in batch mode compiles the block one physical line at a time
    (checked 2026-09-25): a call split over lines, and even a two-line `for`
    or `with` block, is a SyntaxError. So each statement becomes one line;
    a block whose body is plain statements becomes `header: a; b`; a block
    with nested blocks runs through exec() on one line.
    """
    lines = code.splitlines(keepends=True)
    comments: dict[int, int] = {}
    statements: list[str] = []
    start: int | None = None
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type == tokenize.COMMENT:
            comments[token.start[0]] = token.start[1]
            continue
        if token.type in (tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
            continue
        if start is None and token.type not in (tokenize.NEWLINE, tokenize.ENDMARKER):
            start = token.start[0]
        if token.type == tokenize.NEWLINE and start is not None:
            parts = [
                lines[row - 1][: comments.get(row, len(lines[row - 1]))]
                for row in range(start, token.end[0] + 1)
            ]
            indent = parts[0][: len(parts[0]) - len(parts[0].lstrip())]
            joined = " ".join(part.strip() for part in parts)
            joined = re.sub(r"([(\[{]) ", r"\1", joined)
            joined = re.sub(r",? ([)\]}])", r"\1", joined)
            statements.append(indent + joined)
            start = None
    chunks: list[list[str]] = []
    for statement in statements:
        if statement.startswith((" ", "\t")) and chunks:
            chunks[-1].append(statement)
        else:
            chunks.append([statement])
    out: list[str] = []
    for chunk in chunks:
        body = [line.strip() for line in chunk[1:]]
        depths = {len(line) - len(line.lstrip()) for line in chunk[1:]}
        if len(chunk) == 1:
            out.append(chunk[0])
        elif len(depths) == 1 and not any(line.endswith(":") for line in body):
            out.append(f"{chunk[0]} {'; '.join(body)}")
        else:
            out.append(f"exec({chr(10).join(chunk) + chr(10)!r})")
    return "\n".join(out) + "\n"


def _stata_python_block(spec: Spec, csv_name: str) -> tuple[str, list[str]]:
    imports, read = _py_loaded(spec)
    packages = py_packages(imports, spec)
    # CSV has no nested values: lists and records go to Stata as JSON text.
    flatten = (
        "nested = [name for name, dtype in data.schema.items() if dtype.is_nested()]\n"
        "data = data.with_columns(\n"
        "    pl.col(name).map_elements(\n"
        "        lambda value: json.dumps(\n"
        "            value.to_list() if isinstance(value, pl.Series) else value, default=str\n"
        "        ),\n"
        "        return_dtype=pl.Utf8,\n"
        "    )\n"
        "    for name in nested\n"
        ")\n"
    )
    table = (
        []
        if spec.kind in ("zip", "file")
        else [
            *py_prepare(spec),
            flatten,
            f'data.write_csv(RAW_DIR / "{csv_name}")\n',
        ]
    )
    body = _join(
        _py_imports([*imports, "import json"]),
        f'RAW_DIR = Path("data/raw")\nRAW_DIR.mkdir(parents=True, exist_ok=True)\n'
        f'raw_path = RAW_DIR / "{spec.file_name}"\n',
        read,
        *table,
    )
    return f"python:\n{stata_statements(body)}end\n", packages


def render_stata(spec: Spec, tool: str) -> tuple[str, list[str]]:
    path = f"data/raw/{spec.file_name}"
    delimiters = "" if spec.delimiter == "," else f' delimiters("{spec.delimiter}")'
    simple = not (
        spec.filters
        or "python" in spec.native
        or spec.na_values
        or spec.sort_by
        or _needs_request(spec)
        or "statcan.gc.ca" in spec.url
    )
    packages: list[str] = []
    if spec.kind == "csv" and simple:
        read = (
            f'copy "{spec.url}" "{path}", replace\n'
            f'import delimited "{path}", clear varnames(1) encoding("utf-8"){delimiters}\n'
        )
    elif spec.kind == "zip_csv" and simple:
        folder = f"data/raw/{spec.file_name.removesuffix('.zip')}"
        read = (
            f'local folder "{folder}"\n'
            f'copy "{spec.url}" "{path}", replace\n'
            'capture mkdir "`folder\'"\n\n'
            "* unzipfile extracts into the working directory; tar (Windows 10+, macOS,\n"
            "* Linux) extracts into the folder without a cd.\n\n"
            f'shell tar -xf "{path}" -C "`folder\'"\n\n'
            "* The ZIP may also hold a metadata CSV; read the data file.\n\n"
            'local csv_files : dir "`folder\'" files "*.csv"\n'
            "foreach file of local csv_files {\n"
            '    if strpos(lower("`file\'"), "metadata") == 0 {\n'
            "        local data_csv `file'\n"
            "    }\n"
            "}\n"
            "import delimited \"`folder'/`data_csv'\", clear varnames(1) "
            f'encoding("utf-8"){delimiters}\n'
        )
    elif spec.kind == "zip" and simple:
        folder = f"data/raw/{spec.file_name.removesuffix('.zip')}"
        read = (
            f'copy "{spec.url}" "{path}", replace\n'
            f'capture mkdir "{folder}"\n'
            f'shell tar -xf "{path}" -C "{folder}"\n'
        )
    elif spec.kind == "file" and simple:
        read = f'copy "{spec.url}" "{path}", replace\n'
    elif spec.kind == "xlsx" and simple:
        sheet = f' sheet("{spec.sheet}")' if spec.sheet else ""
        cells = f" cellrange(A{spec.skip_rows + 1})" if spec.skip_rows else ""
        read = (
            f'copy "{spec.url}" "{path}", replace\n'
            f'import excel "{path}",{sheet}{cells} firstrow clear\n'
        )
    else:
        # Short: Stata cannot open paths past Windows' 260-character limit.
        csv_name = f"{spec.file_name.rsplit('.', 1)[0][:24]}_prepared.csv"
        block, python_packages = _stata_python_block(spec, csv_name)
        read = (
            "* Stata reads no JSON or HTML and truncates long column names, so its\n"
            "* built-in Python (Stata 16+) fetches, filters and writes a CSV. Point\n"
            "* Stata at a Python with these packages first: python set exec <path>.\n\n"
            + block
            + (
                ""
                if spec.kind in ("zip", "file")
                else f'\nimport delimited "data/raw/{csv_name}", clear varnames(1) encoding("utf-8")\n'
            )
        )
        packages.append("python: " + ", ".join(python_packages))
    prepare: list[str] = []
    if spec.kind not in ("zip", "file"):
        specific = cleaning.specific("stata", spec.source)
        if specific:
            prepare.append(specific.body)
        prepare.append(cleaning.GENERIC["stata"].body)
    setup = _join(
        "version 18\nclear all\nset more off\n",
        "* 0. Setup\n",
        'capture mkdir "logs"\n'
        "capture log close\n"
        f'log using "logs/{tool[:32]}.log", replace\n'
        'capture mkdir "data"\n'
        'capture mkdir "data/raw"\n',
    )
    sections = [_header("*", spec, tool), setup, "* 1. Read inputs\n", read]
    if spec.kind not in ("zip", "file"):
        sections += ["* 2. Check inputs\n", "assert _N > 0\n", "* 3. Prepare data\n", *prepare]
    sections.append("log close\n")
    return _join(*sections), packages


# Julia -----------------------------------------------------------------------


def _jl_filter(item: Filter) -> str:
    def cell(column: str) -> str:
        return f'coalesce(string(row[{json.dumps(column)}]), "")'

    if item.op == "contains":
        needle = json.dumps(str(item.value).lower())
        return f"occursin({needle}, lowercase({cell(item.columns[0])}))"
    if item.op == "terms":
        haystack = f'lowercase(join([{", ".join(cell(c) for c in item.columns)}], " "))'
        return " &&\n        ".join(
            f"occursin({json.dumps(term)}, {haystack})" for term in str(item.value).lower().split()
        )
    if item.op == "is":
        value = json.dumps(str(item.value).strip().lower())
        return f"lowercase(strip({cell(item.columns[0])})) == {value}"
    if item.op == "starts":
        return f"startswith({cell(item.columns[0])}, {json.dumps(str(item.value))})"
    symbol = {"eq": "==", "ge": ">=", "le": "<="}[item.op]
    column = f"row[{json.dumps(item.columns[0])}]"
    value = item.value if isinstance(item.value, int | float) else json.dumps(str(item.value))
    if not isinstance(item.value, int | float):
        column = f"string({column})"
    return f"!ismissing(row[{json.dumps(item.columns[0])}]) && {column} {symbol} {value}"


def _jl_request(spec: Spec, path: str) -> str:
    """Downloads.download for a plain GET; Downloads.request with a body or headers."""
    if not _needs_request(spec):
        return f'Downloads.download({json.dumps(spec.url)}, "{path}")\n'
    headers = dict(spec.headers)
    body = ""
    if spec.post_json is not None:
        headers["Content-Type"] = "application/json"
        body = f', method = "POST", input = IOBuffer({json.dumps(json.dumps(spec.post_json))})'
    elif spec.post_form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = f', method = "POST", input = IOBuffer({json.dumps(urlencode(spec.post_form))})'
    pairs = ", ".join(f"{json.dumps(k)} => {json.dumps(v)}" for k, v in headers.items())
    return (
        f"Downloads.request(\n    {json.dumps(spec.url)};\n    headers = [{pairs}]{body},\n"
        f'    output = "{path}",\n)\n'
    )


def _jl_read(spec: Spec) -> tuple[list[str], str] | None:
    path = f"data/raw/{spec.file_name}"
    download = _jl_request(spec, path)
    missing = f", missingstring = {json.dumps(['', *spec.na_values])}" if spec.na_values else ""
    delim = f", delim = {json.dumps(spec.delimiter)}" if spec.delimiter != "," else ""
    if spec.kind == "csv":
        read = f'data = read_csv("{path}"{delim}{missing})\n'
        return ["Downloads", "TidierFiles"], download + read
    if spec.kind == "zip_csv":
        test = (
            f"occursin({json.dumps(spec.member_pattern)}, f.name)"
            if spec.member_pattern
            else (
                '(endswith(lowercase(f.name), ".csv") || endswith(lowercase(f.name), ".txt")) &&\n'
                '    !occursin("metadata", lowercase(f.name))'
            )
        )
        return ["Downloads", "TidierFiles", "ZipFile"], (
            f"{download}"
            f'archive = ZipFile.Reader("{path}")\n\n'
            "# The ZIP may also hold a metadata file; read the data file.\n\n"
            f"data_file = first(f for f in archive.files if {test})\n"
            'write("data/raw/table.csv", read(data_file))\n'
            "close(archive)\n"
            f'data = read_csv("data/raw/table.csv"{delim}{missing})\n'
        )
    if spec.kind in ("zip", "file"):
        return ["Downloads"], download
    if spec.kind == "xlsx":
        sheet = f", sheet = {json.dumps(spec.sheet)}" if spec.sheet else ""
        skip = f", skip = {spec.skip_rows}" if spec.skip_rows else ""
        return ["Downloads", "TidierFiles"], f'{download}data = read_xlsx("{path}"{sheet}{skip})\n'
    if spec.kind == "json":
        fetch = download
        walk = "".join(f"[{json.dumps(k)}]" for k in spec.records_path)
        payload = f'payload = JSON3.read(read("{path}", String))\n'
        if spec.columnar:
            return ["DataFrames", "Downloads", "JSON3"], (
                fetch
                + payload
                + "data = DataFrame(Dict(String(k) => collect(v) for (k, v) in payload))\n"
            )
        if spec.name_value:
            records = (
                "records = [\n"
                '    Dict(c["Name"] => get(c["Value"], "Literal", missing) for c in row)\n'
                f"    for row in payload{walk}\n"
                "]\n"
            )
        elif spec.records_dict:
            records = f'records = [merge(Dict("key" => String(k)), Dict(v)) for (k, v) in payload{walk}]\n'
        elif spec.single_object:
            records = (
                "records = [\n"
                "    Dict(k => v for (k, v) in payload if !(v isa JSON3.Object || v isa JSON3.Array)),\n"
                "]\n"
            )
        elif spec.each_item:
            records = f"records = reduce(vcat, [collect(item{walk}) for item in payload])\n"
        elif spec.record_field:
            records = f"records = [row[{json.dumps(spec.record_field)}] for row in payload{walk}]\n"
        else:
            records = f"records = payload{walk}\n"
        return ["DataFrames", "Downloads", "JSON3", "Tables"], (
            fetch + payload + records + "data = DataFrame(Tables.dictrowtable(records))\n"
        )
    return None  # HTML tables and feeds: no maintained Julia reader to rely on


def render_julia(spec: Spec, tool: str) -> tuple[str, list[str]] | None:
    native = spec.native.get("julia")
    loaded = (list(native.imports), native.body) if native else _jl_read(spec)
    if loaded is None:
        return None
    packages, read = loaded
    prepare: list[str] = []
    if spec.header_prefix:
        prepare.append(
            f'rename!(data, names(data) .=> replace.(names(data), r"^{spec.header_prefix}" => ""))\n'
        )
    if spec.filters:
        packages.append("DataFrames")
        conditions = " &&\n        ".join(f"({_jl_filter(f)})" for f in spec.filters)
        prepare.append(
            "# Keep the rows the MapleStats tool kept.\n\n"
            f"data = filter(row -> begin\n        {conditions}\n    end, data)\n"
        )
    if spec.sort_by:
        rev = str(spec.sort_descending).lower()
        prepare.append(f"sort!(data, {json.dumps(spec.sort_by)}; rev = {rev})\n")
    if spec.kind not in ("zip", "file"):
        specific = cleaning.specific("julia", spec.source)
        if specific:
            prepare.append(specific.body)
        packages += cleaning.GENERIC["julia"].imports
        prepare.append(cleaning.GENERIC["julia"].body)
    usings = "".join(f"using {p}\n" for p in sorted(set(packages)))
    setup = _join("# 0. Setup\n", usings, 'mkpath("data/raw")\n')
    sections = [_header("#", spec, tool), setup, "# 1. Read inputs\n", read]
    if spec.kind not in ("zip", "file"):
        check = f'@assert nrow(data) > 0 "{spec.url} returned no rows"\n'
        sections += ["# 2. Check inputs\n", check, "# 3. Prepare data\n", *prepare]
    return _join(*sections), sorted(set(packages))


RENDERERS = {"r": render_r, "python": render_python, "stata": render_stata, "julia": render_julia}

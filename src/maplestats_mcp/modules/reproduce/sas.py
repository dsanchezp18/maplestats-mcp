"""Render a Spec as a SAS program (Base SAS 9.4M5 or later).

SAS reads delimited text, ZIP archives and Excel workbooks well, and has no
reader for HTML tables, feeds or arbitrary JSON, so those sources, and any
spec whose own steps exist only in other languages, get no SAS program
(`render_sas` returns None and the result's notes say why).

The layout follows the other scripts: a header, then 0. Setup, 1. Read
inputs, 2. Check inputs and 3. Prepare data. The prepared table is
`work.maple_data`. Two things differ from the other languages:

- SAS names are 32 characters, so the program renames every column to
  snake_case (lower case, runs of other characters as one underscore, at
  most 32 characters, duplicates numbered) while it reads, and filters and
  the sort use those names. `sas_name` writes the same rule in Python.
- Delimited files are read with every column as text, as in the other
  languages, so codes keep their form ("000000001", coordinate "2.10"); the
  standard cleaning then converts the columns that are really numbers.

This program was written from SAS's documentation and has not been run in a
SAS session: the tests check what it says, not that SAS accepts it.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode

from maplestats_mcp.modules.reproduce import cleaning
from maplestats_mcp.modules.reproduce.render import (
    _LINE_BREAKS,
    _join,
    _safe_spec,
    comment_text,
)
from maplestats_mcp.modules.reproduce.spec import Filter, Spec, term_groups

DATA = "work.maple_data"
# What may not sit inside a double-quoted SAS string: "&name" and "%name" start
# macro resolution there, and a quote ends the string.
_UNSAFE_DOUBLE_QUOTED = re.compile(r"[&%\"']")


def sas_name(column: str) -> str:
    """The column's name as the program's renaming step writes it."""
    name = re.sub(r"[^a-z0-9]+", "_", column.lower()).strip("_") or "x"
    if name[0].isdigit():
        name = "x" + name
    return name[:32]


def _sq(value: Any) -> str:
    """A single-quoted SAS literal: macro triggers stay inert inside single quotes."""
    return "'" + _LINE_BREAKS.sub("", str(value)).replace("'", "''") + "'"


def _delimiter(delimiter: str) -> str:
    return "'09'x" if delimiter == "\t" else _sq(delimiter)


def _comment(text: str) -> str:
    return comment_text(text).replace("*/", "* /")


def _header(spec: Spec, tool: str) -> str:
    rule = "/* " + "=" * 60
    output = {"zip": "the archive's member list", "file": "the downloaded file"}.get(
        spec.kind, f"the prepared table as {DATA}"
    )
    lines = [
        _comment(spec.title or "Reproduce " + tool),
        f"Purpose: Fetch the data behind MapleStats MCP's {_comment(tool)}",
        f"         ({_comment(spec.method)})",
        f"Inputs:  {_comment(spec.url)}",
        *(_comment(line) for line in spec.details),
        f"Outputs: data/raw/{_comment(spec.file_name)}; {output}",
    ]
    return rule + "\n" + "".join(f"   {line}\n" for line in lines) + "   " + "=" * 60 + " */\n"


# Downloads --------------------------------------------------------------------


def _download(spec: Spec, path: str) -> str:
    """PROC HTTP, with the body and headers when the request needs them."""
    method = '"post"' if _needs_post(spec) else '"get"'
    options = f"url={_sq(spec.url)} method={method}"
    headers = dict(spec.headers)
    if spec.post_json is not None:
        headers["Content-Type"] = "application/json"
        options += f" in={_sq(json.dumps(spec.post_json))}"
    elif spec.post_form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        options += f" in={_sq(urlencode(spec.post_form))}"
    pairs = " ".join(f"{_sq(k)}={_sq(v)}" for k, v in headers.items())
    header_statement = f"    headers {pairs};\n" if pairs else ""
    return (
        f'filename raw_dl "{path}";\n'
        f"proc http {options} out=raw_dl;\n"
        f"{header_statement}"
        "run;\n"
        "filename raw_dl clear;\n\n"
        "data _null_;\n"
        "    if &sys_prochttp_status_code. ne 200 then do;\n"
        f"        put 'ERROR: the download from ' {_sq(spec.url)} 'answered HTTP '\n"
        '            "&sys_prochttp_status_code.";\n'
        "        abort cancel;\n"
        "    end;\n"
        "run;\n"
    )


def _needs_post(spec: Spec) -> bool:
    return spec.post_json is not None or bool(spec.post_form)


# Names -------------------------------------------------------------------------

# Builds &renames from work._cols (old: the variable's name now, header: what the
# source calls the column) and applies it to the data in one rename=, which
# allows swaps. Names that collide are numbered _2, _3 as janitor numbers them.
_RENAME_STEP = """\
data _null_;
    set work._cols end=last;
    length new candidate $32 tail $12 renames $32767;
    retain renames '';
    if _n_ = 1 then do;
        declare hash used();
        used.defineKey('candidate');
        used.defineDone();
    end;
{prefix}    new = prxchange('s/[^a-z0-9]+/_/', -1, klowcase(strip(header)));
    new = prxchange('s/^_+|_+$//', -1, new);
    if missing(new) then new = 'x';
    if prxmatch('/^[0-9]/', new) then new = cats('x', new);
    candidate = new;
    suffix = 1;
    do while (used.check() = 0);
        suffix + 1;
        tail = cats('_', suffix);
        candidate = cats(substr(new, 1, 32 - length(tail)), tail);
    end;
    rc = used.add();
    if upcase(old) ne upcase(candidate) then
        renames = catx(' ', renames, cats("'", old, "'n=", candidate));
    if last then call symputx('renames', renames);
run;

%macro apply_renames;
    %if %length(&renames.) > 0 %then %do;
        data {data};
            set {data}(rename=(&renames.));
        run;
    %end;
%mend apply_renames;
%apply_renames;
"""


def _rename_step(spec: Spec) -> str:
    prefix = ""
    if spec.header_prefix:
        length = len(_LINE_BREAKS.sub("", spec.header_prefix))
        prefix = (
            f"    if substr(header, 1, {length}) = {_sq(spec.header_prefix)} then\n"
            f"        header = substr(header, {length + 1});\n"
        )
    return _RENAME_STEP.format(prefix=prefix, data=DATA)


# Reading -----------------------------------------------------------------------


def _read_text(spec: Spec, source: str, first_row: int) -> str:
    """Read a delimited file as text: the header names the columns, then every
    column is read into v1..vN and renamed."""
    delimiter = _delimiter(spec.delimiter)
    infile = f'infile {source} dsd delimiter={delimiter} truncover lrecl=1000000 encoding="utf-8"'
    missing = ""
    if spec.na_values:
        values = ", ".join(_sq(v) for v in spec.na_values)
        missing = (
            f"    array cells{{*}} v1-v&ncols.;\n"
            f"    do i = 1 to dim(cells);\n"
            f"        if cells{{i}} in ({values}) then cells{{i}} = '';\n"
            f"    end;\n"
            f"    drop i;\n"
        )
    blank_stop = (
        "    input @;\n    if lengthn(strip(_infile_)) = 0 then stop;\n    input v1-v&ncols.;\n"
        if spec.stop_at_blank
        else "    input v1-v&ncols.;\n"
    )
    notes = ""
    if spec.skip_rows or spec.stop_at_blank:
        parts = []
        if spec.skip_rows:
            parts.append(f"opens with {spec.skip_rows} title line(s) above its header")
        if spec.stop_at_blank:
            parts.append("ends with notes below a blank line")
        notes = f"/* The file {' and '.join(parts)}; read the table between. */\n\n"
    return (
        f"{notes}"
        "/* The header line gives the number of columns and their names. */\n\n"
        "data _null_;\n"
        f"    {infile} firstobs={first_row} obs={first_row};\n"
        "    input;\n"
        f"    call symputx('ncols', countw(_infile_, {delimiter}, 'mq'));\n"
        "run;\n\n"
        "data work._cols;\n"
        f"    {infile} firstobs={first_row} obs={first_row};\n"
        "    length old $32 header $1000;\n"
        "    do column = 1 to &ncols.;\n"
        "        input header :$1000. @;\n"
        "        old = cats('v', column);\n"
        "        output;\n"
        "    end;\n"
        "    keep column old header;\n"
        "run;\n\n"
        "/* Every column is read as text; a cell over 32,767 characters is cut, and a\n"
        "   quoted cell holding a line break is not supported by list input. */\n\n"
        f"data {DATA};\n"
        f"    {infile} firstobs={first_row + 1};\n"
        "    length v1-v&ncols. $32767;\n"
        f"{blank_stop}"
        f"{missing}"
        "run;\n\n"
        "/* Column names: snake_case, at most 32 characters. Accented letters and\n"
        "   other characters become underscores. */\n\n"
        f"{_rename_step(spec)}"
    )


def _read_xlsx(spec: Spec, path: str) -> str:
    sheet = _sq(spec.sheet) if spec.sheet else ""
    if spec.skip_rows:
        target = f'range="{spec.sheet}$A{spec.skip_rows + 1}:XFD1048576"'
        where = f"    {target};\n"
    else:
        where = f"    sheet={_sq(spec.sheet)};\n" if sheet else ""
    return (
        "/* Column headers are kept as written (validvarname=any), then renamed. */\n\n"
        f'proc import datafile="{path}" out={DATA} dbms=xlsx replace;\n'
        f"{where}"
        "    getnames=yes;\n"
        "run;\n\n"
        "proc contents data=" + DATA + " out=work._cols(keep=name varnum "
        "rename=(name=old varnum=column)) noprint;\n"
        "run;\n\n"
        "data work._cols;\n"
        "    set work._cols;\n"
        "    header = old;\n"
        "run;\n\n"
        "proc sort data=work._cols;\n"
        "    by column;\n"
        "run;\n\n"
        f"{_rename_step(spec)}"
    )


def _zip_member(spec: Spec, path: str) -> str:
    """List a ZIP's members; for zip_csv, pick the data file into &member."""
    pick = ""
    if spec.kind == "zip_csv":
        test = (
            f"index(member, {_sq(spec.member_pattern)}) > 0"
            if spec.member_pattern
            else "lowcase(scan(member, -1, '.')) in ('csv', 'txt') and "
            "index(lowcase(member), 'metadata') = 0"
        )
        pick = (
            "\n/* The ZIP may also hold a metadata file; read the data file. */\n\n"
            "%let member = ;\n"
            "proc sql noprint outobs=1;\n"
            f"    select member into :member trimmed from work._members where {test};\n"
            "quit;\n\n"
            "data _null_;\n"
            "    if missing(symget('member')) then do;\n"
            f"        put 'ERROR: no data file found in ' {_sq(spec.url)};\n"
            "        abort cancel;\n"
            "    end;\n"
            "run;\n"
        )
    return (
        f'filename zipin zip "{path}";\n\n'
        "data work._members;\n"
        "    length member $500;\n"
        "    fid = dopen('zipin');\n"
        "    do i = 1 to dnum(fid);\n"
        "        member = dread(fid, i);\n"
        "        output;\n"
        "    end;\n"
        "    rc = dclose(fid);\n"
        "    keep member;\n"
        "run;\n"
        f"{pick}"
    )


# Filters ----------------------------------------------------------------------


def _text(column: str, spec: Spec) -> str:
    """The column's cell as text. Excel numbers are numeric variables: vvalue
    gives their displayed text, as the other languages read them."""
    name = sas_name(column)
    return f"strip(vvalue({name}))" if spec.kind == "xlsx" else name


def _either(tests: list[str], operator: str) -> str:
    return tests[0] if len(tests) == 1 else "(" + operator.join(tests) + ")"


def _filter(item: Filter, spec: Spec) -> list[str]:
    cells = [_text(c, spec) for c in item.columns]
    first = cells[0]
    if item.op == "contains":
        return [f"index(lowcase({first}), {_sq(str(item.value).lower())}) > 0"]
    if item.op == "terms":
        haystack = "lowcase(catx(' ', " + ", ".join(cells) + "))"
        return [
            _either([f"index({haystack}, {_sq(t)}) > 0" for t in group], " or ")
            for group in term_groups(item.value)
        ]
    if item.op == "is":
        return [f"lowcase(strip({first})) = {_sq(str(item.value).strip().lower())}"]
    if item.op == "in":
        values = ", ".join(_sq(str(v).strip().lower()) for v in item.value)
        return [f"lowcase(strip({first})) in ({values})"]
    if item.op == "starts":
        return [f"{first} =: {_sq(item.value)}"]
    symbol = {"eq": "=", "ge": ">=", "le": "<="}[item.op]
    if isinstance(item.value, int | float) and not isinstance(item.value, bool):
        # A missing number is smaller than every number in SAS: leave it out.
        number = f"input({first}, ?? best32.)"
        return [f"not missing({number}) and {number} {symbol} {item.value}"]
    return [f"not missing({first}) and {first} {symbol} {_sq(item.value)}"]


def _filters(spec: Spec) -> str:
    conditions = [c for f in spec.filters for c in _filter(f, spec)]
    if not conditions:
        return ""
    joined = " and\n        ".join(f"({c})" for c in conditions)
    return (
        "/* Keep the rows the MapleStats tool kept. */\n\n"
        f"data {DATA};\n"
        f"    set {DATA};\n"
        f"    if {joined};\n"
        "run;\n"
    )


# Cleaning ---------------------------------------------------------------------

_CLEAN = """\
/* Standard cleaning: trimmed text, and numbers stored as text converted. Empty
   text is already missing in SAS. Codes stay text as the source wrote them:
   columns named like one (coordinate, vector_id, dguid, NAICS, postal code) and
   columns with a leading zero (01, 000000001). A converted column moves to the
   end of the table. */

%macro clean_data;
    %local text_columns convert_rename convert_assign convert_drop;
    %let convert_rename = ;
    proc sql noprint;
        select count(*) into :text_columns trimmed from dictionary.columns
        where libname = 'WORK' and memname = 'MAPLE_DATA' and type = 'char';
    quit;
    %if &text_columns. > 0 %then %do;
        data {data};
            set {data};
            array __text{{*}} _character_;
            do __i = 1 to dim(__text);
                __text{{__i}} = strip(__text{{__i}});
            end;
            drop __i;
        run;

        data _null_;
            set {data} end=__last;
            array __text{{*}} _character_;
            array __seen{{5000}} _temporary_;
            array __bad{{5000}} _temporary_;
            array __zero{{5000}} _temporary_;
            length __rename __assign __drop $32767 __name $32;
            retain __rename __assign __drop '' __k 0 __code_re __zero_re;
            if _n_ = 1 then do;
                __code_re = prxparse('/{code_columns}/');
                __zero_re = prxparse('/{leading_zero}/');
            end;
            do __i = 1 to dim(__text);
                if not missing(__text{{__i}}) then do;
                    __seen{{__i}} = 1;
                    /* best32. reads only 32 characters: longer text is not a number. */
                    if lengthn(__text{{__i}}) > 32 or missing(input(__text{{__i}}, ?? best32.))
                        then __bad{{__i}} = 1;
                    if prxmatch(__zero_re, __text{{__i}}) then __zero{{__i}} = 1;
                end;
            end;
            if __last then do;
                do __i = 1 to dim(__text);
                    __name = vname(__text{{__i}});
                    if __seen{{__i}} and not __bad{{__i}} and not __zero{{__i}}
                        and not prxmatch(__code_re, lowcase(__name)) then do;
                        __k + 1;
                        __rename = catx(' ', __rename, cats(__name, '=__t', __k));
                        __assign = catx(' ', __assign,
                            cats(__name, '=input(__t', __k, ', best32.);'));
                        __drop = catx(' ', __drop, cats('__t', __k));
                    end;
                end;
                call symputx('convert_rename', __rename);
                call symputx('convert_assign', __assign);
                call symputx('convert_drop', __drop);
            end;
        run;

        %if %length(&convert_rename.) > 0 %then %do;
            data {data};
                set {data}(rename=(&convert_rename.));
                &convert_assign.
                drop &convert_drop.;
            run;
        %end;
    %end;
%mend clean_data;
%clean_data;
"""


def _clean() -> str:
    return _CLEAN.format(
        data=DATA,
        code_columns=cleaning.CODE_COLUMNS,
        leading_zero=cleaning.LEADING_ZERO,
    )


def _sort(spec: Spec) -> str:
    if not spec.sort_by:
        return ""
    direction = "descending " if spec.sort_descending else ""
    return (
        "/* Sorted after the cleaning, so numbers sort as numbers. */\n\n"
        f"proc sort data={DATA};\n"
        f"    by {direction}{sas_name(spec.sort_by)};\n"
        "run;\n"
    )


# Render -------------------------------------------------------------------------


def _supported(spec: Spec) -> bool:
    """Whether SAS can fetch and read this spec, with every step it needs."""
    if spec.kind not in ("csv", "zip_csv", "zip", "xlsx", "file"):
        return False
    # A Python read or step means the generic read below is not enough for this
    # source (R's cansim call alone does not); Power Query is skipped on the same test.
    if "sas" not in spec.native and ("python" in spec.native or "python" in spec.prepare):
        return False
    if "sas" not in spec.prepare and "python" in spec.prepare:
        return False
    if spec.kind == "xlsx":
        if spec.sheet and _UNSAFE_DOUBLE_QUOTED.search(spec.sheet):
            return False
        # A range needs the sheet's name.
        if spec.skip_rows and not spec.sheet:
            return False
    return True


def render_sas(spec: Spec, tool: str) -> tuple[str, list[str]] | None:
    spec = _safe_spec(spec)
    if not _supported(spec):
        return None
    path = f"data/raw/{spec.file_name}"
    packages = ["Base SAS 9.4M5 or later (PROC HTTP, hash objects)"]
    download = _download(spec, path)
    if spec.kind == "csv":
        read = download + "\n" + _read_text(spec, '"' + path + '"', spec.skip_rows + 1)
    elif spec.kind == "zip_csv":
        read = (
            download
            + "\n"
            + _zip_member(spec, path)
            + "\n"
            + _read_text(spec, 'zipin("&member.")', spec.skip_rows + 1)
        )
    elif spec.kind == "zip":
        read = (
            download
            + "\n/* SAS reads a ZIP's members directly (filename ZIP); the member list is in\n"
            "   work._members. Read the data file you need with infile zipin('<member>'). */\n\n"
            + _zip_member(spec, path)
        )
    elif spec.kind == "xlsx":
        packages.append("SAS/ACCESS Interface to PC Files (PROC IMPORT dbms=xlsx)")
        read = download + "\n" + _read_xlsx(spec, path)
    else:
        read = download
    setup = _join(
        "/* 0. Setup */\n",
        "options validvarname=any compress=yes;\n\n"
        "data _null_;\n"
        '    if not fileexist("data") then rc = dcreate("data", ".");\n'
        '    if not fileexist("data/raw") then rc = dcreate("raw", "data");\n'
        "run;\n",
    )
    sections = [_header(spec, tool), setup, "/* 1. Read inputs */\n", read]
    if spec.kind not in ("zip", "file"):
        check = (
            "proc sql noprint;\n"
            f"    select count(*) into :row_count trimmed from {DATA};\n"
            "quit;\n\n"
            "data _null_;\n"
            "    if &row_count. = 0 then do;\n"
            f"        put 'ERROR: ' {_sq(spec.url)} ' returned no rows';\n"
            "        abort cancel;\n"
            "    end;\n"
            "run;\n"
        )
        sections += [
            "/* 2. Check inputs */\n",
            check,
            "/* 3. Prepare data */\n",
            _filters(spec),
            _clean(),
            _sort(spec),
        ]
    return _join(*sections), packages

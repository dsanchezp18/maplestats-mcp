"""Render a Spec as a Power Query M query for Excel.

Power Query is built into Excel 2016 and later (Data > Get Data > From
Other Sources > Blank Query > Advanced Editor), so the query needs nothing
installed: it calls the same URL the R, Python, Stata and Julia scripts
call, applies the tool's filters on the source's own column names, then
cleans like the R script (snake_case names, trimmed text, empty text as
null, numbers and ISO dates stored as text converted). Refreshing the
query in Excel fetches the data again.

The layout mirrors the other scripts: a comment header, then numbered
sections as comments inside one `let` expression. Every value a user
supplied reaches M only through m_text(), which doubles quotes and writes
control characters and "#(" as M escapes, so it cannot leave its literal.

What M cannot repeat returns None, and reproduce_code says why: Beyond
20/20 files, RSS feeds, downloads that are not a table (a ZIP the user
picks from, fixed-width text), and tools whose own steps run in Python in
the other scripts (PHAC Health Infobase, CFIA pages, IP Horizons joins).

No Excel was available when this was written (2026-10-02): the M syntax
was checked by a structural parser in the tests and the URLs live, but the
queries have not been run inside Excel. See the module notes.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from maplestats_mcp.modules.reproduce.render import _safe_spec, _trim_comment, comment_text
from maplestats_mcp.modules.reproduce.spec import Filter, Spec

PACKAGES = ["Power Query (built into Excel 2016 or later and Microsoft 365)"]

_SKIPPED_KINDS = ("ivt", "feed", "file", "zip", "none")


def m_text(value: Any) -> str:
    """An M text literal: quotes doubled, control characters and "#(" escaped."""
    out: list[str] = []
    text = str(value)
    for index, ch in enumerate(text):
        code = ord(ch)
        if ch == '"':
            out.append('""')
        elif ch == "#" and text[index + 1 : index + 2] == "(":
            out.append("#(#)")
        elif code < 0x20 or code == 0x7F or ch in "\x85  ":
            out.append(f"#({code:04X})")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def m_value(value: Any) -> str:
    """An M literal for a JSON value (records, lists, text, numbers, logicals)."""
    if isinstance(value, dict):
        fields = ", ".join(f"#{m_text(k)} = {m_value(v)}" for k, v in value.items())
        return f"[{fields}]"
    if isinstance(value, list):
        return "{" + ", ".join(m_value(v) for v in value) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int | float):
        return json.dumps(value)
    return m_text(value)


def _field(column: str) -> str:
    return f"Record.Field(_, {m_text(column)})"


def _filter(item: Filter) -> str:
    cell = _field(item.columns[0])
    if item.op == "contains":
        return f"Text.Contains(Text.Lower(AsText({cell})), {m_text(str(item.value).lower())})"
    if item.op == "terms":
        cells = ", ".join(f"AsText({_field(c)})" for c in item.columns)
        haystack = f'Text.Lower(Text.Combine({{{cells}}}, " "))'
        return " and ".join(
            f"Text.Contains({haystack}, {m_text(term)})" for term in str(item.value).lower().split()
        )
    if item.op == "is":
        return f"Text.Lower(Text.Trim(AsText({cell}))) = {m_text(str(item.value).strip().lower())}"
    if item.op == "starts":
        return f"Text.StartsWith(AsText({cell}), {m_text(str(item.value))})"
    symbol = {"eq": "=", "ge": ">=", "le": "<="}[item.op]
    if isinstance(item.value, int | float) and not isinstance(item.value, bool):
        return f"(let n = AsNumber({cell}) in n <> null and n {symbol} {json.dumps(item.value)})"
    return f'(let t = AsText({cell}) in t <> "" and t {symbol} {m_text(str(item.value))})'


def _request(spec: Spec) -> str:
    """Web.Contents for the URL, with the POST body and headers the tool sent."""
    headers = dict(spec.headers)
    content = ""
    if spec.post_json is not None:
        headers["Content-Type"] = "application/json"
        content = f"Content = Json.FromValue({m_value(spec.post_json)})"
    elif spec.post_form:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        content = f"Content = Text.ToBinary(Uri.BuildQueryString({m_value(spec.post_form)}))"
    options = []
    if headers:
        pairs = ", ".join(f"#{m_text(k)} = {m_text(v)}" for k, v in headers.items())
        options.append(f"Headers = [{pairs}]")
    if content:
        options.append(content)
    extra = f", [{', '.join(options)}]" if options else ""
    return f"Web.Contents({m_text(spec.url)}{extra})"


# A ZIP's central directory names every member and where its data starts;
# reading it (not the local headers) also works for archives whose local
# headers leave the sizes to a trailing data descriptor. Checked
# 2026-10-02 against StatCan's 18100004-eng.zip, which has no archive
# comment, so the end-of-directory record is the last 22 bytes. Method 8 is
# raw deflate, which Binary.Decompress(..., Compression.Deflate) reads.
_UNZIP = """\
    // Power Query has no ZIP reader: this lists the archive's files from its
    // central directory and inflates each one.
    UnzipFiles = (archive as binary) as table =>
        let
            Bytes = Binary.Buffer(archive),
            U16 = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger16, ByteOrder.LittleEndian),
            U32 = BinaryFormat.ByteOrder(BinaryFormat.UnsignedInteger32, ByteOrder.LittleEndian),
            Read16 = (offset as number) as number => U16(Binary.Range(Bytes, offset, 2)),
            Read32 = (offset as number) as number => U32(Binary.Range(Bytes, offset, 4)),
            DirectoryEnd = Binary.Length(Bytes) - 22,
            EntryCount = Read16(DirectoryEnd + 10),
            DirectoryStart = Read32(DirectoryEnd + 16),
            Entries = List.Generate(
                () => [Offset = DirectoryStart, Index = 0],
                each [Index] < EntryCount,
                each [
                    Offset = [Offset] + 46 + Read16([Offset] + 28) + Read16([Offset] + 30)
                        + Read16([Offset] + 32),
                    Index = [Index] + 1
                ],
                each [
                    FileName = Text.FromBinary(
                        Binary.Range(Bytes, [Offset] + 46, Read16([Offset] + 28)), TextEncoding.Utf8
                    ),
                    Method = Read16([Offset] + 10),
                    CompressedSize = Read32([Offset] + 20),
                    LocalOffset = Read32([Offset] + 42)
                ]
            ),
            Files = List.Transform(
                Entries,
                (entry) =>
                    let
                        DataStart = entry[LocalOffset] + 30 + Read16(entry[LocalOffset] + 26)
                            + Read16(entry[LocalOffset] + 28),
                        Packed = Binary.Range(Bytes, DataStart, entry[CompressedSize]),
                        Content = if entry[Method] = 8
                            then Binary.Decompress(Packed, Compression.Deflate)
                            else Packed
                    in
                        [FileName = entry[FileName], Content = Content]
            )
        in
            Table.FromRecords(Files, {"FileName", "Content"}),
"""

_HELPERS = """\
    // Cell values as text or number, null-safe, for the filters and checks.
    AsText = (value as any) as text =>
        if value = null then "" else (try Text.From(value) otherwise ""),
    AsNumber = (value as any) as nullable number =>
        if value = null then null else (try Number.From(value, "en-US") otherwise null),
    // Records to a table with every field any record has, not only the first's.
    ToTable = (records as list) as table =>
        Table.FromRecords(
            records,
            List.Distinct(List.Combine(List.Transform(records, Record.FieldNames))),
            MissingField.UseNull
        ),
"""

# janitor's clean_names in R strips accents; M has no such function, so
# the French and other Latin accents StatCan and other sources use map
# explicitly.
_ACCENTS = {
    "à": "a", "â": "a", "ä": "a", "á": "a", "ç": "c", "é": "e", "è": "e", "ê": "e", "ë": "e",
    "î": "i", "ï": "i", "í": "i", "ô": "o", "ö": "o", "ó": "o", "ù": "u", "û": "u", "ü": "u",
    "ú": "u", "ÿ": "y", "ñ": "n", "œ": "oe", "æ": "ae",
}  # fmt: skip


def _accents_record() -> str:
    pairs = {**_ACCENTS, **{k.upper(): v.upper() for k, v in _ACCENTS.items()}}
    pairs["Œ"], pairs["Æ"] = "OE", "AE"
    return "[" + ", ".join(f"#{m_text(k)} = {m_text(v)}" for k, v in pairs.items()) + "]"


def _cleaning(previous: str) -> str:
    return f"""\
    // Standard cleaning, as the R script's clean_names() and type_convert():
    // snake_case names without accents (PÉRIODE -> periode, referenceNumber ->
    // reference_number), names that clean alike numbered (indicator,
    // indicator_2), trimmed text, empty text as null, then columns whose
    // every value is a number or an ISO date (YYYY-MM-DD) converted.
    Accents = {_accents_record()},
    CleanName = (name as text) as text =>
        let
            Plain = Text.Combine(
                List.Transform(Text.ToList(name), (ch) => Record.FieldOrDefault(Accents, ch, ch))
            ),
            Words = Splitter.SplitTextByCharacterTransition({{"a".."z", "0".."9"}}, {{"A".."Z"}})(
                Plain
            ),
            Lower = Text.Lower(Text.Combine(Words, "_")),
            Spaced = Text.Combine(
                List.Transform(
                    Text.ToList(Lower), (ch) => if List.Contains(NameCharacters, ch) then ch else " "
                )
            ),
            Snake = Text.Combine(List.Select(Text.Split(Spaced, " "), (part) => part <> ""), "_")
        in
            if Snake = "" then "x" else Snake,
    NameCharacters = {{"a".."z", "0".."9"}},
    OldNames = Table.ColumnNames({previous}),
    CleanNames = List.Transform(OldNames, CleanName),
    NewNames = List.Transform(
        List.Positions(CleanNames),
        (i) =>
            let
                Earlier = List.Count(
                    List.Select(List.FirstN(CleanNames, i), (name) => name = CleanNames{{i}})
                )
            in
                if Earlier = 0 then CleanNames{{i}} else CleanNames{{i}} & "_" & Text.From(Earlier + 1)
    ),
    Renamed = Table.RenameColumns(
        {previous},
        List.Select(List.Zip({{OldNames, NewNames}}), (pair) => pair{{0}} <> pair{{1}})
    ),
    Trimmed = Table.TransformColumns(
        Renamed,
        List.Transform(
            Table.ColumnNames(Renamed),
            (name) =>
                {{
                    name,
                    (value) =>
                        if value is text
                        then (if Text.Trim(value) = "" then null else Text.Trim(value))
                        else value
                }}
        )
    ),
    IsNumberText = (value as any) as logical =>
        value is number
        or (value is text and (try Number.FromText(value, "en-US") otherwise null) <> null),
    IsIsoDate = (value as any) as logical =>
        value is text
        and Text.Length(value) = 10
        and Text.Middle(value, 4, 1) = "-"
        and Text.Middle(value, 7, 1) = "-"
        and (try Date.FromText(value, "en-US") otherwise null) <> null,
    ColumnsWhere = (table as table, test as function) as list =>
        List.Select(
            Table.ColumnNames(table),
            (name) =>
                let
                    Values = List.RemoveNulls(Table.Column(table, name))
                in
                    not List.IsEmpty(Values) and List.AllTrue(List.Transform(Values, test))
        ),
    // Codes stay text as the source wrote them: columns named like one
    // (coordinate, vector_id, dguid, NAICS, postal code; StatCan's "2.1" and
    // "2.10" are different coordinates) and columns with a leading zero (01).
    CodeName = (name as text) as logical =>
        List.Contains(
            {{"coordinate", "vector", "vector_id", "vectorid", "product_id", "productid", "pid",
              "dguid", "postal_code", "postalcode", "fsa", "noc", "sgc"}},
            name
        )
        or Text.EndsWith(name, "_dguid")
        or Text.EndsWith(name, "_postal_code")
        or Text.Contains(name, "naics")
        or Text.StartsWith(name, "noc_")
        or Text.EndsWith(name, "_noc")
        or Text.StartsWith(name, "sgc_")
        or Text.EndsWith(name, "_sgc"),
    HasLeadingZero = (value as any) as logical =>
        value is text
        and (
            let
                Digits = if Text.StartsWith(value, "-") then Text.Middle(value, 1) else value
            in
                Text.Length(Digits) > 1
                and Text.Start(Digits, 1) = "0"
                and List.Contains({{"0".."9"}}, Text.Middle(Digits, 1, 1))
        ),
    CodeColumns = List.Select(
        Table.ColumnNames(Trimmed),
        (name) => CodeName(name) or List.AnyTrue(List.Transform(Table.Column(Trimmed, name), HasLeadingZero))
    ),
    Codes = Table.TransformColumns(
        Trimmed,
        List.Transform(
            CodeColumns,
            (name) =>
                {{
                    name,
                    (value) =>
                        if value = null then null
                        else if value is number then Number.ToText(value, "G", "en-US")
                        else Text.From(value),
                    type text
                }}
        )
    ),
    NumberColumns = List.Difference(ColumnsWhere(Codes, IsNumberText), CodeColumns),
    Numbers = Table.TransformColumnTypes(
        Codes, List.Transform(NumberColumns, (name) => {{name, type number}}), "en-US"
    ),
    DateColumns = ColumnsWhere(Numbers, IsIsoDate),
    Cleaned = Table.TransformColumns(
        Numbers,
        List.Transform(
            DateColumns,
            (name) => {{name, (value) => if value = null then null else Date.FromText(value, "en-US"), type date}}
        )
    ),
"""


def _scaled(value: str, power: str, name: str, comment: str) -> str:
    return (
        f"    // {comment}\n"
        f"    Data = Table.AddColumn(\n"
        f"        Cleaned,\n"
        f"        {m_text(name)},\n"
        f"        each if [{value}] = null or [{power}] = null then null\n"
        f"            else [{value}] * Number.Power(10, [{power}]),\n"
        f"        type number\n"
        f"    )\n"
    )


def _specific(source: str) -> str:
    """The source-specific step, on cleaned names; the last step is Data."""
    if source == "statcan_table":
        return _scaled(
            "value",
            "scalar_id",
            "value_normalized",
            "value is in the unit named by scalar_factor; scalar_id is its power of ten.",
        )
    if source == "statcan_table_fr":
        return _scaled(
            "valeur",
            "identificateur_scalaire",
            "valeur_normalisee",
            "valeur est dans l'unité de facteur_scalaire; identificateur_scalaire en est "
            "la puissance de dix.",
        )
    if source == "statcan_vectors":
        return _scaled(
            "value",
            "scalar_factor_code",
            "value_normalized",
            "scalar_factor_code is the value's power of ten; ref_per is the reference date.",
        )
    return "    Data = Cleaned\n"


def _records(spec: Spec) -> str | None:
    """M steps from the parsed JSON (Payload) to a table (Loaded)."""

    def walk(root: str, keys: list[str]) -> str:
        for key in keys:
            root = f"Record.Field({root}, {m_text(key)})"
        return root

    if spec.columnar:
        return (
            "    // One list per column.\n"
            "    Loaded = Table.FromColumns(Record.FieldValues(Payload), Record.FieldNames(Payload)),\n"
        )
    if spec.single_object:
        return "    // One record: one row.\n    Loaded = Table.FromRecords({Payload}),\n"
    if spec.records_dict:
        rows = walk("Payload", spec.records_path)
        return (
            "    // Records keyed by name: one row each, the name in key.\n"
            f"    Keyed = {rows},\n"
            "    Records = List.Transform(\n"
            "        Record.FieldNames(Keyed), (key) => Record.Combine({[key = key], Record.Field(Keyed, key)})\n"
            "    ),\n"
            "    Loaded = ToTable(Records),\n"
        )
    if spec.name_value:
        rows = walk("Payload", spec.records_path)
        return (
            "    // Each row is a list of {Name, Value: {Literal}} cells.\n"
            "    Records = List.Transform(\n"
            f"        {rows},\n"
            "        (row) =>\n"
            "            Record.FromList(\n"
            "                List.Transform(row, (cell) => try cell[Value][Literal] otherwise null),\n"
            "                List.Transform(row, (cell) => cell[Name])\n"
            "            )\n"
            "    ),\n"
            "    Loaded = ToTable(Records),\n"
        )
    if spec.each_item:
        parent = walk("item", spec.records_path[:-1])
        last = m_text(spec.records_path[-1])
        # WDS keeps vectorId, productId and coordinate on the object that
        # holds vectorDataPoint, not on each point, so each row gets them.
        return (
            "    // One object per requested item; its rows carry the item's own fields\n"
            "    // (for WDS: vectorId, productId, coordinate).\n"
            "    Records = List.Combine(\n"
            "        List.Transform(\n"
            "            Payload,\n"
            "            (item) =>\n"
            "                let\n"
            f"                    Parent = {parent},\n"
            "                    Scalars = Record.SelectFields(\n"
            "                        Parent,\n"
            "                        List.Select(\n"
            "                            Record.FieldNames(Parent),\n"
            "                            (name) =>\n"
            "                                not (Record.Field(Parent, name) is list or Record.Field(Parent, name) is record)\n"
            "                        )\n"
            "                    )\n"
            "                in\n"
            f"                    List.Transform(Record.Field(Parent, {last}), (row) => Record.Combine({{Scalars, row}}))\n"
            "        )\n"
            "    ),\n"
            "    Loaded = ToTable(Records),\n"
        )
    rows = walk("Payload", spec.records_path)
    if spec.record_field:
        rows = f"List.Transform({rows}, (row) => Record.Field(row, {m_text(spec.record_field)}))"
    return f"    Loaded = ToTable({rows}),\n"


def _read(spec: Spec) -> tuple[str, str] | None:
    """(helper steps for 0. Setup, steps for 1. Read inputs ending in Loaded)."""
    raw = f"    Raw = {_request(spec)},\n"
    csv_options = (
        f"[Delimiter = {m_text(spec.delimiter)}, Encoding = 65001, QuoteStyle = QuoteStyle.Csv]"
    )
    promote = "    Loaded = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),\n"
    if spec.kind == "csv" and (spec.skip_rows or spec.stop_at_blank):
        lines = f"List.Skip(Lines.FromBinary(Raw, null, null, 65001), {spec.skip_rows})"
        if spec.stop_at_blank:
            lines = f'List.FirstN({lines}, each Text.Trim(_) <> "")'
        return "", (
            raw
            + f"    {_trim_comment('//', spec).strip()}\n"
            + f"    Body = {lines},\n"
            + f'    Csv = Csv.Document(Text.Combine(Body, "#(cr,lf)"), {csv_options}),\n'
            + promote
        )
    if spec.kind == "csv":
        return "", raw + f"    Csv = Csv.Document(Raw, {csv_options}),\n" + promote
    if spec.kind == "zip_csv":
        if spec.member_pattern:
            test = f"Text.Contains([FileName], {m_text(spec.member_pattern)})"
        else:
            test = (
                '(Text.EndsWith(Text.Lower([FileName]), ".csv") or Text.EndsWith(Text.Lower([FileName]), ".txt"))\n'
                '            and not Text.Contains(Text.Lower([FileName]), "metadata")'
            )
        return _UNZIP, (
            raw
            + "    // The ZIP may also hold a metadata file; read the data file.\n"
            + "    DataFile = Table.SelectRows(\n"
            + "        UnzipFiles(Raw),\n"
            + f"        each {test}\n"
            + "    ){0}[Content],\n"
            + f"    Csv = Csv.Document(DataFile, {csv_options}),\n"
            + promote
        )
    if spec.kind == "xlsx":
        pick = f" and [Item] = {m_text(spec.sheet)}" if spec.sheet else ""
        skip = f"Table.Skip(Sheet, {spec.skip_rows})" if spec.skip_rows else "Sheet"
        return "", (
            raw
            + "    Book = Excel.Workbook(Raw, null, true),\n"
            + f'    Sheet = Table.SelectRows(Book, each [Kind] = "Sheet"{pick}){{0}}[Data],\n'
            + f"    Loaded = Table.PromoteHeaders({skip}, [PromoteAllScalars = true]),\n"
        )
    if spec.kind == "json":
        records = _records(spec)
        if records is None:
            return None
        return "", raw + "    Payload = Json.Document(Raw),\n" + records
    if spec.kind == "sdmx":
        return "", sdmx_generic_steps(spec.url)
    if spec.kind == "html_table":
        return "", (
            raw
            + "    // Web.Page parses every table on the page; take the one the tool read.\n"
            + '    Tables = Table.SelectRows(Web.Page(Text.FromBinary(Raw)), each [Kind] = "Table"),\n'
            + f"    Loaded = Tables{{{spec.html_table_index}}}[Data],\n"
        )
    return None


def sdmx_generic_steps(url: str) -> str:
    """Read steps for StatCan SDMX-ML (GenericData) into one row per observation.

    Checked live 2026-10-02 on data/DF_18100004/2.2: StatCan answers only
    with GenericData XML (CSV Accept headers get HTTP 406). Each
    <generic:Series> holds a SeriesKey and an Attributes block of
    <generic:Value id= value=/> elements, then <generic:Obs> elements with an
    ObsDimension (the period) and an ObsValue. Xml.Document names elements
    by their local name, so the namespace prefixes do not matter.
    """
    return f"""\
    Raw = Web.Contents({m_text(url)}),
    // SDMX-ML: each Series carries its key and attributes as <Value id= value=/>.
    Attribute = (attributes as table, name as text) as any =>
        let
            Match = Table.SelectRows(attributes, each [Name] = name)
        in
            if Table.IsEmpty(Match) then null else Match{{0}}[Value],
    Child = (node as table, name as text) as table =>
        let
            Match = Table.SelectRows(node, each [Name] = name)
        in
            if Table.IsEmpty(Match) or not (Match{{0}}[Value] is table)
            then #table({{"Name", "Attributes"}}, {{}})
            else Match{{0}}[Value],
    IdValues = (part as table) as record =>
        Record.FromList(
            List.Transform(part[Attributes], (a) => Attribute(a, "value")),
            List.Transform(part[Attributes], (a) => Attribute(a, "id"))
        ),
    ObsValue = (obs as table, name as text) as any =>
        let
            Match = Table.SelectRows(obs, each [Name] = name)
        in
            if Table.IsEmpty(Match) then null else Attribute(Match{{0}}[Attributes], "value"),
    Document = Xml.Document(Raw),
    DataSet = Child(Document{{0}}[Value], "DataSet"),
    SeriesList = Table.SelectRows(DataSet, each [Name] = "Series")[Value],
    Records = List.Combine(
        List.Transform(
            SeriesList,
            (series) =>
                let
                    Fields = Record.Combine(
                        {{IdValues(Child(series, "SeriesKey")), IdValues(Child(series, "Attributes"))}}
                    ),
                    Observations = Table.SelectRows(series, each [Name] = "Obs")[Value]
                in
                    List.Transform(
                        Observations,
                        (obs) =>
                            Record.Combine(
                                {{
                                    Fields,
                                    IdValues(Child(obs, "Attributes")),
                                    [
                                        TIME_PERIOD = ObsValue(obs, "ObsDimension"),
                                        OBS_VALUE = ObsValue(obs, "ObsValue")
                                    ]
                                }}
                            )
                    )
        )
    ),
    Observed = ToTable(Records),
    // SCALAR_FACTOR is the value's power of ten (0 units, 3 thousands, 6 millions).
    Loaded = Table.AddColumn(
        Observed,
        "OBS_VALUE_NORMALIZED",
        each
            let
                Value = AsNumber([OBS_VALUE]),
                Power = AsNumber(Record.FieldOrDefault(_, "SCALAR_FACTOR", 0))
            in
                if Value = null or Power = null then null else Value * Number.Power(10, Power),
        type number
    ),
"""


def _header(spec: Spec, tool: str) -> str:
    rule = "// " + "=" * 60
    details = "".join(f"// {comment_text(line)}\n" for line in spec.details)
    return (
        f"{rule}\n"
        f"// {comment_text(spec.title or 'Reproduce ' + tool)}\n"
        f"// Purpose: Fetch the data behind MapleStats MCP's {comment_text(tool)}\n"
        f"//          ({comment_text(spec.method)})\n"
        f"// Inputs:  {comment_text(spec.url)}\n"
        f"{details}"
        "// Outputs: the prepared table, loaded to a worksheet or the Data Model\n"
        "// How to run: Excel > Data > Get Data > From Other Sources > Blank Query >\n"
        "//   Advanced Editor; paste this query, Done, then Close & Load. Answer the\n"
        "//   first prompt with Anonymous access; Data > Refresh All fetches it again.\n"
        "//   A worksheet holds 1,048,576 rows: load a larger table (a full StatCan\n"
        "//   table can be) with Close & Load To > Only Create Connection > Add this\n"
        "//   data to the Data Model.\n"
        f"{rule}\n"
    )


def render_excel(spec: Spec, tool: str) -> tuple[str, list[str]] | None:
    """A Power Query M query, or None where M cannot repeat the steps."""
    spec = _safe_spec(spec)
    native = spec.native.get("excel")
    if native is None and (
        spec.kind in _SKIPPED_KINDS or "python" in spec.native or "python" in spec.prepare
    ):
        return None
    read = ("", native.body) if native else _read(spec)
    if read is None:
        return None
    unzip, load = read
    if native and native.imports:
        # An excel native Code names the URL it fetches as its one import
        # (M has no imports); the header and the row check name that URL.
        spec = dataclasses.replace(spec, url=native.imports[0])
    prepare: list[str] = []
    # M is lazy: a step nothing depends on never runs, so the first prepare
    # step reads Checked and the row check always runs.
    last = "Checked"
    # Byte-order marks and the source's header marker would otherwise stay in
    # the first column's name, and the filters name columns as the source does.
    marker = spec.header_prefix
    strip = (
        f"if Text.StartsWith(name, {m_text(marker)}) then Text.Middle(name, {len(marker)}) else name"
        if marker
        else "name"
    )
    if (spec.kind in ("csv", "zip_csv") and native is None) or marker:
        prepare.append(
            "    Headers = Table.TransformColumnNames(\n"
            f"        {last},\n"
            "        (column) =>\n"
            "            let\n"
            "                name = Text.Trim(column, {Character.FromNumber(65279)})\n"
            "            in\n"
            f"                {strip}\n"
            "    ),\n"
        )
        last = "Headers"
    if spec.na_values:
        prepare.append(
            f"    // The source writes missing cells as {comment_text(', '.join(spec.na_values))}.\n"
            "    Missing = Table.TransformColumns(\n"
            f"        {last},\n"
            "        List.Transform(\n"
            f"            Table.ColumnNames({last}),\n"
            "            (name) =>\n"
            f"                {{name, (value) => if List.Contains({m_value(spec.na_values)}, value) then null else value}}\n"
            "        )\n"
            "    ),\n"
        )
        last = "Missing"
    if spec.filters:
        conditions = "\n            and ".join(_filter(f) for f in spec.filters)
        prepare.append(
            "    // Keep the rows the MapleStats tool kept.\n"
            f"    Filtered = Table.SelectRows(\n        {last},\n        each {conditions}\n    ),\n"
        )
        last = "Filtered"
    if spec.sort_by:
        order = "Order.Descending" if spec.sort_descending else "Order.Ascending"
        prepare.append(
            f"    Sorted = Table.Sort({last}, {{{{{m_text(spec.sort_by)}, {order}}}}}),\n"
        )
        last = "Sorted"
    if spec.source == "valet":
        prepare.append(
            "    // Valet nests each series as <series>[v]; make one row per date and series.\n"
            f'    Long = Table.UnpivotOtherColumns({last}, {{"d"}}, "series", "cell"),\n'
            "    Valued = Table.AddColumn(\n"
            '        Long, "value", each try Number.From([cell][v], "en-US") otherwise null, type number\n'
            "    ),\n"
            '    Tidy = Table.RenameColumns(Table.SelectColumns(Valued, {"d", "series", "value"}), {{"d", "date"}}),\n'
        )
        last = "Tidy"
    prepare.append(_cleaning(last))
    prepare.append(_specific("" if native else spec.source))
    check = (
        "    // Stop with a clear message instead of loading an empty table.\n"
        "    Checked = if Table.IsEmpty(Loaded)\n"
        f'        then error Error.Record("MapleStats", {m_text(spec.url + " returned no rows")})\n'
        "        else Loaded,\n"
    )
    body = (
        "let\n"
        "    // 0. Setup\n"
        + _HELPERS
        + unzip
        + "    // 1. Read inputs\n"
        + load
        + "    // 2. Check inputs\n"
        + check
        + "    // 3. Prepare data\n"
        + "".join(prepare)
    )
    return _header(spec, tool) + body + "in\n    Data\n", PACKAGES
